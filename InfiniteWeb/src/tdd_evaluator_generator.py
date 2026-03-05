"""
TDD Evaluator Generator Module
Generates evaluators to validate user task completion based on generated data and cross-page states
"""

import json
from typing import List, Dict, Any, Optional
from tdd_logger_module import TDDLogger
from tdd_data_manager import TDDEvaluator
from llm_caller import call_openai_api_json_async


class TDDEvaluatorGenerator:
    """
    Generates evaluators for TDD system to validate user task completion
    """
    
    def __init__(self, logger: TDDLogger = None, max_retries: int = 3, model=None, reasoning_effort=None):
        """
        Initialize TDD Evaluator Generator

        Args:
            logger: TDDLogger instance
            max_retries: Maximum number of retry attempts for API calls
            model: Model to use (None for default)
            reasoning_effort: Reasoning effort level for LLM calls
        """
        self.logger = logger or TDDLogger()
        self.max_retries = max_retries
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def generate_evaluators(self, tasks: List[Dict[str, Any]], 
                                 generated_data: Dict[str, Any],
                                 architecture: Dict[str, Any],
                                 website_type: str) -> List[TDDEvaluator]:
        """
        Generate evaluators for task completion validation
        
        Args:
            tasks: List of user tasks to evaluate
            generated_data: Generated website data structure
            architecture: Website architecture with cross-page states
            website_type: Type of website (for context)
            
        Returns:
            List of TDDEvaluator instances
            
        Raises:
            Exception: If evaluator generation fails
        """
        self.logger.start_stage("Generate Evaluators")
        self.logger.log_info("🔍 Generating task evaluators based on generated data and architecture...")
        
        # Prepare data for prompt
        cross_page_states = architecture.get("cross_page_states", {})
        static_data_structure = self._extract_data_structure(generated_data)
        
        try:
            # Generate evaluators via LLM
            evaluators_data = await self._call_llm_for_evaluators(
                tasks, cross_page_states, static_data_structure, website_type
            )
            
            # Create TDDEvaluator instances
            evaluators = []
            for eval_data in evaluators_data["evaluators"]:
                evaluator = TDDEvaluator.from_dict(eval_data)
                evaluators.append(evaluator)
            
            self.logger.log_info(f"✅ Successfully generated {len(evaluators)} task evaluators")
            self.logger.end_stage("Generate Evaluators")
            
            return evaluators
            
        except Exception as e:
            error_msg = f"Failed to generate evaluators: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.end_stage("Generate Evaluators")
            raise Exception(error_msg)
    
    def _extract_data_structure(self, generated_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract data structure information from generated data
        
        Args:
            generated_data: Generated website data
            
        Returns:
            Dictionary with data structure information
        """
        structure = {}
        
        for data_type, data_list in generated_data.items():
            if isinstance(data_list, list) and len(data_list) > 0:
                # Get field names and types from the first item
                first_item = data_list[0]
                if isinstance(first_item, dict):
                    fields = {}
                    for field_name, field_value in first_item.items():
                        if isinstance(field_value, str):
                            fields[field_name] = "string"
                        elif isinstance(field_value, int):
                            fields[field_name] = "number"
                        elif isinstance(field_value, float):
                            fields[field_name] = "number"
                        elif isinstance(field_value, bool):
                            fields[field_name] = "boolean"
                        elif isinstance(field_value, list):
                            fields[field_name] = "array"
                        elif isinstance(field_value, dict):
                            fields[field_name] = "object"
                        else:
                            fields[field_name] = "any"
                    
                    structure[data_type] = {
                        "fields": fields,
                        "count": len(data_list),
                        "sample_item": first_item
                    }
        
        return structure
    
    async def _call_llm_for_evaluators(self, tasks: List[Dict[str, Any]],
                                cross_page_states: Dict[str, Any],
                                data_structure: Dict[str, Any],
                                website_type: str) -> Dict[str, Any]:
        """
        Call LLM to generate evaluators
        
        Args:
            tasks: List of user tasks
            cross_page_states: Cross-page state definitions
            data_structure: Data structure information
            website_type: Type of website
            
        Returns:
            Dictionary containing evaluators data
        """
        prompt = f"""
        You are a QA engineer. Create evaluators to check if users complete tasks successfully.
        
        Website Type: {website_type}
        
        Tasks to evaluate:
        {json.dumps(tasks, indent=2)}
        
        Cross-Page States Structure:
        {json.dumps(cross_page_states, indent=2)}
        
        Generated Data Structure:
        {json.dumps(data_structure, indent=2)}
        
        For each task, create an evaluator that:
        - Uses cross-page states stored in localStorage to determine completion
        - Uses data structure knowledge to create precise validation logic
        - References exact field names and data types from the data structure
        - Provides clear evaluation criteria and logic
        - Uses JavaScript logic to check task completion status
        
        Guidelines:
        - Cross-page states contain data type references, default values, and descriptions
        - Data structure contains the exact field names, types, and sample data
        - Use localStorage.getItem() to access both cross-page states and static data
        - Parse JSON data when retrieving complex objects from localStorage
        - Check for null/undefined values before accessing object properties
        - Use realistic validation logic based on the actual data structure
        
        Return your response in JSON format:
        {{
            "evaluators": [
                {{
                    "task_id": "task_1",
                    "name": "Evaluator Name",
                    "description": "What this evaluator checks",
                    "localStorage_variables": ["selectedProductId", "products"],
                    "evaluation_logic": "// JavaScript code using exact field names from data structure\\nconst products = JSON.parse(localStorage.getItem('products') || '[]');\\nconst selectedId = localStorage.getItem('selectedProductId');\\nreturn products.some(p => p.id === selectedId);"
                }}
            ]
        }}
        """
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Generate Task Evaluators",
                prompt,
                additional_args={"max_retries": self.max_retries}
            )

        # Retry logic
        for attempt in range(self.max_retries):
            try:
                result, usage_info = await call_openai_api_json_async(
                    [{"role": "user", "content": prompt}],
                    model=self.model,
                    reasoning_effort=self.reasoning_effort
                )
                
                # Log successful API response
                if self.logger:
                    self.logger.log_api_response(
                        "Generate Task Evaluators",
                        success=True,
                        response=result,
                        usage_info=usage_info,
                        call_id=call_id
                    )
                
                # Parse result if it's a string
                if isinstance(result, str):
                    result = json.loads(result)
                
                # Validate result structure
                if not isinstance(result, dict) or "evaluators" not in result:
                    raise ValueError("Invalid response structure - missing 'evaluators' key")
                
                if not isinstance(result["evaluators"], list):
                    raise ValueError("Invalid response structure - 'evaluators' must be a list")
                
                # Validate each evaluator
                for eval_data in result["evaluators"]:
                    required_fields = ["task_id", "name", "description", "localStorage_variables", "evaluation_logic"]
                    for field in required_fields:
                        if field not in eval_data:
                            raise ValueError(f"Missing required field '{field}' in evaluator")
                
                return result
                
            except json.JSONDecodeError as e:
                self.logger.log_error(f"JSON parse error on attempt {attempt + 1}: {str(e)}")
                if attempt == self.max_retries - 1:
                    # Log failed API response on final attempt
                    if self.logger:
                        self.logger.log_api_response(
                            "Generate Task Evaluators",
                            success=False,
                            error=str(e),
                            call_id=call_id
                        )
                    raise Exception(f"Failed to parse JSON response after {self.max_retries} attempts")
            
            except Exception as e:
                self.logger.log_error(f"API call failed on attempt {attempt + 1}: {str(e)}")
                if attempt == self.max_retries - 1:
                    # Log failed API response on final attempt
                    if self.logger:
                        self.logger.log_api_response(
                            "Generate Task Evaluators",
                            success=False,
                            error=str(e),
                            call_id=call_id
                        )
                    raise Exception(f"Failed to generate evaluators after {self.max_retries} attempts")
        
        raise Exception("Unexpected error in LLM call")
    
    def save_evaluators(self, evaluators: List[TDDEvaluator], 
                       cross_page_states: Dict[str, Any],
                       static_data_types: List[str],
                       output_path: str) -> None:
        """
        Save evaluators to JSON file
        
        Args:
            evaluators: List of TDDEvaluator instances
            cross_page_states: Cross-page state definitions
            static_data_types: List of static data type names
            output_path: Path to save evaluators.json
        """
        evaluators_data = {
            "evaluators": [evaluator.to_dict() for evaluator in evaluators],
            "cross_page_states": list(cross_page_states.keys()),
            "static_data_types": static_data_types
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(evaluators_data, f, indent=2, ensure_ascii=False)
        
        self.logger.log_info(f"💾 Saved {len(evaluators)} evaluators to {output_path}")