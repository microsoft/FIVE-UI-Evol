"""
TDD Test Validator
Validates implementation by running tests and auto-fixes failures
"""

import os
import json
import subprocess
import tempfile
from typing import Dict, Any, List, Tuple
from llm_caller import call_openai_api_json_async


INCREMENTAL_FIX_PROMPT = """Fix the following JavaScript implementation errors using search-replace patches.

Test Failures:
{failures_json}

Current Implementation (with line numbers for reference):
```javascript
{numbered_implementation}
```

Test Code (for reference, do NOT modify):
```javascript
{tests}
```

Return ONLY the patches needed to fix errors in JSON format:
{{
  "replacements": [
    {{
      "old": "exact string to find (include enough context to be unique)",
      "new": "replacement string with fix applied"
    }}
  ]
}}

Rules:
1. Each "old" must be an EXACT substring from the implementation (WITHOUT line numbers)
2. Include enough surrounding context to make "old" unique in the file
3. Keep patches minimal - only change what's needed to fix the test failure
4. If multiple errors are in the same area, combine into one patch
5. Do NOT change the interface signatures
6. Ensure the code remains Node.js compatible
"""


class TDDTestValidator:
    """Validates and fixes implementation using test results"""

    def __init__(self, logger=None, max_fix_iterations=3,
                 model=None, reasoning_effort="medium"):
        self.logger = logger
        self.max_fix_iterations = max_fix_iterations
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def validate_and_fix(self, implementation: str, tests: str, generated_data: Dict[str, Any] = None) -> Tuple[str, Dict[str, Any]]:
        """
        Validate implementation by running tests and fix failures
        
        Args:
            implementation: Business logic implementation code
            tests: Test runner code
            generated_data: Pre-generated data to use in tests
            
        Returns:
            Tuple of (fixed_implementation, test_results)
        """
        if self.logger:
            self.logger.start_stage("Validate and Fix", "backend")
        
        iteration = 0
        current_implementation = implementation
        
        while iteration < self.max_fix_iterations:
            iteration += 1
            
            if self.logger:
                self.logger.log_info(f"Validation iteration {iteration}/{self.max_fix_iterations}")
            
            # Run tests with generated data
            test_results = self._run_tests(current_implementation, tests, generated_data)
            
            # Debug logging
            if self.logger:
                self.logger.log_info(f"Test results: {json.dumps(test_results, indent=2)}")
            
            # Check if all tests pass
            if self._all_tests_pass(test_results):
                if self.logger:
                    self.logger.log_info(f"✅ All tests passed on iteration {iteration}")
                    self.logger.end_stage("Validate and Fix")
                return current_implementation, test_results
            
            # Fix failures
            if self.logger:
                failed_count = len([r for r in test_results.get('details', []) if not r.get('success', False)])
                self.logger.log_info(f"Fixing {failed_count} failed tests...")
            
            current_implementation = await self._fix_implementation(
                current_implementation, 
                tests,
                test_results,
                iteration
            )
        
        # Max iterations reached
        if self.logger:
            self.logger.log_warning(f"Max iterations ({self.max_fix_iterations}) reached. Some tests may still be failing.")
            self.logger.end_stage("Validate and Fix")
        
        return current_implementation, test_results
    
    def _run_tests(self, implementation: str, tests: str, generated_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Run tests in Node.js environment
        
        Args:
            implementation: Business logic code
            tests: Test runner code
            generated_data: Pre-generated data to inject into tests
            
        Returns:
            Test results dictionary
        """
        # Create temporary directory for test files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write implementation file
            impl_path = os.path.join(tmpdir, "business_logic.js")
            with open(impl_path, 'w', encoding='utf-8') as f:
                f.write(implementation)
            
            # Write test file
            test_path = os.path.join(tmpdir, "test_runner.js")
            with open(test_path, 'w', encoding='utf-8') as f:
                f.write(tests)
            
            # Create package.json in temp directory
            package_json = {
                "name": "tdd-test",
                "version": "1.0.0",
                "dependencies": {
                    "node-localstorage": "^2.2.1"
                }
            }
            package_path = os.path.join(tmpdir, "package.json")
            with open(package_path, 'w', encoding='utf-8') as f:
                json.dump(package_json, f, indent=2)
            
            # Install dependencies in temp directory
            # On Windows, use npm.cmd instead of npm
            npm_cmd = "npm.cmd" if os.name == 'nt' else "npm"
            
            # if on Windows, Need shell=True
            if os.name == 'nt':
                install_result = subprocess.run(
                    [npm_cmd, "install", "--silent"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=60,  # Fixed timeout for npm install
                    shell=True  # Need shell=True on Windows
                )
                if self.logger and install_result.returncode != 0:
                    self.logger.log_warning(f"npm install warning: {install_result.stderr}")
                    
            else: # Unix-like systems
                install_result = subprocess.run(
                    [npm_cmd, "install", "--silent", "--no-audit", "--no-fund"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=180
                )

                if install_result.returncode != 0:
                    if self.logger:
                        self.logger.log_error("npm install failed")
                        self.logger.log_error(f"STDERR: {install_result.stderr.strip()}")
                        self.logger.log_error(f"STDOUT: {install_result.stdout.strip()}")
                    return {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": f"Dependency install failed (node-localstorage). Return code {install_result.returncode}",
                        "details": []
                    }

                dep_path = os.path.join(tmpdir, "node_modules", "node-localstorage")
                if not os.path.isdir(dep_path):
                    if self.logger:
                        self.logger.log_error(f"Dependency directory missing: {dep_path}")
                    return {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": "node-localstorage not found after npm install",
                        "details": []
                    }

            executor_code = """
            // Setup localStorage mock for Node.js environment
            // Require node-localstorage (installed locally in temp dir)
            const { LocalStorage } = require('node-localstorage');
            global.localStorage = new LocalStorage('./test-storage');  // Fixed storage directory
            
            // Clear any previous test data
            localStorage.clear();
            
            const BusinessLogic = require('./business_logic.js');
            const TestRunner = require('./test_runner.js');
            
            // Run tests
            const logic = new BusinessLogic();
            const runner = new TestRunner(logic);
            const results = runner.runAllTests();
            
            // Output results as JSON
            console.log(JSON.stringify({
                total: results.length,
                passed: results.filter(r => r.success).length,
                failed: results.filter(r => !r.success).length,
                details: results
            }, null, 2));
            
            // Clean up localStorage after tests
            localStorage.clear();
            """
            
            executor_path = os.path.join(tmpdir, "executor.js")
            with open(executor_path, 'w', encoding='utf-8') as f:
                f.write(executor_code)
            
            # Run tests
            try:
                result = subprocess.run(
                    ["node", executor_path],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    timeout=30  # Fixed timeout for node execution
                )
                
                if result.returncode != 0:
                    # Node.js error
                    if self.logger:
                        self.logger.log_error(f"Node.js execution failed with return code {result.returncode}")
                        self.logger.log_error(f"STDERR: {result.stderr}")
                        self.logger.log_error(f"STDOUT: {result.stdout}")
                    return {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": f"Node.js error: {result.stderr}",
                        "stdout": result.stdout,
                        "details": []
                    }
                
                # Parse JSON output
                try:
                    parsed_result = json.loads(result.stdout)
                    if self.logger:
                        self.logger.log_info(f"Successfully parsed test output: {json.dumps(parsed_result, indent=2)}")
                    return parsed_result
                except json.JSONDecodeError:
                    if self.logger:
                        self.logger.log_warning(f"Failed to parse JSON directly, raw output: {result.stdout}")
                    
                    # Try to extract JSON from output
                    lines = result.stdout.split('\n')
                    for i in range(len(lines)):
                        if lines[i].strip().startswith('{'):
                            # Found start of JSON
                            json_str = '\n'.join(lines[i:])
                            try:
                                parsed_result = json.loads(json_str)
                                if self.logger:
                                    self.logger.log_info(f"Extracted JSON from output: {json.dumps(parsed_result, indent=2)}")
                                return parsed_result
                            except:
                                pass
                    
                    if self.logger:
                        self.logger.log_error(f"Could not extract valid JSON from output")
                    
                    return {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": "Could not parse test output",
                        "stdout": result.stdout,
                        "details": []
                    }
                    
            except subprocess.TimeoutExpired:
                return {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "error": "Test execution timeout",
                    "details": []
                }
            except Exception as e:
                return {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "error": str(e),
                    "details": []
                }
    
    def _all_tests_pass(self, test_results: Dict[str, Any]) -> bool:
        """Check if all tests pass"""
        if 'error' in test_results:
            if self.logger:
                self.logger.log_warning(f"Test has error: {test_results['error']}")
            return False
        
        total = test_results.get('total', 0)
        failed = test_results.get('failed', 0)
        passed = test_results.get('passed', 0)
        
        if self.logger:
            self.logger.log_info(f"Test summary: total={total}, passed={passed}, failed={failed}")
        
        if total == 0:
            if self.logger:
                self.logger.log_warning("No tests were executed (total=0)")
            return False
        
        if failed > 0:
            return False
        
        # Check detailed results
        for detail in test_results.get('details', []):
            if not detail.get('success', False):
                return False
        
        return True

    def _apply_replacements(self, content: str, replacements: List[Dict]) -> Tuple[str, int, int]:
        """
        Apply search-replace patches to content.

        Args:
            content: Original implementation code
            replacements: List of {old, new} replacement dictionaries

        Returns:
            Tuple[str, int, int]: (modified_content, successful_count, failed_count)
        """
        modified = content
        success = 0
        failed = 0

        for r in replacements:
            old = r.get("old", "")
            new = r.get("new", "")

            if not old:
                failed += 1
                continue

            if old in modified:
                modified = modified.replace(old, new, 1)  # Replace only first occurrence
                success += 1
            else:
                failed += 1
                if self.logger:
                    preview = old[:80].replace('\n', '\\n')
                    self.logger.log_warning(f"  Patch failed: could not find '{preview}...'")

        return modified, success, failed

    async def _fix_implementation(self, implementation: str, tests: str,
                                 test_results: Dict[str, Any], iteration: int) -> str:
        """
        Fix implementation based on test failures using incremental patches

        Args:
            implementation: Current implementation
            tests: Test code
            test_results: Test execution results
            iteration: Current iteration number

        Returns:
            Fixed implementation
        """
        # Collect failure information
        failures = []
        for detail in test_results.get('details', []):
            if not detail.get('success', False):
                failures.append({
                    "test": detail.get('test', 'Unknown'),
                    "error": detail.get('error', 'Test failed')
                })

        # Add general error if present
        if 'error' in test_results:
            failures.insert(0, {
                "test": "Execution",
                "error": test_results['error']
            })

        # Add line numbers to implementation for LLM reference
        numbered_lines = []
        for i, line in enumerate(implementation.split('\n'), 1):
            numbered_lines.append(f"{i:4d}| {line}")
        numbered_implementation = '\n'.join(numbered_lines)

        # Use incremental fix prompt
        prompt = INCREMENTAL_FIX_PROMPT.format(
            failures_json=json.dumps(failures, indent=2),
            numbered_implementation=numbered_implementation,
            tests=tests
        )

        # Log API call
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Fix Implementation (Incremental)",
                prompt,
                additional_args={"iteration": iteration},
                stage="Validate and Fix"
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
                    "Fix Implementation (Incremental)",
                    success=True,
                    response=response,
                    usage_info=usage,
                    stage="Validate and Fix",
                    call_id=call_id
                )

            # Parse JSON response
            if isinstance(response, str):
                parsed_response = json.loads(response)
            else:
                parsed_response = response

            # Extract and apply replacements
            replacements = parsed_response.get("replacements", [])

            if not replacements:
                if self.logger:
                    self.logger.log_warning("No replacements returned by LLM")
                return implementation

            # Apply replacements
            modified, success, failed = self._apply_replacements(implementation, replacements)

            if self.logger:
                self.logger.log_info(f"Patches: {success} applied, {failed} failed")

            # Return modified content only if at least one patch succeeded
            return modified if success > 0 else implementation

        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to fix implementation: {str(e)}")
                self.logger.log_api_response(
                    "Fix Implementation (Incremental)",
                    success=False,
                    error=str(e),
                    stage="Validate and Fix",
                    call_id=call_id
                )
            # Return original implementation if fix fails
            return implementation
    
    def _make_browser_compatible(self, implementation: str) -> str:
        """
        Make the implementation compatible with browser environment
        by replacing module.exports with browser-friendly code
        
        Args:
            implementation: Original implementation code with module.exports
            
        Returns:
            Browser-compatible implementation code
        """
        # Replace module.exports with browser-compatible code
        if "module.exports" in implementation:
            # Find the class name being exported
            lines = implementation.split('\n')
            class_name = None
            
            for line in lines:
                if "module.exports" in line:
                    # Extract the class name from module.exports = ClassName
                    parts = line.split('=')
                    if len(parts) > 1:
                        class_name = parts[1].strip().rstrip(';')
                    break
            
            if class_name:
                # Replace module.exports with browser/Node.js compatible code
                browser_export = f"""
// For browser environment
if (typeof window !== 'undefined') {{
  window.{class_name} = {class_name};
  window.WebsiteSDK = new {class_name}();
}}

// For Node.js environment (testing)
if (typeof module !== 'undefined' && module.exports) {{
  module.exports = {class_name};
}}"""
                
                # Replace the simple module.exports line
                implementation = implementation.replace(f"module.exports = {class_name};", browser_export)
                
                if self.logger:
                    self.logger.log_info(f"Made implementation browser-compatible for class: {class_name}")
        
        return implementation
    
    def save_results(self, implementation: str, tests: str, 
                    test_results: Dict[str, Any], output_dir: str):
        """
        Save final implementation, tests, and results
        
        Args:
            implementation: Final implementation code
            tests: Test code
            test_results: Test execution results
            output_dir: Directory to save files
        """
        os.makedirs(output_dir, exist_ok=True)

        # Save implementation - skip if already exists (instrumentation stage may have written it)
        impl_path = os.path.join(output_dir, "business_logic.js")
        if not os.path.exists(impl_path):
            # File doesn't exist, write the implementation
            browser_compatible_impl = self._make_browser_compatible(implementation)
            with open(impl_path, 'w', encoding='utf-8') as f:
                f.write(browser_compatible_impl)
        else:
            # File exists (likely from instrumentation stage), ensure browser compatibility
            with open(impl_path, 'r', encoding='utf-8') as f:
                existing_impl = f.read()

            # Check if browser compatibility code already exists
            if "window.WebsiteSDK" not in existing_impl:
                browser_compatible_impl = self._make_browser_compatible(existing_impl)
                with open(impl_path, 'w', encoding='utf-8') as f:
                    f.write(browser_compatible_impl)
                if self.logger:
                    self.logger.log_info("Added browser compatibility to existing business_logic.js")
            else:
                if self.logger:
                    self.logger.log_info("Preserved existing business_logic.js (instrumented version)")
        
        # Save tests
        test_path = os.path.join(output_dir, "test_flows.js")
        with open(test_path, 'w', encoding='utf-8') as f:
            f.write(tests)
        
        # Save test results
        results_path = os.path.join(output_dir, "test_results.json")
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump(test_results, f, indent=2)
        
        # Create runner script
        runner_script = """
// Test runner script
// Setup localStorage mock for Node.js environment
// Require node-localstorage (must be installed via npm install)
const { LocalStorage } = require('node-localstorage');
global.localStorage = new LocalStorage('./test-storage');

// Clear any previous test data
localStorage.clear();

const BusinessLogic = require('./business_logic.js');
const TestRunner = require('./test_flows.js');

console.log('Running TDD-generated tests...');
console.log('================================\\n');

const logic = new BusinessLogic();
const runner = new TestRunner(logic);
const results = runner.runAllTests();

console.log('\\n================================');
console.log(`Total: ${results.length}`);
console.log(`Passed: ${results.filter(r => r.success).length}`);
console.log(`Failed: ${results.filter(r => !r.success).length}`);

// Clean up localStorage after tests
localStorage.clear();

if (results.every(r => r.success)) {
    console.log('\\n✅ All tests passed!');
    process.exit(0);
} else {
    console.log('\\n❌ Some tests failed');
    process.exit(1);
}
"""
        
        runner_path = os.path.join(output_dir, "run_tests.js")
        with open(runner_path, 'w', encoding='utf-8') as f:
            f.write(runner_script)
        
        if self.logger:
            self.logger.log_info(f"Saved results to {output_dir}")
            self.logger.log_info(f"  - Implementation: {impl_path}")
            self.logger.log_info(f"  - Tests: {test_path}")
            self.logger.log_info(f"  - Results: {results_path}")
            self.logger.log_info(f"  - Runner: {runner_path}")
            self.logger.log_info(f"\nTo run tests:")
            self.logger.log_info(f"  cd {output_dir}")
            self.logger.log_info(f"  node run_tests.js")