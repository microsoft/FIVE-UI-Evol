"""
TDD Interface Designer
Designs core interfaces based on data models and tasks
"""

import json
from typing import List, Dict, Any
from llm_caller import call_openai_api_json


class TDDInterfaceDesigner:
    """Designs interfaces from data models and tasks for TDD generation"""

    def __init__(self, logger=None, model=None, reasoning_effort=None):
        self.logger = logger
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    def design_interfaces(self, tasks: List[Dict[str, Any]], data_models: Dict[str, Any], 
                          website_type: str, primary_architecture: Any = None) -> Dict[str, Any]:
        """
        Design core step interfaces based on tasks and data models
        
        Args:
            tasks: List of user tasks with steps
            data_models: Extracted data models with entities and relationships
            website_type: Type of website
            primary_architecture: Primary architecture design (optional)
            
        Returns:
            Dictionary containing interface definitions
        """
        # Prepare architecture context if provided
        architecture_context = ""
        if primary_architecture:
            pages_info = []
            if hasattr(primary_architecture, 'pages'):
                pages = primary_architecture.pages
            elif isinstance(primary_architecture, dict):
                pages = primary_architecture.get('pages', [])
            else:
                pages = []
            
            for page in pages:
                page_name = page.get('name', 'Unknown') if isinstance(page, dict) else getattr(page, 'name', 'Unknown')
                page_functions = page.get('primary_functions', []) if isinstance(page, dict) else getattr(page, 'primary_functions', [])
                pages_info.append(f"- {page_name}: {', '.join(page_functions)}")
            
            if pages_info:
                architecture_context = f"""
        
        Website Pages and Functions:
        {chr(10).join(pages_info)}
        """
        
        prompt = f"""
        You are a software architect. Design comprehensive interfaces for both user tasks AND page functionality.
        
        Website Type: {website_type}
        User Tasks: {json.dumps(tasks, indent=2)}
        Data Models: {json.dumps(data_models, indent=2)}
        {architecture_context}
        
        IMPORTANT REQUIREMENTS:
        1. Design USER-FACING interfaces that will be directly called from UI
        2. This is for SINGLE-USER agent training - NO userId, sessionId parameters
        3. System state (cart, session) should be managed internally, not passed as parameters
        
        CRITICAL: Design interfaces for TWO purposes:
        
        A. TASK EXECUTION INTERFACES - For user tasks:
           - What information must be shown BEFORE the user can act (display interfaces)
           - What action the user performs (action interfaces)
           - What feedback/results need to be shown AFTER the action (result interfaces)
        
        B. PAGE FUNCTIONALITY INTERFACES - For each page's primary_functions:
           - Review EVERY primary_function in the Website Pages list above
           - Ensure there's an interface to support EACH function
           - Examples:
             * "Navigate to featured product categories" → needs getCategories()
             * "Display featured products" → needs getFeaturedProducts()
             * "Show product filters" → needs getFilterOptions()
             * "View product specifications" → needs getProductDetails(productId)
        
        4. Interfaces should handle complete operations (e.g., addToCart handles cart creation if needed)
        5. Do NOT create unnecessary CRUD, but DO create interfaces needed for page display
        6. Do not create interfaces that include URL in return values such as getNavigationLinks, as these are handled separately
        7. For interfaces that get data for display, return not only necessary fields, but also user-friendly fields (e.g., include "category_name" instead of only "categoryId")
        8. CRITICAL - Entity Reference Parameters: For parameters that reference another data entity (foreign key pattern):
           - Identify by naming: parameter name like "xxxId" that matches an entity name (e.g., locationId → Location, categoryId → Category, fromLocationId → Location)
           - Add "entityReference" metadata to indicate this parameter should use a selector UI (not plain text input):
             {{"entity": "EntityName", "displayField": "displayName or name", "valueField": "id"}}
           - This tells the UI to render a dropdown/autocomplete showing user-friendly names, not expect users to type internal IDs
           - Examples:
             * fromLocationId, toLocationId → entityReference: {{entity: "Location", displayField: "displayName", valueField: "id"}}
             * categoryId → entityReference: {{entity: "Category", displayField: "name", valueField: "id"}}
           - Do NOT add entityReference for parameters that come from URL (already selected on previous page)
        9. CRITICAL - Array Return Types Must Specify Items:
           - For any return type with "type": "array", ALWAYS include "items" to specify element type
           - If the array contains objects from a data model, use: "items": "EntityName"
           - If the array contains simple values, explicitly define the structure with object format
           - NEVER leave array types without items specification
           - Examples:
             * Correct: {{"type": "array", "items": "Product"}}
             * Correct: {{"type": "array", "items": {{"type": "object", "properties": {{"id": {{"type": "string"}}, "name": {{"type": "string"}}}}}}}}
             * WRONG: {{"type": "array", "description": "list of categories"}} - missing items!
        10. CRITICAL - Object Parameters Must Specify Properties:
           - For any parameter with "type": "object", ALWAYS include "properties" to define its exact key-value structure
           - This ensures the SDK implementation and UI code agree on the same object shape
           - NEVER leave object parameters with only a description and no properties
           - If the object keys come from another interface's output (e.g., filter IDs from getFilterOptions), explicitly define the value format
           - Examples:
             * Correct: {{"name": "filters", "type": "object", "properties": {{"categoryId": {{"type": "string"}}, "minPrice": {{"type": "number"}}, "maxPrice": {{"type": "number"}}}}}}
             * Correct: {{"name": "options", "type": "object", "properties": {{"color": {{"type": "string"}}, "size": {{"type": "string"}}}}}}
             * WRONG: {{"name": "filters", "type": "object", "description": "filter parameters"}} - missing properties!
        11. Enum Value Naming Convention:
           - When listing example values for string parameters in descriptions, use lowercase_snake_case
           - Example: "e.g., 'code_sample', 'request_example'" (NOT "code-sample", "Code Sample")
           - This applies to status, type, category, mode, context, and similar parameters
        12. Do NOT Design Interfaces for Page Chrome Content:
           - Page chrome = decorative text/images that do NOT reference any entity in Data Models and are NOT related to any user task
           - Examples of page chrome (no interface needed): hero banner title like "Welcome to Our Store", site tagline, about-us paragraph, footer copyright text, decorative background images
           - Examples that ARE business data (interface needed): featured products, category lists, team member profiles, testimonials, store locations, pricing tables, event schedules — even if displayed statically, these reference Data Model entities
           - If content references or displays instances of a Data Model entity, it MUST go through an SDK interface
           - If content is generic text/images that could be written by the page generator without any data, it should be inlined in HTML
        13. CRITICAL - Configuration Interfaces Must Include Concrete Values:
           - For interfaces returning display/config metadata (e.g., *TableConfig, *FilterOptions, *SortOptions),
             include concrete selectable values so SDK and HTML cannot guess different keys.
           - For fields with a fixed set of allowed string values, use "type": "enum" with a "values" list
             (same format as data models). Do NOT use "type": "string" with a separate "enumValues" property.
           - For table config interfaces: always list explicit column keys in availableColumns with exact key and label values
           - For filter/sort option interfaces: always list explicit option values using "type": "enum", "values": [...]
           - For scalar defaults, include "defaultValue" in the property schema
           - Do NOT leave configurable keys as free-form strings without explicit allowed values
           - Example: a table config should specify {{"key": "name", "label": "Name"}}, {{"key": "price", "label": "Price"}} — not just "returns column config"

        Example task interfaces:
        - getProductDetails(productId) - show product info
        - addToCart(productId, quantity) - add to cart
        - getCartItems() - show cart contents
        
        Example page functionality interfaces:
        - getFeaturedProducts() - for homepage featured section
        - getCategories() - for navigation menu
        - getFilterOptions(category) - for product listing filters
        - searchProducts(query, filters) - for search functionality
        
        Return JSON in this format:
        {{
            "interfaces": [
                {{
                    "name": "addToCart",
                    "description": "Add a product to cart (cart managed internally)",
                    "parameters": [
                        {{"name": "productId", "type": "string", "required": true}},
                        {{"name": "quantity", "type": "number", "required": true, "default": 1}}
                    ],
                    "returns": {{
                        "type": "object",
                        "properties": {{
                            "success": {{"type": "boolean"}},
                            "cartId": {{"type": "string"}},
                            "message": {{"type": "string"}}
                        }}
                    }},
                    "relatedTasks": ["task_1", "task_2"]
                }},
                {{
                    "name": "searchFlights",
                    "description": "Search available flights",
                    "parameters": [
                        {{"name": "fromLocationId", "type": "string", "required": true, "entityReference": {{"entity": "Location", "displayField": "displayName", "valueField": "id"}}}},
                        {{"name": "toLocationId", "type": "string", "required": true, "entityReference": {{"entity": "Location", "displayField": "displayName", "valueField": "id"}}}},
                        {{"name": "departureDate", "type": "string", "required": true}}
                    ],
                    "returns": {{"type": "array", "items": "Flight"}},
                    "relatedTasks": ["task_1"]
                }},
                {{
                    "name": "getProductTableConfig",
                    "description": "Get table configuration for product listing",
                    "parameters": [],
                    "returns": {{
                        "type": "object",
                        "properties": {{
                            "availableColumns": {{
                                "type": "array",
                                "items": {{
                                    "type": "object",
                                    "properties": {{
                                        "key": {{"type": "enum", "values": ["name", "price", "category", "stock"]}},
                                        "label": {{"type": "string"}}
                                    }}
                                }}
                            }},
                            "defaultColumns": {{
                                "type": "array",
                                "items": {{"type": "enum", "values": ["name", "price"]}},
                                "defaultValue": ["name", "price"]
                            }},
                            "sortableColumns": {{
                                "type": "array",
                                "items": {{"type": "enum", "values": ["name", "price", "stock"]}}
                            }}
                        }}
                    }},
                    "relatedTasks": []
                }}
            ],
            "helperFunctions": [
                {{
                    "name": "_getOrCreateCart",
                    "description": "Internal helper to get or create cart from localStorage",
                    "visibility": "private"
                }}
            ]
        }}
        """
        
        if self.logger:
            self.logger.log_info("Designing interfaces from tasks and data models...")
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Design Interfaces",
                prompt
            )

        try:
            response, usage = call_openai_api_json(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log API response
            if self.logger:
                self.logger.log_api_response(
                    "Design Interfaces",
                    success=True,
                    response=response,
                    usage_info=usage,
                    call_id=call_id
                )
            
            # Parse JSON response
            if isinstance(response, str):
                interfaces = json.loads(response)
            else:
                interfaces = response
            
            if self.logger:
                core_count = len(interfaces.get('interfaces', []))
                helper_count = len(interfaces.get('helperFunctions', []))
                self.logger.log_info(f"Designed {core_count} core interfaces and {helper_count} helper functions")
            
            return interfaces
            
        except Exception as e:
            import traceback
            if self.logger:
                self.logger.log_error(f"Failed to design interfaces: {str(e)}")
                self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
                # Log failed API response
                self.logger.log_api_response(
                    "Design Interfaces",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            raise
    
    def generate_interface_contract(self, interfaces: Dict[str, Any]) -> str:
        """
        Generate TypeScript-style interface contract for documentation
        
        Args:
            interfaces: Designed interfaces
            
        Returns:
            TypeScript interface definitions as string
        """
        contract = []
        contract.append("// Core Business Logic Interfaces")
        contract.append("interface BusinessLogic {")
        
        # Core interfaces
        for interface in interfaces.get('interfaces', []):
            params = []
            for param in interface['parameters']:
                param_type = self._ts_type(param['type'])
                required = "" if param.get('required', True) else "?"
                params.append(f"{param['name']}{required}: {param_type}")
            
            return_type = self._format_return_type(interface['returns'])
            contract.append(f"  // {interface['description']}")
            contract.append(f"  {interface['name']}({', '.join(params)}): {return_type};")
            contract.append("")
        
        # Helper functions
        if interfaces.get('helperFunctions'):
            contract.append("  // Helper Functions (internal use)")
            for helper in interfaces['helperFunctions']:
                contract.append(f"  private {helper['name']}(...args: any[]): any;")
        
        contract.append("}")
        
        return "\n".join(contract)
    
    def _ts_type(self, type_str: str) -> str:
        """Convert type string to TypeScript type"""
        type_map = {
            "string": "string",
            "number": "number",
            "boolean": "boolean",
            "datetime": "Date",
            "array": "any[]",
            "object": "any",
            "enum": "string"
        }
        return type_map.get(type_str, "any")
    
    def _format_return_type(self, returns) -> str:
        """Format return type for TypeScript"""
        if not returns:
            return "void"

        if isinstance(returns, str):
            return self._ts_type(returns)

        if returns.get('type') == 'object' and 'properties' in returns:
            props = []
            for prop, details in returns['properties'].items():
                # Handle both string type and dict with 'type' key
                if isinstance(details, str):
                    prop_type = self._ts_type(details)
                elif isinstance(details, dict):
                    prop_type = self._ts_type(details.get('type', 'any'))
                else:
                    prop_type = 'any'
                props.append(f"{prop}: {prop_type}")
            # Use string concatenation instead of f-string to avoid brace issues
            return "{" + ", ".join(props) + "}"
        
        return self._ts_type(returns.get('type', 'any'))

    def lint_interfaces(self, interfaces: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deterministic lint check on designed interfaces.
        Fails on critical issues, warns on non-critical ones.

        Args:
            interfaces: Designed interfaces

        Returns:
            Dict with 'passed', 'errors', 'warnings' keys
        """
        errors = []
        warnings = []

        for iface in interfaces.get('interfaces', []):
            name = iface.get('name', '<unnamed>')

            # Check 1: object parameters must have properties; enum parameters must have values
            for param in iface.get('parameters', []):
                param_type = param.get('type', '')
                if param_type == 'object' and 'properties' not in param:
                    errors.append(
                        f"[{name}] parameter '{param.get('name', '?')}' has type 'object' but missing 'properties'"
                    )
                if param_type == 'enum' and 'values' not in param:
                    errors.append(
                        f"[{name}] parameter '{param.get('name', '?')}' has type 'enum' but missing 'values'"
                    )

            # Check 2: TableConfig interfaces must have concrete column definitions
            if 'TableConfig' in name or 'tableConfig' in name:
                returns = iface.get('returns', {})
                props = returns.get('properties', {})
                available_cols = props.get('availableColumns', {})
                if not available_cols:
                    errors.append(
                        f"[{name}] is a TableConfig interface but returns no 'availableColumns' property"
                    )
                else:
                    # Check that items have enumValues or concrete key definitions
                    items = available_cols.get('items', {})
                    if isinstance(items, dict):
                        item_props = items.get('properties', {})
                        key_prop = item_props.get('key', {})
                        if isinstance(key_prop, dict) and 'enumValues' not in key_prop and 'values' not in key_prop:
                            warnings.append(
                                f"[{name}] availableColumns.items.key has no 'values'/'enumValues' — column keys may diverge between SDK and HTML"
                            )

            # Check 3: array return types must have items
            returns = iface.get('returns', {})
            if isinstance(returns, dict) and returns.get('type') == 'array' and 'items' not in returns:
                errors.append(
                    f"[{name}] returns type 'array' but missing 'items' specification"
                )

            # Check 4: FilterOptions/SortOptions should have concrete values
            if any(kw in name for kw in ['FilterOptions', 'filterOptions', 'SortOptions', 'sortOptions']):
                returns = iface.get('returns', {})
                if isinstance(returns, dict) and returns.get('type') == 'object' and 'properties' not in returns:
                    warnings.append(
                        f"[{name}] is a config interface but returns no 'properties' — filter/sort keys may diverge"
                    )

        passed = len(errors) == 0
        result = {'passed': passed, 'errors': errors, 'warnings': warnings}

        if self.logger:
            if errors:
                self.logger.log_error(f"Interface lint FAILED with {len(errors)} error(s):")
                for e in errors:
                    self.logger.log_error(f"  ERROR: {e}")
            if warnings:
                for w in warnings:
                    self.logger.log_info(f"  WARN: {w}")
            if passed:
                self.logger.log_info(f"Interface lint passed ({len(warnings)} warning(s))")

        return result

    def design_missing_interfaces(self, missing_interfaces: Dict[str, List[Dict[str, str]]], 
                                   tasks: List[Dict[str, Any]], 
                                   data_models: Dict[str, Any],
                                   existing_interfaces: Dict[str, Any],
                                   website_type: str) -> Dict[str, Any]:
        """
        Design interfaces based on missing interface requirements from architecture
        
        Args:
            missing_interfaces: Dictionary mapping page names to missing interfaces
            tasks: User tasks
            data_models: Data models
            existing_interfaces: Already designed interfaces
            website_type: Type of website
            
        Returns:
            Dictionary containing newly designed interfaces
        """
        # Prepare the list of missing interfaces
        missing_list = []
        for page_name, interfaces in missing_interfaces.items():
            for interface in interfaces:
                missing_list.append({
                    "page": page_name,
                    "name": interface["name"],
                    "reason": interface["reason"]
                })
        
        # Prepare existing interfaces summary
        existing_names = [i["name"] for i in existing_interfaces.get("interfaces", [])]
        
        prompt = f"""
        You are a software architect. Design the missing interfaces that were identified during architecture review.
        
        Website Type: {website_type}
        
        Missing Interfaces Needed:
        {json.dumps(missing_list, indent=2)}
        
        Existing Interfaces (already designed):
        {json.dumps(existing_names, indent=2)}
        
        Data Models Available:
        {json.dumps(data_models, indent=2)}
        
        User Tasks:
        {json.dumps(tasks, indent=2)}
        
        REQUIREMENTS:
        1. Design ONLY the missing interfaces listed above
        2. Each interface should fulfill the specific reason provided
        3. Follow the same pattern as existing interfaces
        4. Focus on data retrieval and display operations
        5. Keep interfaces simple and focused on their specific purpose
        
        Common patterns for missing interfaces:
        - getFeaturedProducts(): Return a curated list of products for homepage
        - getCategories(): Return all available categories for navigation
        - getCategoryProducts(categoryId): Return products in a specific category
        - updateCartQuantity(cartItemId, quantity): Update quantity of item in cart
        
        Return JSON in this format:
        {{
            "interfaces": [
                {{
                    "name": "getFeaturedProducts",
                    "description": "Get featured products for homepage display",
                    "parameters": [],
                    "returns": {{
                        "type": "object",
                        "properties": {{
                            "products": {{"type": "array"}},
                            "totalCount": {{"type": "number"}}
                        }}
                    }},
                    "sideEffects": [],
                    "relatedTasks": []
                }}
            ]
        }}
        """
        
        if self.logger:
            self.logger.log_info(f"Designing {len(missing_list)} missing interfaces...")
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Design Missing Interfaces",
                prompt,
                additional_args={"missing_count": len(missing_list)}
            )

        try:
            response, usage = call_openai_api_json(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log API response
            if self.logger:
                self.logger.log_api_response(
                    "Design Missing Interfaces",
                    success=True,
                    response=response,
                    usage_info=usage,
                    call_id=call_id
                )
            
            # Parse JSON response
            if isinstance(response, str):
                new_interfaces = json.loads(response)
            else:
                new_interfaces = response
            
            if self.logger:
                count = len(new_interfaces.get('interfaces', []))
                self.logger.log_info(f"Designed {count} missing interfaces")
            
            return new_interfaces
            
        except Exception as e:
            import traceback
            if self.logger:
                self.logger.log_error(f"Failed to design missing interfaces: {str(e)}")
                self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
                # Log failed API response
                self.logger.log_api_response(
                    "Design Missing Interfaces",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            raise
    
    def validate_interfaces(self, interfaces: Dict[str, Any], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate that interfaces cover all task requirements
        
        Args:
            interfaces: Designed interfaces
            tasks: Original user tasks
            
        Returns:
            Validation result with coverage analysis
        """
        validation = {
            "valid": True,
            "coverage": {},
            "missing": [],
            "warnings": []
        }
        
        # Check if each task has related interfaces
        task_ids = [task.get('id', f"task_{i}") for i, task in enumerate(tasks)]
        covered_tasks = set()
        
        for interface in interfaces.get('interfaces', []):
            for task_id in interface.get('relatedTasks', []):
                covered_tasks.add(task_id)
        
        # Find uncovered tasks
        uncovered = set(task_ids) - covered_tasks
        if uncovered:
            validation['valid'] = False
            validation['missing'] = list(uncovered)
            validation['warnings'].append(f"Tasks not covered by interfaces: {', '.join(uncovered)}")
        
        # Calculate coverage
        validation['coverage'] = {
            "total_tasks": len(task_ids),
            "covered_tasks": len(covered_tasks),
            "coverage_percentage": (len(covered_tasks) / len(task_ids) * 100) if task_ids else 0
        }
        
        return validation