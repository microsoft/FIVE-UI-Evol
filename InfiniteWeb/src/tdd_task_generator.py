"""
TDD Task Generator
Generates user tasks from website type
"""

import json
from typing import List, Dict, Any, Optional
from llm_caller import call_openai_api_json


class TDDTaskGenerator:
    """Generates user tasks based on website type"""

    def __init__(self, logger=None, min_steps=6, max_steps=10, model=None, reasoning_effort=None):
        """
        Initialize task generator

        Args:
            logger: TDDLogger instance for logging
            min_steps: Minimum number of steps per task (default 6 for RL training)
            max_steps: Maximum number of steps per task (default 10 for focused tasks)
            model: Model to use (e.g., "gpt-4.1", "gpt-5", None for default)
            reasoning_effort: Reasoning effort level (e.g., "low", "medium", "high")
        """
        self.logger = logger
        self.min_steps = min_steps
        self.max_steps = max_steps
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    def generate_tasks(self, website_type: str, 
                      task_count_range: str = "3-5",
                      custom_task_names: List[str] = None) -> List[Dict[str, Any]]:
        """
        Generate user tasks for a website type
        
        Args:
            website_type: Type of website (e.g., "shopping_website", "social_network")
            task_count_range: Range of tasks to generate (e.g., "3-5")
            custom_task_names: Optional list of specific task names to generate
            
        Returns:
            List of task dictionaries with id, name, description, and steps
        """
        if self.logger:
            self.logger.start_stage("Generate Tasks")
            self.logger.log_info(f"Generating tasks for {website_type}")
            if custom_task_names:
                self.logger.log_info(f"Using custom task names: {custom_task_names}")
        
        try:
            # Build the prompt based on whether custom tasks are provided
            if custom_task_names and len(custom_task_names) > 0:
                prompt = self._build_custom_tasks_prompt(website_type, custom_task_names)
                prompt_type = "custom tasks"
            else:
                prompt = self._build_auto_tasks_prompt(website_type, task_count_range)
                prompt_type = "automatic generation"
            
            # Log API call and get call_id
            call_id = None
            if self.logger:
                call_id = self.logger.log_api_call(
                    "Generate User Tasks",
                    prompt,
                    additional_args={'function': 'call_openai_api_json'},
                    stage="Generate Tasks"
                )

            # Call LLM to generate tasks
            messages = [{"role": "user", "content": prompt}]
            result, usage_info = call_openai_api_json(
                messages,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log API response
            if self.logger:
                self.logger.log_api_response(
                    "Generate User Tasks",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    stage="Generate Tasks",
                    call_id=call_id
                )
            
            # Parse and validate result
            if isinstance(result, str):
                result = json.loads(result)
            
            tasks = result.get("tasks", [])
            
            # Validate tasks structure
            validated_tasks = self._validate_tasks(tasks)
            
            if self.logger:
                self.logger.log_info(f"Successfully generated {len(validated_tasks)} tasks using {prompt_type}")
                self.logger.end_stage("Generate Tasks")
            
            return validated_tasks
            
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to generate tasks: {str(e)}")
                self.logger.end_stage("Generate Tasks")
            raise
    
    def _build_custom_tasks_prompt(self, website_type: str,
                                   custom_task_names: List[str]) -> str:
        """Build prompt for custom task generation"""
        return f"""
You are a UX researcher. Generate detailed user tasks based on the following task names for a {website_type}.

Task names provided by user:
{json.dumps(custom_task_names, ensure_ascii=False, indent=2)}

IMPORTANT REQUIREMENTS:
1. This is a mock website, so tasks should NOT depend on any external services like email authentication.
2. Each task MUST contain between {self.min_steps}-{self.max_steps} detailed steps for proper complexity.
3. Tasks should be suitable for RL model training, requiring multiple decisions and interactions.
4. Ensure all tasks can be completed within the localStorage environment.
5. Tasks should NOT contain file upload steps (e.g., uploading photos/images/documents).

For each task name provided:
- Create a complete task structure with ID, name, description and detailed steps
- The name should match the provided task name BUT add SPECIFIC criteria (e.g., if given "buy shoes", make it "buy running shoes under $100 with 4+ star rating")
- Description MUST include MEASURABLE success criteria (specific prices, quantities, ratings, features)
- Steps MUST be {self.min_steps}-{self.max_steps} detailed, specific ACTIONS (not verifications)
- Include EXACT selection criteria in steps (e.g., "click the first product", "select the cheapest option", "choose the item with highest rating")

Step detail requirements (ACTIONS ONLY):
- Clear navigation actions (e.g., "Navigate to the products page")
- Specific element interactions (e.g., "Click the menu button in the top-right corner")
- Precise data entry (e.g., "Type 'electronics' in the search field")
- Selection actions (e.g., "Select 'Size Large' from the dropdown")
- Form filling (e.g., "Enter 'john@example.com' in the email field")
- Page transitions (e.g., "Click the 'Continue' button to go to next page")
- List interactions (e.g., "Click on the second item in the results list")

AVOID verification/validation/confirmation steps - focus only on actions!

Example of SPECIFIC task with clear criteria:
Original request: "Search and filter products"
Enhanced task: "Find the cheapest Dell laptop between $500-$1500 with SSD storage"
Description: "Search for laptops, filter by Dell brand and $500-$1500 price range, select the cheapest one with SSD"
Steps:
1. Navigate to the homepage
2. Click on the search bar in the header section
3. Type "laptop SSD" in the search field
4. Press Enter to execute the search
5. Click on the "Price" filter section in the left sidebar
6. Enter "500" in the minimum price field
7. Enter "1500" in the maximum price field
8. Click the "Brand" filter checkbox for "Dell"
9. Click the sort dropdown and select "Price - Low to High"
10. Click on the first product card (the cheapest Dell laptop with SSD)

Return your response in JSON format:
{{
    "tasks": [
        {{
            "id": "task_1",
            "name": "Enhanced task name with SPECIFIC criteria added to the original",
            "description": "DETAILED description with EXACT success criteria (prices, quantities, ratings, specific features to select)",
            "steps": ["Specific action 1", "Specific action 2", "... ({self.min_steps}-{self.max_steps} ACTION steps with clear selection criteria)"]
        }}
    ]
}}
"""
    
    def _build_auto_tasks_prompt(self, website_type: str,
                                 task_count_range: str) -> str:
        """Build prompt for automatic task generation"""
        return f"""
You are a UX researcher. Generate {task_count_range} realistic user tasks for a {website_type}.

IMPORTANT REQUIREMENTS:
1. This is a mock website, so tasks should NOT depend on any external services like email authentication.
2. Each task MUST contain between {self.min_steps}-{self.max_steps} detailed steps for proper complexity.
3. Tasks should be suitable for RL model training, requiring multiple decisions and interactions.
4. Tasks should NOT contain file upload steps (e.g., uploading photos/images/documents).

Each task should:
- Represent a SPECIFIC user goal with MEASURABLE success criteria
- Contain {self.min_steps}-{self.max_steps} DETAILED action steps
- Include CLEAR decision criteria (e.g., "select the cheapest option", "choose items with 4+ stars")
- Specify EXACT targets (e.g., "add 3 items under $50", "find products with free shipping")
- Use CONCRETE values and thresholds (prices, quantities, ratings, dates)
- Cover different aspects of the website functionality

Task specificity requirements:
- BAD: "Compare products and select the best one"
- GOOD: "Compare two laptops and select the one with more RAM under $1000"
- BAD: "Search for headphones and add to cart"
- GOOD: "Search for wireless headphones under $200 with 4+ star rating and add the first result to cart"
- BAD: "Filter products by price"
- GOOD: "Filter products to show only items between $25-$75 with free shipping"

Step detail requirements (FOCUS ON ACTIONS, NOT VERIFICATION):
- Specific navigation actions (e.g., "Navigate to the homepage", "Go to the Electronics category")
- Clear element interactions (e.g., "Click the search button in the header", "Click the third product in the list")
- Precise data entry (e.g., "Type 'wireless headphones' in the search field", "Enter quantity as 2")
- Selection actions (e.g., "Select 'Blue' from the color dropdown", "Choose 'Express Shipping' option")
- Page transitions (e.g., "Click on the product image to open details page", "Navigate to checkout page")
- Form interactions (e.g., "Fill in the email field with 'user@example.com'", "Enter '12345' as ZIP code")
- List/grid interactions (e.g., "Scroll down to view more products", "Click 'Load More' button")

AVOID these types of steps:
- Verification steps (e.g., "Verify the page loaded", "Confirm the cart updated")
- Validation steps (e.g., "Validate the price is correct", "Check that the item appears")
- Confirmation steps (e.g., "Ensure the button is visible", "Make sure the form is complete")
- Waiting without action (e.g., "Wait for page to load" - instead specify next action directly)

Example of SPECIFIC task with ACTION-FOCUSED steps:
Task Name: "Find and purchase the cheapest laptop with 16GB RAM under $800"
Description: "Search for laptops, filter to 16GB RAM models under $800, and add the cheapest one to cart"
Steps:
1. Navigate to the website homepage
2. Click on the search bar in the header
3. Type "laptop 16GB RAM" in the search field
4. Press Enter to execute the search
5. Click on the price filter dropdown in the sidebar
6. Enter "800" in the maximum price field
7. Click on the RAM filter and select "16GB" checkbox
8. Click on the sort dropdown menu
9. Select "Price - Low to High" from the sorting options
10. Click on the first product card in the sorted results (cheapest)

Return your response in JSON format:
{{
    "tasks": [
        {{
            "id": "task_1",
            "name": "SPECIFIC task name with CLEAR goal (e.g., 'Buy the cheapest red shirt under $30')",
            "description": "DETAILED description with MEASURABLE success criteria (e.g., 'Find red shirts, filter under $30, sort by price, add cheapest to cart')",
            "steps": ["Specific action 1", "Specific action 2", "... ({self.min_steps}-{self.max_steps} ACTION steps total, NO verifications)"]
        }}
    ]
}}
"""
    
    def _validate_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate and clean task data

        Args:
            tasks: Raw task list from LLM

        Returns:
            Validated task list
        """
        validated = []

        for i, task in enumerate(tasks):
            # Ensure required fields
            if not isinstance(task, dict):
                if self.logger:
                    self.logger.log_warning(f"Skipping invalid task at index {i}: not a dictionary")
                continue

            # Validate required fields
            if not all(key in task for key in ["name", "description", "steps"]):
                if self.logger:
                    self.logger.log_warning(f"Skipping incomplete task at index {i}")
                continue

            # Ensure ID exists
            if "id" not in task:
                task["id"] = f"task_{i+1}"

            # Validate steps is a list
            if not isinstance(task["steps"], list) or len(task["steps"]) == 0:
                if self.logger:
                    self.logger.log_warning(f"Task {task['id']} has invalid steps")
                continue

            # Validate step count for RL training complexity
            step_count = len(task["steps"])
            if step_count < self.min_steps:
                if self.logger:
                    self.logger.log_warning(
                        f"Task {task['id']} has only {step_count} steps (minimum {self.min_steps} required). "
                        f"Task may be too simple for effective RL training."
                    )
                # Still include the task but log warning for monitoring
            elif step_count > self.max_steps:
                if self.logger:
                    self.logger.log_warning(
                        f"Task {task['id']} has {step_count} steps (maximum {self.max_steps} recommended). "
                        f"Truncating to first {self.max_steps} steps."
                    )
                # Truncate to maximum steps
                task["steps"] = task["steps"][:self.max_steps]

            # Validate step content quality
            valid_steps = []
            for j, step in enumerate(task["steps"]):
                if isinstance(step, str) and len(step.strip()) > 10:  # Ensure step has meaningful content
                    valid_steps.append(step)
                else:
                    if self.logger:
                        self.logger.log_warning(
                            f"Task {task['id']}, step {j+1} is too short or invalid, skipping"
                        )

            # Update steps with only valid ones
            task["steps"] = valid_steps

            # Final check on step count after validation
            if len(task["steps"]) < self.min_steps:
                if self.logger:
                    self.logger.log_error(
                        f"Task {task['id']} has insufficient valid steps after validation "
                        f"({len(task['steps'])} < {self.min_steps}). Skipping task."
                    )
                continue

            validated.append(task)

        return validated
    
    def generate_task_summary(self, tasks: List[Dict[str, Any]]) -> str:
        """
        Generate a summary of the tasks
        
        Args:
            tasks: List of task dictionaries
            
        Returns:
            Formatted summary string
        """
        summary = f"Generated {len(tasks)} tasks:\n"
        summary += "=" * 40 + "\n"
        
        for task in tasks:
            summary += f"\n📌 {task['id']}: {task['name']}\n"
            summary += f"   {task['description']}\n"
            summary += f"   Steps: {len(task.get('steps', []))}\n"
        
        return summary