"""
TDD Evaluator Validator

Validates that evaluators correctly judge task completion
"""

import os
import json
import subprocess
import tempfile
from typing import Dict, Any, List, Tuple
from tdd_logger_module import TDDLogger
from tdd_instrumentation_data_models import EvaluatorValidationResult
from tdd_instrumentation_evaluator import TDDEvaluator
from llm_caller import call_openai_api_json_async


class TDDEvaluatorValidator:
    """
    Validates evaluator logic correctness by generating and running test cases
    """

    def __init__(self, logger: TDDLogger = None, max_fix_iterations: int = 3,
                 reasoning_effort: str = "medium", model: str = None):
        """
        Initialize evaluator validator

        Args:
            logger: TDDLogger instance
            max_fix_iterations: Maximum fix iterations per evaluator
            reasoning_effort: Reasoning effort level (minimal, low, medium, high)
            model: Model name to use (None for default)
        """
        self.logger = logger or TDDLogger()
        self.max_fix_iterations = max_fix_iterations
        self.reasoning_effort = reasoning_effort
        self.model = model

    async def validate_and_fix_evaluators(self,
                                          evaluators: List[TDDEvaluator],
                                          instrumented_code: str,
                                          tasks: List[Dict[str, Any]],
                                          test_data: Dict[str, Any]) -> Tuple[List[TDDEvaluator], EvaluatorValidationResult]:
        """
        Validate and fix all evaluators

        Args:
            evaluators: List of evaluators to validate
            instrumented_code: Instrumented business logic
            tasks: Task definitions
            test_data: Test data

        Returns:
            Tuple of (validated_evaluators, validation_result)
        """
        self.logger.start_stage("Validate Evaluators")
        self.logger.log_info(f"🧪 Validating {len(evaluators)} evaluators...")

        validated_evaluators = []
        failed_evaluator_ids = []
        total_iterations = 0

        for evaluator in evaluators:
            self.logger.log_info(f"\n📊 Validating evaluator: {evaluator.task_id} - {evaluator.name}")

            try:
                # Validate and fix single evaluator
                validated_evaluator, iterations = await self._validate_and_fix_single_evaluator(
                    evaluator, instrumented_code, tasks, test_data
                )

                total_iterations += iterations
                validated_evaluators.append(validated_evaluator)
                self.logger.log_info(f"✅ Evaluator {evaluator.task_id} validated successfully")

            except Exception as e:
                self.logger.log_error(f"❌ Evaluator {evaluator.task_id} validation failed: {str(e)}")
                # Keep original evaluator if validation fails
                validated_evaluators.append(evaluator)
                failed_evaluator_ids.append(evaluator.task_id)

        # Create result
        success = len(failed_evaluator_ids) == 0
        result = EvaluatorValidationResult(
            success=success,
            total_evaluators=len(evaluators),
            validated_evaluators=len(evaluators) - len(failed_evaluator_ids),
            failed_evaluators=len(failed_evaluator_ids),
            iterations_used=total_iterations,
            message=f"Validated {len(validated_evaluators) - len(failed_evaluator_ids)}/{len(evaluators)} evaluators",
            failed_evaluator_ids=failed_evaluator_ids
        )

        self.logger.log_info(f"\n{'✅' if success else '⚠️'} Validation complete:")
        self.logger.log_info(f"   Total: {result.total_evaluators}")
        self.logger.log_info(f"   Passed: {result.validated_evaluators}")
        self.logger.log_info(f"   Failed: {result.failed_evaluators}")
        self.logger.end_stage("Validate Evaluators")

        return validated_evaluators, result

    async def _validate_and_fix_single_evaluator(self,
                                                  evaluator: TDDEvaluator,
                                                  instrumented_code: str,
                                                  tasks: List[Dict[str, Any]],
                                                  test_data: Dict[str, Any]) -> Tuple[TDDEvaluator, int]:
        """
        Validate and fix a single evaluator

        Args:
            evaluator: Evaluator to validate
            instrumented_code: Business logic code
            tasks: All tasks
            test_data: Test data

        Returns:
            Tuple of (validated_evaluator, iterations_used)
        """
        current_evaluator = evaluator
        iteration = 0

        # Find task definition
        task = next((t for t in tasks if t.get("id") == evaluator.task_id), None)
        if not task:
            raise Exception(f"Task {evaluator.task_id} not found")

        while iteration < self.max_fix_iterations:
            iteration += 1
            self.logger.log_info(f"  Iteration {iteration}/{self.max_fix_iterations}")

            # Generate test cases for this evaluator
            test_cases = await self._generate_test_cases(current_evaluator, task, test_data)

            # Run tests
            test_results = self._run_evaluator_tests(
                current_evaluator, instrumented_code, test_cases, test_data
            )

            # Log detailed test results for debugging
            self.logger.log_info(f"  Test results: total={test_results.get('total')}, passed={test_results.get('passed')}, failed={test_results.get('failed')}")
            if test_results.get("total", 0) == 0:
                self.logger.log_warning(f"  ⚠️ No tests were executed! Checking test code...")
                self.logger.log_info(f"  Test code preview (first 500 chars):\n{test_cases}")
                if test_results.get("stderr"):
                    self.logger.log_error(f"  stderr: {test_results.get('stderr')}")
                if test_results.get("stdout"):
                    self.logger.log_info(f"  stdout: {test_results.get('stdout')}")

            # Check if all tests passed
            all_passed = test_results.get("passed", 0) == test_results.get("total", 0)

            # If no tests were executed, treat as failure
            if test_results.get("total", 0) == 0:
                self.logger.log_error(f"  ❌ No tests executed - treating as failure")
                all_passed = False

            if all_passed and test_results.get("total", 0) > 0:
                self.logger.log_info(f"  ✅ All tests passed ({test_results.get('passed')}/{test_results.get('total')})")
                return current_evaluator, iteration

            # Fix evaluator
            self.logger.log_warning(f"  ⚠️ Tests failed ({test_results.get('failed')}/{test_results.get('total')}), fixing...")
            current_evaluator = await self._fix_evaluator(
                current_evaluator, task, test_results
            )

        # Max iterations reached
        raise Exception(f"Max iterations ({self.max_fix_iterations}) reached")

    async def _generate_test_cases(self,
                                    evaluator: TDDEvaluator,
                                    task: Dict[str, Any],
                                    test_data: Dict[str, Any]) -> str:
        """
        Generate test cases for evaluator (positive and negative scenarios)

        Args:
            evaluator: Evaluator to test
            task: Task definition
            test_data: Test data

        Returns:
            Test code as string
        """
        # Pre-process evaluation logic for prompt
        eval_logic_escaped = evaluator.evaluation_logic.replace('\n', '\\n').replace('"', '\\"')

        prompt = f"""Generate test cases to validate an evaluator's logic.

TASK DEFINITION:
{json.dumps(task, indent=2)}

EVALUATOR:
{{
  "task_id": "{evaluator.task_id}",
  "name": "{evaluator.name}",
  "description": "{evaluator.description}",
  "localStorage_variables": {json.dumps(evaluator.localStorage_variables, indent=2)},
  "evaluation_logic": "{eval_logic_escaped}"
}}

TEST DATA (sample):
{json.dumps(test_data, indent=2)}

INSTRUCTIONS:
Generate test cases that validate evaluator scoring (0.0-1.0):
1. **Full completion tests**: Execute all task steps → evaluator should return 1.0 (or close to 1.0)
2. **Partial completion tests**: Execute some steps → evaluator should return intermediate scores (e.g., 0.3-0.8)
3. **No completion tests**: Skip all steps → evaluator should return 0.0 (or close to 0.0)

Each test should:
- Setup: Initialize localStorage with test data
- Execute: Call business logic methods to set instrumentation variables
- Evaluate: Run the evaluator logic
- Assert: Check if result is a NUMBER in the expected range (NOT a boolean)

IMPORTANT: Use TestRunner class pattern (NOT Jest)

EXAMPLE STRUCTURE:
```javascript
class EvaluatorTestRunner {{
  constructor(businessLogic) {{
    this.logic = businessLogic || new BusinessLogic();
    this.results = [];
  }}

  clearStorage() {{
    localStorage.clear();
  }}

  setupTestData() {{
    const testData = {json.dumps(test_data, indent=2)};
    for (const key in testData) {{
      localStorage.setItem(key, JSON.stringify(testData[key]));
    }}
  }}

  runAllTests() {{
    console.log('Starting evaluator tests...');
    this.testEvaluator_FullCompletion();
    this.testEvaluator_NoCompletion();
    return this.results;
  }}

  testEvaluator_FullCompletion() {{
    const testName = '{evaluator.task_id}: Full completion should return ~1.0';
    try {{
      this.clearStorage();
      this.setupTestData();

      // Execute complete task steps
      // Example: this.logic.searchArticles('query');
      //          this.logic.filterResults({{...}});

      // Run evaluator
      const result = (function() {{ {evaluator.evaluation_logic} }})();

      // Assert score is close to 1.0 (allow small tolerance)
      this.assert(typeof result === 'number', 'Evaluator should return a number, got: ' + typeof result);
      this.assert(result >= 0.9 && result <= 1.0, 'Evaluator should return ~1.0 for complete task, got: ' + result);
      this.recordSuccess(testName);
    }} catch (error) {{
      this.recordFailure(testName, error);
    }}
  }}

  testEvaluator_NoCompletion() {{
    const testName = '{evaluator.task_id}: No completion should return ~0.0';
    try {{
      this.clearStorage();
      this.setupTestData();

      // Execute NO task steps (or clear relevant state)
      // Just setup data but don't execute any task-specific actions

      // Run evaluator
      const result = (function() {{ {evaluator.evaluation_logic} }})();

      // Assert score is close to 0.0 (allow for data existence checkpoints)
      this.assert(typeof result === 'number', 'Evaluator should return a number, got: ' + typeof result);
      this.assert(result >= 0.0 && result <= 0.3, 'Evaluator should return ~0.0-0.3 for no completion, got: ' + result);
      this.recordSuccess(testName);
    }} catch (error) {{
      this.recordFailure(testName, error);
    }}
  }}

  assert(condition, message) {{
    if (!condition) throw new Error('Assertion failed: ' + message);
  }}

  recordSuccess(testName) {{
    this.results.push({{ test: testName, success: true }});
    console.log('✓ ' + testName);
  }}

  recordFailure(testName, error) {{
    this.results.push({{ test: testName, success: false, error: error.message }});
    console.log('✗ ' + testName + ': ' + error.message);
  }}
}}

module.exports = EvaluatorTestRunner;
```

REQUIREMENTS:
- Generate at least 1 full completion test (should return ~1.0)
- Generate at least 1 no completion test (should return ~0.0)
- Optionally add partial completion tests (should return intermediate values like 0.3-0.7)
- Use this.logic methods to execute task steps
- Run evaluator with: (function() {{ {evaluator.evaluation_logic} }})()
- The evaluator returns a NUMBER (0.0-1.0), NOT a boolean
- End with: module.exports = EvaluatorTestRunner;

Return the complete test code."""

        # Log API call
        call_id = self.logger.log_api_call(
            f"Generate Test Cases for {evaluator.task_id}",
            prompt
        )

        try:
            result, usage_info = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                reasoning_effort=self.reasoning_effort,
                model=self.model
            )

            self.logger.log_api_response(
                f"Generate Test Cases for {evaluator.task_id}",
                success=True,
                response="[Test cases generated]",
                usage_info=usage_info,
                call_id=call_id
            )

            # Extract code
            test_code = self._extract_code(result if isinstance(result, str) else json.dumps(result))
            return test_code

        except Exception as e:
            self.logger.log_error(f"Failed to generate test cases: {str(e)}")
            self.logger.log_api_response(
                f"Generate Test Cases for {evaluator.task_id}",
                success=False,
                error=str(e),
                call_id=call_id
            )
            raise

    def _run_evaluator_tests(self,
                             evaluator: TDDEvaluator,
                             instrumented_code: str,
                             test_cases: str,
                             test_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run evaluator tests in Node.js environment

        Args:
            evaluator: Evaluator being tested
            instrumented_code: Business logic
            test_cases: Test code
            test_data: Test data

        Returns:
            Test results dictionary
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write business logic
                code_path = os.path.join(tmpdir, "business_logic.js")
                with open(code_path, 'w', encoding='utf-8') as f:
                    f.write(instrumented_code)

                # Write test cases
                test_path = os.path.join(tmpdir, "test_runner.js")
                with open(test_path, 'w', encoding='utf-8') as f:
                    f.write(test_cases)

                # Create package.json
                package_json = {
                    "name": "evaluator-test",
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

                # Create executor
                executor_code = """
                const { LocalStorage } = require('node-localstorage');
                global.localStorage = new LocalStorage('./test-storage');
                localStorage.clear();

                const BusinessLogic = require('./business_logic.js');
                const TestRunner = require('./test_runner.js');

                const logic = new BusinessLogic();
                const runner = new TestRunner(logic);
                const results = runner.runAllTests();

                console.log(JSON.stringify({
                    total: results.length,
                    passed: results.filter(r => r.success).length,
                    failed: results.filter(r => !r.success).length,
                    details: results
                }, null, 2));

                localStorage.clear();
                """

                executor_path = os.path.join(tmpdir, "executor.js")
                with open(executor_path, 'w', encoding='utf-8') as f:
                    f.write(executor_code)

                # Run tests
                node_cmd = "node"
                result = subprocess.run(
                    [node_cmd, executor_path],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                # Parse output
                return self._parse_test_output(result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            self.logger.log_error(f"Evaluator tests timed out")
            return {"total": 0, "passed": 0, "failed": 0, "error": "Timeout"}
        except Exception as e:
            self.logger.log_error(f"Evaluator test error: {str(e)}")
            return {"total": 0, "passed": 0, "failed": 0, "error": str(e)}

    def _parse_test_output(self, stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
        """Parse test output"""
        import re

        # Try to parse JSON
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, dict) and "total" in parsed:
                return {
                    "total": parsed.get("total", 0),
                    "passed": parsed.get("passed", 0),
                    "failed": parsed.get("failed", 0),
                    "details": parsed.get("details", []),
                    "stdout": stdout,
                    "stderr": stderr
                }
        except json.JSONDecodeError:
            pass

        # Extract from mixed output
        lines = stdout.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith('{'):
                try:
                    parsed = json.loads('\n'.join(lines[i:]))
                    if isinstance(parsed, dict) and "total" in parsed:
                        return {
                            "total": parsed.get("total", 0),
                            "passed": parsed.get("passed", 0),
                            "failed": parsed.get("failed", 0),
                            "details": parsed.get("details", []),
                            "stdout": stdout,
                            "stderr": stderr
                        }
                except json.JSONDecodeError:
                    continue

        # Fallback
        return {
            "total": 0 if returncode != 0 else 1,
            "passed": 0 if returncode != 0 else 1,
            "failed": 1 if returncode != 0 else 0,
            "stdout": stdout,
            "stderr": stderr
        }

    async def _fix_evaluator(self,
                             evaluator: TDDEvaluator,
                             task: Dict[str, Any],
                             test_results: Dict[str, Any]) -> TDDEvaluator:
        """
        Fix evaluator based on test failures

        Args:
            evaluator: Current evaluator
            task: Task definition
            test_results: Test results with failures

        Returns:
            Fixed evaluator
        """
        # Pre-process evaluation logic for prompt
        eval_logic_escaped = evaluator.evaluation_logic.replace('\n', '\\n').replace('"', '\\"')

        prompt = f"""Fix the evaluator logic based on test failures.

TASK DEFINITION:
{json.dumps(task, indent=2)}

CURRENT EVALUATOR:
{{
  "task_id": "{evaluator.task_id}",
  "name": "{evaluator.name}",
  "description": "{evaluator.description}",
  "localStorage_variables": {json.dumps(evaluator.localStorage_variables, indent=2)},
  "evaluation_logic": "{eval_logic_escaped}"
}}

TEST FAILURES:
{json.dumps(test_results.get('details', []), indent=2)}

DIAGNOSIS:
The evaluator's evaluation_logic is incorrectly scoring task completion.
Analyze the test failures and fix the logic.

REQUIREMENTS:
1. Use checkpoint-based scoring pattern (NOT boolean true/false)
2. Return a NUMBER from 0.0 to 1.0 based on completed checkpoints
3. Total checkpoint weights must sum to 1.0
4. Return 1.0 only when ALL required steps are completed
5. Return partial scores (0.1-0.9) for partial completion
6. Return ~0.0 if no steps are completed (allow small score for data existence)
7. Check all localStorage variables listed in localStorage_variables
8. Handle edge cases (null, undefined, empty strings)

SCORING PATTERN:
```javascript
const checkpoints = [];
checkpoints.push({ passed: condition1, weight: 0.2 });
checkpoints.push({ passed: condition2, weight: 0.3 });
// ... more checkpoints
return checkpoints.reduce((sum, cp) => sum + (cp.passed ? cp.weight : 0), 0);
```

RETURN FORMAT (JSON):
{{
  "task_id": "{evaluator.task_id}",
  "name": "{evaluator.name}",
  "description": "{evaluator.description}",
  "localStorage_variables": {json.dumps(evaluator.localStorage_variables, indent=2)},
  "evaluation_logic": "// Fixed JavaScript code"
}}

Return the complete fixed evaluator."""

        # Log API call
        call_id = self.logger.log_api_call(
            f"Fix Evaluator {evaluator.task_id}",
            prompt
        )

        try:
            result, usage_info = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                reasoning_effort=self.reasoning_effort,
                model=self.model
            )

            self.logger.log_api_response(
                f"Fix Evaluator {evaluator.task_id}",
                success=True,
                response="[Evaluator fixed]",
                usage_info=usage_info,
                call_id=call_id
            )

            # Parse result
            if isinstance(result, str):
                result = json.loads(result)

            # Create fixed evaluator
            fixed_evaluator = TDDEvaluator(
                task_id=result.get("task_id", evaluator.task_id),
                name=result.get("name", evaluator.name),
                description=result.get("description", evaluator.description),
                localStorage_variables=result.get("localStorage_variables", evaluator.localStorage_variables),
                evaluation_logic=result.get("evaluation_logic", evaluator.evaluation_logic)
            )

            return fixed_evaluator

        except Exception as e:
            self.logger.log_error(f"Failed to fix evaluator: {str(e)}")
            self.logger.log_api_response(
                f"Fix Evaluator {evaluator.task_id}",
                success=False,
                error=str(e),
                call_id=call_id
            )
            raise

    def _extract_code(self, text: str) -> str:
        """Extract code from markdown blocks"""
        import re

        pattern = r'```(?:javascript)?\s*\n(.*?)\n```'
        matches = re.findall(pattern, text, re.DOTALL)

        if matches:
            return max(matches, key=len)

        return text.strip()
