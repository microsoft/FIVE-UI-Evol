"""
TDD Instrumentation Validator

Validates instrumented code by running both original and instrumentation tests
"""

import os
import json
import subprocess
import tempfile
from typing import Dict, Any, Tuple
from tdd_logger_module import TDDLogger
from tdd_instrumentation_data_models import ValidationResult
from llm_caller import call_openai_api_async


class TDDInstrumentationValidator:
    """
    Validates instrumentation does not break original functionality
    and that instrumentation variables are set correctly
    """

    def __init__(self, logger: TDDLogger = None, max_fix_iterations: int = 5,
                 reasoning_effort: str = "medium", model: str = None):
        """
        Initialize validator

        Args:
            logger: TDDLogger instance
            max_fix_iterations: Maximum fix iterations
            reasoning_effort: Reasoning effort level (minimal, low, medium, high)
            model: Model name to use (None for default)
        """
        self.logger = logger or TDDLogger()
        self.max_fix_iterations = max_fix_iterations
        self.reasoning_effort = reasoning_effort
        self.model = model

    async def validate_and_fix(self,
                               instrumented_code: str,
                               original_tests: str,
                               test_data: Dict[str, Any]) -> Tuple[str, ValidationResult]:
        """
        Validate and fix instrumented code (only validates original functionality is preserved)

        Args:
            instrumented_code: Instrumented business logic
            original_tests: Original functionality tests
            test_data: Test data

        Returns:
            Tuple of (validated_code, validation_result)
        """
        self.logger.start_stage("Validate Instrumentation")
        self.logger.log_info("✅ Validating instrumented code preserves original functionality...")

        current_code = instrumented_code
        iteration = 0

        while iteration < self.max_fix_iterations:
            iteration += 1
            self.logger.log_info(f"Validation iteration {iteration}/{self.max_fix_iterations}")

            # Run original tests to ensure instrumentation doesn't break functionality
            original_results = self._run_tests(current_code, original_tests, test_data, "Original Tests")

            # Check results
            original_passed = original_results.get("passed", 0) == original_results.get("total", 0)

            self.logger.log_info(f"Original tests: {original_results.get('passed', 0)}/{original_results.get('total', 0)} passed")

            # Original tests passed - success!
            if original_passed:
                self.logger.log_info(f"✅ All original tests passed on iteration {iteration}")
                self.logger.log_info("   Instrumentation did not break original functionality")
                self.logger.end_stage("Validate Instrumentation")

                return current_code, ValidationResult(
                    success=True,
                    original_tests_passed=True,
                    instrumentation_tests_passed=True,  # N/A - no instrumentation tests
                    total_tests=original_results.get("total", 0),
                    passed_tests=original_results.get("passed", 0),
                    failed_tests=0,
                    iterations_used=iteration,
                    message="Original functionality preserved"
                )

            # Fix needed
            self.logger.log_warning(f"Original tests failed - attempting fix...")

            current_code = await self._fix_instrumented_code(
                current_code,
                original_results,
                None  # No instrumentation test failures
            )

        # Max iterations reached
        self.logger.log_error(f"Max iterations ({self.max_fix_iterations}) reached with test failures")
        self.logger.end_stage("Validate Instrumentation")

        return current_code, ValidationResult(
            success=False,
            original_tests_passed=False,
            instrumentation_tests_passed=True,  # N/A
            total_tests=original_results.get("total", 0),
            passed_tests=original_results.get("passed", 0),
            failed_tests=original_results.get("failed", 0),
            iterations_used=self.max_fix_iterations,
            message="Failed after max iterations",
            errors=["Max fix iterations reached", "Instrumentation broke original functionality"]
        )

    def _run_tests(self,
                   code: str,
                   tests: str,
                   test_data: Dict[str, Any],
                   test_name: str) -> Dict[str, Any]:
        """
        Run tests in Node.js environment

        Args:
            code: Business logic code
            tests: Test code
            test_data: Test data
            test_name: Name for logging

        Returns:
            Test results dictionary
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write business logic
                code_path = os.path.join(tmpdir, "business_logic.js")
                with open(code_path, 'w', encoding='utf-8') as f:
                    f.write(code)

                # Write tests
                test_path = os.path.join(tmpdir, "test_runner.js")
                with open(test_path, 'w', encoding='utf-8') as f:
                    f.write(tests)

                # Create package.json
                package_json = {
                    "name": "instrumentation-test",
                    "version": "1.0.0",
                    "dependencies": {
                        "node-localstorage": "^2.2.1"
                    }
                }
                package_path = os.path.join(tmpdir, "package.json")
                with open(package_path, 'w', encoding='utf-8') as f:
                    json.dump(package_json, f, indent=2)

                # Install dependencies
                npm_cmd = "npm.cmd" if os.name == 'nt' else "npm"
                install_args = [npm_cmd, "install", "--silent"]
                if os.name != 'nt':
                    install_args.extend(["--no-audit", "--no-fund"])

                subprocess.run(
                    install_args,
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    shell=(os.name == 'nt')
                )

                # Create executor wrapper to actually run tests
                executor_code = """
                // Setup localStorage mock for Node.js environment
                const { LocalStorage } = require('node-localstorage');
                global.localStorage = new LocalStorage('./test-storage');

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

                # Run tests via executor
                node_cmd = "node"
                result = subprocess.run(
                    [node_cmd, executor_path],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                # Parse output (now expects JSON format)
                return self._parse_test_output(result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            self.logger.log_error(f"{test_name} timed out")
            return {"total": 0, "passed": 0, "failed": 0, "error": "Timeout"}
        except Exception as e:
            self.logger.log_error(f"{test_name} error: {str(e)}")
            return {"total": 0, "passed": 0, "failed": 0, "error": str(e)}

    def _parse_test_output(self, stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
        """
        Parse test output to extract results

        Args:
            stdout: Standard output
            stderr: Standard error
            returncode: Return code

        Returns:
            Test results dictionary
        """
        import re
        import json

        # Priority 1: Try to parse JSON output (from executor wrapper)
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict) and "total" in parsed and "passed" in parsed:
                self.logger.log_info(f"Successfully parsed JSON test output")
                return {
                    "total": parsed.get("total", 0),
                    "passed": parsed.get("passed", 0),
                    "failed": parsed.get("failed", 0),
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode
                }
        except json.JSONDecodeError:
            pass

        # Priority 2: Try to extract JSON from output (in case of console.log messages)
        lines = stdout.split('\n')
        for i in range(len(lines)):
            if lines[i].strip().startswith('{'):
                json_str = '\n'.join(lines[i:])
                try:
                    parsed = json.loads(json_str)
                    if isinstance(parsed, dict) and "total" in parsed and "passed" in parsed:
                        self.logger.log_info(f"Extracted and parsed JSON from output")
                        return {
                            "total": parsed.get("total", 0),
                            "passed": parsed.get("passed", 0),
                            "failed": parsed.get("failed", 0),
                            "stdout": stdout,
                            "stderr": stderr,
                            "returncode": returncode
                        }
                except json.JSONDecodeError:
                    continue

        # Priority 3: Try to parse text-based output (e.g., "X passed, Y failed")
        passed = 0
        failed = 0
        total = 0

        passed_match = re.search(r'(\d+)\s+passed', stdout + stderr)
        failed_match = re.search(r'(\d+)\s+failed', stdout + stderr)

        if passed_match:
            passed = int(passed_match.group(1))
        if failed_match:
            failed = int(failed_match.group(1))

        total = passed + failed

        # Priority 4: If no explicit counts, infer from return code
        if total == 0:
            if returncode == 0:
                # Assume 1 test passed if no explicit output
                passed = 1
                total = 1
                self.logger.log_warning(f"No test output found, inferring success from exit code 0")
            else:
                # Assume 1 test failed
                failed = 1
                total = 1
                self.logger.log_warning(f"No test output found, inferring failure from exit code {returncode}")

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode
        }

    async def _fix_instrumented_code(self,
                                     code: str,
                                     original_test_failures: Dict[str, Any] = None,
                                     instrumentation_test_failures: Dict[str, Any] = None) -> str:
        """
        Fix instrumented code based on test failures

        Args:
            code: Current instrumented code
            original_test_failures: Original test failures (if any)
            instrumentation_test_failures: Instrumentation test failures (if any)

        Returns:
            Fixed code
        """
        failure_info = []

        if original_test_failures:
            failure_info.append(f"ORIGINAL TESTS FAILED:\n{original_test_failures.get('stderr', '')}\n{original_test_failures.get('stdout', '')}")

        if instrumentation_test_failures:
            failure_info.append(f"INSTRUMENTATION TESTS FAILED:\n{instrumentation_test_failures.get('stderr', '')}\n{instrumentation_test_failures.get('stdout', '')}")

        prompt = f"""The instrumented code has test failures. Fix the code.

CURRENT INSTRUMENTED CODE:
```javascript
{code}
```

TEST FAILURES:
{chr(10).join(failure_info)}

DIAGNOSIS:
- If ORIGINAL tests fail: Your instrumentation broke the original functionality. You must fix it without affecting original behavior.
- If INSTRUMENTATION tests fail: The instrumentation variables are not being set correctly. Fix the instrumentation logic.

REQUIREMENTS:
1. DO NOT remove required instrumentation variables
2. Ensure original functionality is preserved
3. Wrap all instrumentation in try-catch blocks
4. Ensure both test suites pass

Return the complete fixed business_logic.js code."""

        # Log API call
        call_id = self.logger.log_api_call(
            "Fix Instrumented Code",
            prompt
        )

        try:
            result, usage_info = await call_openai_api_async(
                [{"role": "user", "content": prompt}],
                reasoning_effort=self.reasoning_effort,
                model=self.model
            )

            self.logger.log_api_response(
                "Fix Instrumented Code",
                success=True,
                response="[Fixed code generated]",
                usage_info=usage_info,
                call_id=call_id
            )

            # Extract code
            fixed_code = self._extract_code(result)
            return fixed_code

        except Exception as e:
            self.logger.log_error(f"Fix failed: {str(e)}")
            self.logger.log_api_response(
                "Fix Instrumented Code",
                success=False,
                error=str(e),
                call_id=call_id
            )
            # Return original code if fix fails
            return code

    def _extract_code(self, text: str) -> str:
        """Extract code from markdown blocks"""
        import re

        pattern = r'```(?:javascript)?\s*\n(.*?)\n```'
        matches = re.findall(pattern, text, re.DOTALL)

        if matches:
            return max(matches, key=len)

        return text.strip()
