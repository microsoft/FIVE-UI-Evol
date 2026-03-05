"""
TDD Instrumentation Generator

Generates instrumented code and tests in TDD style
"""

import json
from typing import Dict, Any, Tuple
from tdd_logger_module import TDDLogger
from tdd_instrumentation_data_models import InstrumentationPlan
from llm_caller import call_openai_api_async


class TDDInstrumentationGenerator:
    """
    Generates instrumented business logic and corresponding tests
    """

    def __init__(self, logger: TDDLogger = None, max_retries: int = 3,
                 reasoning_effort: str = "medium", model: str = None):
        """
        Initialize generator

        Args:
            logger: TDDLogger instance
            max_retries: Maximum retry attempts
            reasoning_effort: Reasoning effort level (minimal, low, medium, high)
            model: Model name to use (None for default)
        """
        self.logger = logger or TDDLogger()
        self.max_retries = max_retries
        self.reasoning_effort = reasoning_effort
        self.model = model

    async def generate(self,
                      instrumentation_plan: InstrumentationPlan,
                      original_code: str,
                      test_data: Dict[str, Any]) -> str:
        """
        Generate instrumented code

        Args:
            instrumentation_plan: Plan for what to instrument
            original_code: Original business_logic.js code
            test_data: Test data (unused, kept for compatibility)

        Returns:
            Instrumented code
        """
        self.logger.start_stage("Generate Instrumented Code")
        self.logger.log_info("🛠️ Generating instrumented code...")

        try:
            # Generate instrumented code
            self.logger.log_info("Adding instrumentation to business logic...")
            instrumented_code = await self._generate_instrumented_code(
                instrumentation_plan, original_code
            )
            self.logger.log_info("✅ Instrumented code generated")

            self.logger.end_stage("Generate Instrumented Code")
            return instrumented_code

        except Exception as e:
            error_msg = f"Failed to generate instrumented code: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.end_stage("Generate Instrumented Code")
            raise Exception(error_msg)

    async def _generate_instrumented_code(self,
                                         plan: InstrumentationPlan,
                                         original_code: str) -> str:
        """
        Generate instrumented business logic code

        Args:
            plan: Instrumentation plan
            original_code: Original code

        Returns:
            Instrumented code
        """
        # Prepare instrumentation specifications
        instrumentation_specs = []
        for req in plan.requirements:
            if req.needs_instrumentation:
                for var in req.required_variables:
                    instrumentation_specs.append({
                        "task_id": req.task_id,
                        "variable_name": var.variable_name,
                        "variable_type": var.variable_type,
                        "set_in_function": var.set_in_function,
                        "set_condition": var.set_condition,
                        "value_to_set": var.value_to_set,
                        "reason": var.reason
                    })

        if not instrumentation_specs:
            self.logger.log_info("No instrumentation needed - returning original code")
            return original_code

        prompt = f"""You are adding instrumentation variables to JavaScript business logic for task completion tracking.

ORIGINAL CODE:
```javascript
{original_code}
```

INSTRUMENTATION SPECIFICATIONS:
{json.dumps(instrumentation_specs, indent=2)}

INSTRUCTIONS:
For each instrumentation variable:
1. Find the specified function in the code
2. Add localStorage.setItem() call at the appropriate location based on the set_condition
3. Wrap instrumentation code in try-catch to ensure non-invasive behavior
4. Use the exact variable_name and value_to_set from specifications

EXAMPLE:
Original:
```javascript
searchNeighborhoods(query) {{
    const results = this._performSearch(query);
    return results;
}}
```

Instrumented (if spec says: set task1_searchCompleted to 'true' when results.length > 0):
```javascript
searchNeighborhoods(query) {{
    const results = this._performSearch(query);

    // Instrumentation for task completion tracking
    try {{
        if (results && results.length > 0) {{
            localStorage.setItem('task1_searchCompleted', 'true');
            localStorage.setItem('task1_searchQuery', query);
        }}
    }} catch (e) {{
        console.error('Instrumentation error:', e);
    }}

    return results;
}}
```

CRITICAL REQUIREMENTS:
- DO NOT change any original functionality
- DO NOT modify function signatures or return values
- Instrumentation code must be wrapped in try-catch
- Only add localStorage.setItem() calls as specified
- Preserve all existing code structure and comments
- Place instrumentation BEFORE the return statement or at the appropriate location

Return the complete instrumented business_logic.js code."""

        # Log API call
        call_id = self.logger.log_api_call(
            "Generate Instrumented Code",
            prompt
        )

        # Call LLM
        for attempt in range(self.max_retries):
            try:
                result, usage_info = await call_openai_api_async(
                    [{"role": "user", "content": prompt}],
                    reasoning_effort=self.reasoning_effort,
                    model=self.model
                )

                self.logger.log_api_response(
                    "Generate Instrumented Code",
                    success=True,
                    response="[Code generated]",
                    usage_info=usage_info,
                    call_id=call_id
                )

                # Extract code from markdown if present
                instrumented_code = self._extract_code(result)
                return instrumented_code

            except Exception as e:
                self.logger.log_error(f"API call failed on attempt {attempt + 1}: {str(e)}")
                if attempt == self.max_retries - 1:
                    self.logger.log_api_response(
                        "Generate Instrumented Code",
                        success=False,
                        error=str(e),
                        call_id=call_id
                    )
                    raise

        raise Exception("Failed after max retries")

    def _extract_code(self, text: str) -> str:
        """
        Extract code from markdown code blocks if present

        Args:
            text: Response text

        Returns:
            Extracted code
        """
        import re

        # Try to extract from ```javascript ... ``` or ``` ... ```
        pattern = r'```(?:javascript)?\s*\n(.*?)\n```'
        matches = re.findall(pattern, text, re.DOTALL)

        if matches:
            # Return the first (or largest) code block
            return max(matches, key=len)

        # If no code blocks, return as-is
        return text.strip()
