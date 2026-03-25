"""
TDD Instrumentation Analyzer

Analyzes tasks and business logic to determine what instrumentation variables are needed
"""

import json
from typing import List, Dict, Any
from tdd_logger_module import TDDLogger
from tdd_instrumentation_data_models import (
    InstrumentationPlan,
    InstrumentationRequirement,
    InstrumentationVariable
)
from llm_caller import call_openai_api_json_async


class TDDInstrumentationAnalyzer:
    """
    Analyzes business logic to determine instrumentation requirements for task evaluation
    """

    def __init__(self, logger: TDDLogger = None, max_retries: int = 3,
                 reasoning_effort: str = "medium", model: str = None):
        """
        Initialize analyzer

        Args:
            logger: TDDLogger instance
            max_retries: Maximum retry attempts for API calls
            reasoning_effort: Reasoning effort level (minimal, low, medium, high)
            model: Model name to use (None for default)
        """
        self.logger = logger or TDDLogger()
        self.max_retries = max_retries
        self.reasoning_effort = reasoning_effort
        self.model = model

    async def analyze_requirements(self,
                                   tasks: List[Dict[str, Any]],
                                   business_logic_code: str,
                                   datadict: Dict[str, Any]) -> InstrumentationPlan:
        """
        Analyze what instrumentation variables are needed for each task

        Args:
            tasks: List of tasks to evaluate
            business_logic_code: Current business logic JavaScript code
            datadict: Data dictionary (data_models.json structure)

        Returns:
            InstrumentationPlan with requirements for each task
        """
        self.logger.start_stage("Analyze Instrumentation Requirements")
        self.logger.log_info(f"🔍 Analyzing instrumentation needs for {len(tasks)} tasks...")

        # Extract existing localStorage usage from code
        existing_storage_vars = self._extract_existing_storage_vars(business_logic_code)
        self.logger.log_info(f"Found {len(existing_storage_vars)} existing localStorage variables")

        # Extract datadict storage keys
        storage_keys = self._extract_storage_keys(datadict)
        self.logger.log_info(f"Found {len(storage_keys)} data storage keys")

        try:
            # Call LLM to analyze requirements
            requirements_data = await self._call_llm_for_analysis(
                tasks=tasks,
                business_logic_code=business_logic_code,
                existing_storage_vars=existing_storage_vars,
                storage_keys=storage_keys
            )

            # Parse into InstrumentationPlan
            plan = self._parse_requirements(requirements_data)

            self.logger.log_info(f"✅ Analysis complete:")
            self.logger.log_info(f"   - Tasks needing instrumentation: {sum(1 for r in plan.requirements if r.needs_instrumentation)}")
            self.logger.log_info(f"   - Total new variables needed: {len(plan.get_all_variables())}")
            self.logger.end_stage("Analyze Instrumentation Requirements")

            return plan

        except Exception as e:
            error_msg = f"Failed to analyze instrumentation requirements: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.end_stage("Analyze Instrumentation Requirements")
            raise Exception(error_msg)

    def _extract_existing_storage_vars(self, code: str) -> List[str]:
        """
        Extract localStorage variable names from business logic code

        Args:
            code: JavaScript code

        Returns:
            List of localStorage key names
        """
        import re

        # Pattern to match localStorage.setItem('key', ...) or localStorage.getItem('key')
        patterns = [
            r"localStorage\.setItem\(['\"]([^'\"]+)['\"]",
            r"localStorage\.getItem\(['\"]([^'\"]+)['\"]",
            r"localStorage\.removeItem\(['\"]([^'\"]+)['\"]"
        ]

        vars_found = set()
        for pattern in patterns:
            matches = re.findall(pattern, code)
            vars_found.update(matches)

        return sorted(list(vars_found))

    def _extract_storage_keys(self, datadict: Dict[str, Any]) -> List[str]:
        """
        Extract storage_key from datadict entities

        Args:
            datadict: Data models dictionary

        Returns:
            List of storage keys
        """
        storage_keys = []
        for entity in datadict.get("entities", []):
            if "storage_key" in entity:
                storage_keys.append(entity["storage_key"])
        return storage_keys

    async def _call_llm_for_analysis(self,
                                     tasks: List[Dict[str, Any]],
                                     business_logic_code: str,
                                     existing_storage_vars: List[str],
                                     storage_keys: List[str]) -> Dict[str, Any]:
        """
        Call LLM to analyze instrumentation requirements

        Args:
            tasks: List of tasks
            business_logic_code: Current JS code
            existing_storage_vars: Existing localStorage variables
            storage_keys: Data storage keys

        Returns:
            Parsed requirements data
        """
        # Prepare complete code (no limit)
        code_snippet = self._prepare_code_snippet(business_logic_code, max_lines=None)

        prompt = f"""You are analyzing JavaScript business logic to determine what instrumentation variables are needed to evaluate task completion.

CONTEXT:
- Each task describes a user action that must be completed on the website
- The business logic (SDK) implements functions that the website calls
- We need to add minimal instrumentation variables to localStorage to track task completion
- Instrumentation must NOT affect original functionality (non-invasive)

TASKS TO EVALUATE:
{json.dumps(tasks, indent=2)}

TASK SCHEMA NOTES:
- Some tasks may be rewritten tasks with this structure:
  - `instruction`: the natural-language instruction shown to the agent
  - `ground_truth`: exact targets / criteria for evaluation
- If `ground_truth` is present, use it as the authoritative source for task correctness when deciding
  what instrumentation is needed. This is especially important for exact quantities, target entities,
  comparison criteria, and form values.
- Do NOT rely only on `name` / `description` if `ground_truth` is available.

CURRENT BUSINESS LOGIC (complete):
{code_snippet}

EXISTING LOCALSTORAGE VARIABLES:
{json.dumps(existing_storage_vars, indent=2)}

DATA STORAGE KEYS:
{json.dumps(storage_keys, indent=2)}

ANALYSIS REQUIREMENTS:
For each task, determine:
1. What operations must occur for the task to be considered complete?
2. Can we use existing localStorage variables to determine completion?
3. If NOT, what new instrumentation variables are needed?

INSTRUMENTATION GUIDELINES:
- Only add variables if existing localStorage is insufficient
- Variables should be minimal and specific to task completion tracking
- Use clear naming convention: taskN_actionDescription (e.g., task1_searchCompleted, task2_comparisonViewed)
- Specify exactly which function should set the variable and under what condition
- Variables should be boolean, string, or simple objects

CRITICAL - TRACK CORRECTNESS, NOT JUST ACTIONS:
- Don't just track "user performed search" - track "user searched with CORRECT criteria"
- Don't just track "user selected item" - track "user selected item that MATCHES task requirements"
- Store enough context to verify correctness in evaluator (e.g., filter params, selected item ID)

INSTRUMENTATION PATTERNS FOR CORRECTNESS:
1. For filtering tasks: Store the filter parameters used
   - Example: task1_filterParams (object with filter criteria like {{hasRoadside: true}})
   - This allows evaluator to check if user used CORRECT filters

2. For selection tasks: Store the selected item ID
   - Example: task1_selectedPlanId (string)
   - Evaluator can verify if selected item MATCHES task requirements

3. For comparison tasks: Store which items were compared
   - Example: task1_comparedItemIds (array of IDs)
   - Evaluator can verify if user compared the RIGHT items

4. For multi-step tasks: Track completion of each CORRECT step
   - Example: task1_correctFilterUsed (boolean), task1_qualifyingItemSelected (boolean)

RETURN FORMAT (JSON):
{{
  "analysis_summary": "Brief summary of findings",
  "requirements": [
    {{
      "task_id": "task_1",
      "task_name": "Task name",
      "task_description": "Task description",
      "needs_instrumentation": true/false,
      "reasoning": "Why instrumentation is/isn't needed",
      "existing_variables": ["var1", "var2"],  // If sufficient
      "required_variables": [  // If needs instrumentation
        {{
          "variable_name": "task1_searchCompleted",
          "variable_type": "boolean",
          "set_in_function": "searchNeighborhoods",
          "set_condition": "After successful search with results.length > 0",
          "value_to_set": "true",
          "reason": "Track if user successfully performed a search"
        }}
      ]
    }}
  ]
}}

IMPORTANT: Be conservative - only add instrumentation if truly necessary for evaluating task completion."""

        # Log API call
        call_id = self.logger.log_api_call(
            "Analyze Instrumentation Requirements",
            prompt
        )

        # Retry logic
        for attempt in range(self.max_retries):
            try:
                result, usage_info = await call_openai_api_json_async(
                    [{"role": "user", "content": prompt}],
                    reasoning_effort=self.reasoning_effort,
                    model=self.model
                )

                # Log success
                self.logger.log_api_response(
                    "Analyze Instrumentation Requirements",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    call_id=call_id
                )

                # Parse if string
                if isinstance(result, str):
                    result = json.loads(result)

                # Validate structure
                if not isinstance(result, dict) or "requirements" not in result:
                    raise ValueError("Invalid response structure - missing 'requirements'")

                return result

            except Exception as e:
                self.logger.log_error(f"API call failed on attempt {attempt + 1}: {str(e)}")
                if attempt == self.max_retries - 1:
                    self.logger.log_api_response(
                        "Analyze Instrumentation Requirements",
                        success=False,
                        error=str(e),
                        call_id=call_id
                    )
                    raise

        raise Exception("Failed after max retries")

    def _prepare_code_snippet(self, code: str, max_lines: int = None) -> str:
        """
        Prepare code for LLM analysis

        Args:
            code: Full code
            max_lines: Maximum lines to include (None for complete code)

        Returns:
            Code snippet or complete code
        """
        # If max_lines is None, return complete code
        if max_lines is None:
            return code

        lines = code.split('\n')
        if len(lines) <= max_lines:
            return code

        # Take first max_lines with a note
        snippet = '\n'.join(lines[:max_lines])
        snippet += f"\n\n... (truncated {len(lines) - max_lines} more lines)"
        return snippet

    def _parse_requirements(self, data: Dict[str, Any]) -> InstrumentationPlan:
        """
        Parse LLM response into InstrumentationPlan

        Args:
            data: Response data from LLM

        Returns:
            InstrumentationPlan object
        """
        requirements = []

        for req_data in data.get("requirements", []):
            # Parse variables
            variables = []
            for var_data in req_data.get("required_variables", []):
                variable = InstrumentationVariable(
                    variable_name=var_data["variable_name"],
                    variable_type=var_data["variable_type"],
                    set_in_function=var_data["set_in_function"],
                    set_condition=var_data["set_condition"],
                    value_to_set=var_data["value_to_set"],
                    reason=var_data["reason"]
                )
                variables.append(variable)

            # Create requirement
            requirement = InstrumentationRequirement(
                task_id=req_data["task_id"],
                task_name=req_data["task_name"],
                task_description=req_data["task_description"],
                needs_instrumentation=req_data["needs_instrumentation"],
                existing_variables=req_data.get("existing_variables", []),
                required_variables=variables
            )
            requirements.append(requirement)

        return InstrumentationPlan(requirements=requirements)
