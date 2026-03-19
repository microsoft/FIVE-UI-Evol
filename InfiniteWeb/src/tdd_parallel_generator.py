"""
TDD Parallel Generator
Generates implementation and tests in parallel based on interfaces
"""

import json
import re
import os
import subprocess
import tempfile
import asyncio
from typing import List, Dict, Any, Tuple
from llm_caller import call_openai_api_json_async
import threading


class TDDParallelGenerator:
    """Generates implementation and tests in parallel for TDD"""

    def __init__(self, logger=None, model=None, reasoning_effort="medium"):
        self.logger = logger
        self.model = model
        self.reasoning_effort = reasoning_effort

    @staticmethod
    def _check_js_syntax(code: str) -> str:
        """Check JavaScript syntax using node -c. Returns error message or empty string."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', encoding='utf-8', delete=False) as f:
            f.write(code)
            f.flush()
            try:
                proc = subprocess.run(
                    ['node', '-c', f.name],
                    capture_output=True, text=True, timeout=10,
                )
                return proc.stderr.strip() if proc.returncode != 0 else ""
            except Exception as e:
                return str(e)
            finally:
                os.unlink(f.name)

    @staticmethod
    def _fix_js_quotes(code: str, max_iterations: int = 20) -> str:
        """Fix single-quote syntax errors in generated JavaScript iteratively.

        Uses node -c to find the exact error line, then fixes ONLY that line
        by converting its single-quoted string to use backticks.
        Repeats until no more syntax errors or max iterations reached.
        """
        for iteration in range(max_iterations):
            err = TDDParallelGenerator._check_js_syntax(code)
            if not err:
                return code

            # Extract error line number
            m = re.search(r':(\d+)', err)
            if not m:
                return code
            err_line = int(m.group(1)) - 1  # 0-indexed
            lines = code.split('\n')
            if err_line < 0 or err_line >= len(lines):
                return code

            line = lines[err_line]

            # Case 1: Line has an unclosed single-quoted string (bare newline)
            # e.g., console.log('\n or subtitle: '\n
            unescaped_quotes = [m.start() for m in re.finditer(r"(?<!\\)'", line)]
            if len(unescaped_quotes) % 2 == 1:
                # Odd quotes = unclosed string. Find the opening quote on this line
                # and the closing quote on a subsequent line
                open_pos = unescaped_quotes[-1]  # last unmatched quote
                # Find closing on next lines
                for j in range(err_line + 1, min(err_line + 10, len(lines))):
                    close_quotes = [m.start() for m in re.finditer(r"(?<!\\)'", lines[j])]
                    if close_quotes:
                        close_line = j
                        close_pos = close_quotes[0]
                        # Escape backticks and ${} in the content between open and close
                        # For the opening line: content after open_pos
                        opening_content = line[open_pos+1:]
                        opening_content = opening_content.replace('`', '\\`').replace('${', '\\${')
                        lines[err_line] = line[:open_pos] + '`' + opening_content
                        # For middle lines
                        for k in range(err_line + 1, close_line):
                            lines[k] = lines[k].replace('`', '\\`').replace('${', '\\${')
                        # For the closing line: content before close_pos
                        cl = lines[close_line]
                        closing_content = cl[:close_pos]
                        closing_content = closing_content.replace('`', '\\`').replace('${', '\\${')
                        lines[close_line] = closing_content + '`' + cl[close_pos+1:]
                        code = '\n'.join(lines)
                        break
                else:
                    # Can't find closing quote, give up on this error
                    return code
                continue

            # Case 2: Line has too many single quotes (embedded quotes in string)
            # e.g., code: 'curl ... -d '{"key":"val"}''
            if len(unescaped_quotes) >= 4:
                first_q = unescaped_quotes[0]
                last_q = unescaped_quotes[-1]
                before = line[:first_q]
                inner = line[first_q+1:last_q].replace('`', '\\`').replace('${', '\\${')
                after = line[last_q+1:]
                lines[err_line] = before + '`' + inner + '`' + after
                code = '\n'.join(lines)
                continue

            # Case 3: Other syntax error on this line — can't auto-fix
            return code

        return code
    
    async def generate_parallel(self, tasks: List[Dict[str, Any]], 
                                data_models: Dict[str, Any],
                                interfaces: Dict[str, Any],
                                website_type: str,
                                generated_data: Dict[str, Any]) -> Tuple[str, str]:
        """
        Generate implementation and tests in parallel
        
        Args:
            tasks: User tasks
            data_models: Data models
            interfaces: Interface definitions
            website_type: Type of website
            generated_data: Pre-generated data for test consistency
            
        Returns:
            Tuple of (implementation_code, test_code)
        """
        if self.logger:
            self.logger.start_stage("Parallel Generation", "backend")
            self.logger.log_info("Starting parallel generation of implementation and tests...")
            self.logger.log_info(f"Using pre-generated data for test consistency ({len(generated_data)} entity types)")
        
        try:
            # Create tasks for parallel execution
            impl_task = self._generate_implementation(tasks, data_models, interfaces, website_type)
            test_task = self._generate_tests(tasks, data_models, interfaces, website_type, generated_data)
            
            # Execute in parallel
            results = await asyncio.gather(impl_task, test_task)
        except Exception as e:
            import traceback
            if self.logger:
                self.logger.log_error(f"Error in parallel generation: {str(e)}")
                self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
            raise
        
        implementation = results[0]
        tests = results[1]

        # Post-generation syntax check and fix for test_flows.js
        syntax_err = self._check_js_syntax(tests)
        if syntax_err:
            if self.logger:
                self.logger.log_warning(f"test_flows.js has syntax error, attempting fix: {syntax_err[:100]}")
            tests = self._fix_js_quotes(tests)
            syntax_err2 = self._check_js_syntax(tests)
            if not syntax_err2:
                if self.logger:
                    self.logger.log_info("✅ test_flows.js syntax error fixed successfully")
            else:
                # Fix failed — regenerate test_flows.js from scratch (up to 3 retries)
                for retry in range(3):
                    if self.logger:
                        self.logger.log_warning(f"Regenerating test_flows.js from scratch (retry {retry + 1}/3)")
                    tests = await self._generate_tests(
                        tasks, data_models, interfaces, website_type, generated_data
                    )
                    syntax_err3 = self._check_js_syntax(tests)
                    if not syntax_err3:
                        if self.logger:
                            self.logger.log_info(f"✅ test_flows.js regenerated successfully on retry {retry + 1}")
                        break
                    # Try fix on the regenerated code too
                    tests = self._fix_js_quotes(tests)
                    if not self._check_js_syntax(tests):
                        if self.logger:
                            self.logger.log_info(f"✅ test_flows.js fixed after regeneration retry {retry + 1}")
                        break
                    if self.logger:
                        self.logger.log_warning(f"test_flows.js still broken after retry {retry + 1}: {syntax_err3[:80]}")

        if self.logger:
            self.logger.log_info("Successfully generated implementation and tests in parallel")
            self.logger.end_stage("Parallel Generation")
        
        return implementation, tests
    
    async def _generate_implementation(self, tasks: List[Dict[str, Any]],
                                       data_models: Dict[str, Any],
                                       interfaces: Dict[str, Any],
                                       website_type: str) -> str:
        """Generate the business logic implementation"""
        
        # Use regular string concatenation to avoid f-string issues with braces
        prompt = """
        You are an expert JavaScript developer. Generate a complete business logic implementation.
        
        Website Type: """ + website_type + """
        Tasks: """ + json.dumps(tasks, indent=2) + """
        Data Models: """ + json.dumps(data_models, indent=2) + """
        Interfaces: """ + json.dumps(interfaces, indent=2) + """
        
        REQUIREMENTS:
        1. Implement ALL core interfaces specified
        2. Add helper functions as needed (prefix with _ for private)
        3. Use localStorage for ALL data persistence (browser-compatible)
        4. NO DOM APIs (document.querySelector, addEventListener, innerHTML, etc). window/globalThis references are allowed ONLY in the final export block. The export block MUST include: window.WebsiteSDK = new BusinessLogic(); and module.exports = BusinessLogic;
        5. Must work in both browser and Node.js environments (with localStorage polyfill)
        6. Keep business logic PURE - no test code in this class
        7. All data must be JSON serializable for localStorage
        8. Implement interfaces with positional arguments only to keep consistent with usage
        9. As localStorage is limited in size, when implementing interfaces about upload big data like uploadVideo, simulate the upload by storing metadata only (e.g., URL, title, description) instead of actual file data
        10. IMPORTANT - Foreign Key Resolution for Getter Functions:
           When implementing getter functions that return items containing foreign key references (fields ending with "Id" like productId, gameId, categoryId):
           - The getter MUST resolve these foreign keys to include the full referenced object for display purposes
           - Use the field name without "Id" suffix as the property name for the resolved object
           - Example: if an item has "productId", include "product" with the full product object
           - Pattern:
             getWishlistItems() {
               const items = this._getFromStorage('wishlistitems', []);
               const products = this._getFromStorage('products', []);
               return items.map(item => ({
                 ...item,
                 product: products.find(p => p.id === item.productId) || null
               }));
             }
           - This ensures frontend code can directly access item.product.title, item.product.price, etc. without additional lookups
           - Apply this pattern to ALL getter functions that return items with foreign key fields
        11. IMPORTANT - Enum Value Naming Convention:
           Fields with "type": "enum" in data models or interface definitions are stored as plain strings in localStorage.
           When comparing or filtering by these fields in the implementation:
           - Always use the exact values from the enum's "values" list — do NOT invent synonyms or alternate spellings
           - All enum values use lowercase_snake_case format (e.g., 'in_progress', 'pending_review')
           - Do NOT use camelCase, Title Case, UPPER_CASE, or hyphen-case for enum comparisons
           - This applies to BOTH data model fields AND interface parameter/return properties that have "type": "enum"
        12. When filtering or matching, consider hierarchical relationships
           between entities in the data model.
        13. Null safety: data fields may be null or undefined. Always guard before calling methods like .toFixed(), .toLowerCase(), .includes() or accessing nested properties. Use patterns like (value != null ? value.toFixed(1) : '0.0').

        **CRITICAL DATA REQUIREMENTS**
        - Do not mock data , use the data from localStorage.

        STRUCTURE (use this exact skeleton, implement ALL interface methods with real logic):
        ```javascript
        // localStorage polyfill for Node.js and environments without localStorage
        const localStorage = (function () {
          try {
            if (typeof globalThis !== "undefined" && globalThis.localStorage) {
              return globalThis.localStorage;
            }
          } catch (e) {}
          var store = {};
          return {
            getItem: function (key) {
              return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null;
            },
            setItem: function (key, value) { store[key] = String(value); },
            removeItem: function (key) { delete store[key]; },
            clear: function () { store = {}; },
            key: function (index) { return Object.keys(store)[index] || null; },
            get length() { return Object.keys(store).length; }
          };
        })();

        class BusinessLogic {
          constructor() {
            this._initStorage();
            this.idCounter = this._getNextIdCounter();
          }
          _initStorage() { /* Initialize all data tables from data models in localStorage if not exist */ }
          _getFromStorage(key) { const d = localStorage.getItem(key); return d ? JSON.parse(d) : []; }
          _saveToStorage(key, data) { localStorage.setItem(key, JSON.stringify(data)); }
          _getNextIdCounter() { const c = parseInt(localStorage.getItem('idCounter') || '1000'); localStorage.setItem('idCounter', (c+1).toString()); return c+1; }
          _generateId(prefix) { return prefix + '_' + this._getNextIdCounter(); }

          // Implement ALL interface methods here with complete, working logic.
          // Every method must contain executable code - no TODO, no placeholders, no comment-only stubs.
        }

        // Export block (REQUIRED - do not omit)
        if (typeof window !== 'undefined') {
          window.BusinessLogic = BusinessLogic;
          window.WebsiteSDK = new BusinessLogic();
        }
        if (typeof module !== 'undefined' && module.exports) {
          module.exports = BusinessLogic;
        }
        ```
        
        Generate COMPLETE, WORKING code in JSON format: {"code": "javascript code here"}
        """
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Generate Implementation",
                prompt,
                additional_args={"website_type": website_type}
            )

        try:
            response, usage = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    "Generate Implementation",
                    success=True,
                    response=response,
                    usage_info=usage,
                    stage="Parallel Generation",
                    call_id=call_id
                )
            
            # Parse JSON response
            if isinstance(response, str):
                parsed_response = json.loads(response)
            else:
                parsed_response = response
            
            # Extract code from response
            if isinstance(parsed_response, dict) and 'code' in parsed_response:
                return parsed_response['code']
            else:
                # If no 'code' field, return the whole response as string
                return json.dumps(parsed_response, indent=2)
                
        except Exception as e:
            import traceback
            if self.logger:
                self.logger.log_error(f"Failed to generate implementation: {str(e)}")
                self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
                # Log failed API response
                self.logger.log_api_response(
                    "Generate Implementation",
                    success=False,
                    error=str(e),
                    stage="Parallel Generation",
                    call_id=call_id
                )
            raise
    
    async def _generate_tests(self, tasks: List[Dict[str, Any]],
                              data_models: Dict[str, Any],
                              interfaces: Dict[str, Any],
                              website_type: str,
                              generated_data: Dict[str, Any]) -> str:
        """Generate flow-based tests"""
        
        # Extract storage key mapping from data models
        storage_key_map = {}
        for entity in data_models.get('entities', []):
            entity_name = entity.get('name')
            storage_key = entity.get('storage_key', entity_name.lower() + 's' if entity_name else '')
            if entity_name:
                storage_key_map[entity_name] = storage_key
        
        # Limit generated data to reduce prompt size and improve efficiency
        limited_generated_data = self._limit_generated_data(generated_data)
        
        # Build prompt with generated data
        prompt = """
        You are an expert test engineer. Generate flow-based integration tests for the business logic.
        
        Website Type: """ + website_type + """
        Tasks: """ + json.dumps(tasks, indent=2) + """
        Data Models: """ + json.dumps(data_models, indent=2) + """
        Storage Key Mapping: """ + json.dumps(storage_key_map, indent=2) + """
        Interfaces: """ + json.dumps(interfaces, indent=2) + """
        
        IMPORTANT: Use the following pre-generated data for INITIAL SETUP ONLY :
        Generated Data: """ + json.dumps(limited_generated_data, indent=2) + """
        
        NOTE: The Generated Data is limited (max 3 items per type). Adapt original tasks to use available data while preserving core functionality being tested.
        
        CRITICAL REQUIREMENTS FOR INTEGRATION TESTING:
        1. Use Generated Data ONLY in setupTestData() for initial localStorage population
        2. NEVER hardcode expected return values - always extract from actual API responses
        3. When testing flows, chain API calls properly:
           - Call API method and capture its FULL response
           - Extract needed values from the response for next calls
           - Use actual returned IDs, not hardcoded ones
        4. Example of CORRECT flow testing:
           ```javascript
           // CORRECT: Using actual API responses
           const addResult = this.logic.addToCart(userId, productId, 2);
           const actualCartId = addResult.cartId;  // Extract from response
           const cartData = this.logic.getCart(actualCartId);  // Use actual ID
           const actualTotal = cartData.total;  // Extract from response
           this.assert(actualTotal > 0, 'Total should be positive');
           
           // WRONG: Hardcoding expected values
           const addResult = this.logic.addToCart(userId, productId, 2);
           const cartData = this.logic.getCart('cart_123');  // Hardcoded!
           this.assert(cartData.total === 49.98, 'Wrong!');  // Hardcoded!
           ```
        5. Test REAL data flow through the system
        6. Verify relationships using actual returned data
        
        REQUIREMENTS:
        1. Test complete user flows, not individual functions
        2. Simulate real user actions sequence
        3. Focus on happy path (successful scenarios)
        4. Use simple assertions (no complex testing framework)
        5. Must run in Node.js environment
        6. Test ALL tasks provided
        7. IMPORTANT: Use ONLY simple CommonJS exports: module.exports = TestRunner;
        8. DO NOT use AMD, UMD, define, or any other module patterns - they cause errors in Node.js
        9. CRITICAL: When accessing localStorage, use the storage_key from the Storage Key Mapping
           For example: If Product entity has storage_key 'products', use localStorage.getItem('products')
           NOT localStorage.getItem('Product')
        10. Call SDK interfaces with positional arguments only (do NOT pass a single object) to keep consistent with usage.

        STRUCTURE (use this exact skeleton, implement ALL test flows with real logic):
        ```javascript
        // Node.js environment - import BusinessLogic from the same directory
        const BusinessLogic = require('./business_logic.js');

        class TestRunner {
          constructor(businessLogic) {
            this.logic = businessLogic || new BusinessLogic();
            this.results = [];
            this.clearStorage();
            this.setupTestData();
          }

          clearStorage() { localStorage.clear(); this.logic._initStorage(); }

          setupTestData() {
            // Populate localStorage with ALL Generated Data using correct storage keys.
            // Every entity type must be written. No placeholders.
          }

          runAllTests() {
            // Call every test method here. One test method per user task.
            return this.results;
          }

          // Implement one test method per task. Each method must:
          // 1. Read initial data from localStorage (populated by setupTestData)
          // 2. Call SDK methods and CAPTURE actual return values
          // 3. Assert using actual returned data - NEVER hardcode expected values
          // 4. Chain calls: extract IDs/values from responses for subsequent calls

          assert(condition, message) { if (!condition) throw new Error('Assertion failed: ' + message); }
          recordSuccess(testName) { this.results.push({test: testName, success: true}); console.log('PASS ' + testName); }
          recordFailure(testName, error) { this.results.push({test: testName, success: false, error: error.message}); console.log('FAIL ' + testName + ': ' + error.message); }
        }

        module.exports = TestRunner;
        ```

        Generate COMPLETE test flows for ALL user tasks in JSON format: {"code": "javascript code here"}
        """
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Generate Tests",
                prompt,
                additional_args={"website_type": website_type}
            )

        try:
            response, usage = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    "Generate Tests",
                    success=True,
                    response=response,
                    usage_info=usage,
                    stage="Parallel Generation",
                    call_id=call_id
                )
            
            # Parse JSON response
            if isinstance(response, str):
                parsed_response = json.loads(response)
            else:
                parsed_response = response
            
            # Extract code from response
            if isinstance(parsed_response, dict) and 'code' in parsed_response:
                return parsed_response['code']
            else:
                # If no 'code' field, return the whole response as string
                return json.dumps(parsed_response, indent=2)
                
        except Exception as e:
            import traceback
            if self.logger:
                self.logger.log_error(f"Failed to generate tests: {str(e)}")
                self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
                # Log failed API response
                self.logger.log_api_response(
                    "Generate Tests",
                    success=False,
                    error=str(e),
                    stage="Parallel Generation",
                    call_id=call_id
                )
            raise
    
    def generate_sync(self, tasks: List[Dict[str, Any]], 
                     data_models: Dict[str, Any],
                     interfaces: Dict[str, Any],
                     website_type: str,
                     generated_data: Dict[str, Any]) -> Tuple[str, str]:
        """
        Synchronous wrapper for parallel generation
        
        Args:
            tasks: User tasks
            data_models: Data models
            interfaces: Interface definitions
            website_type: Type of website
            generated_data: Pre-generated data for test consistency
        
        Returns:
            Tuple of (implementation_code, test_code)
        """
        # Create new event loop for sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(
                self.generate_parallel(tasks, data_models, interfaces, website_type, generated_data)
            )
        finally:
            loop.close()
    
    async def generate_async(self, tasks: List[Dict[str, Any]], 
                           data_models: Dict[str, Any],
                           interfaces: Dict[str, Any],
                           website_type: str,
                           generated_data: Dict[str, Any]) -> Tuple[str, str]:
        """
        Asynchronous parallel generation for use in async contexts
        
        Args:
            tasks: User tasks
            data_models: Data models
            interfaces: Interface definitions
            website_type: Type of website
            generated_data: Pre-generated data for test consistency
        
        Returns:
            Tuple of (implementation_code, test_code)
        """
        return await self.generate_parallel(tasks, data_models, interfaces, website_type, generated_data)
    
    def _limit_generated_data(self, generated_data: Dict[str, Any], max_items_per_type: int = 3) -> Dict[str, Any]:
        """
        Limit generated data to a maximum number of items per data type for LLM efficiency
        
        Args:
            generated_data: Original generated data dictionary
            max_items_per_type: Maximum number of items to keep per data type (default: 3)
            
        Returns:
            Limited data dictionary with the same structure but fewer items
        """
        limited_data = {}
        
        for data_type, data_items in generated_data.items():
            if isinstance(data_items, list):
                # Limit to max_items_per_type for lists
                limited_data[data_type] = data_items[:max_items_per_type]
                
                # Log the limitation for debugging
                if self.logger and len(data_items) > max_items_per_type:
                    self.logger.log_info(f"Limited {data_type} from {len(data_items)} to {max_items_per_type} items for test generation")
            else:
                # Keep non-list items as is
                limited_data[data_type] = data_items
        
        return limited_data