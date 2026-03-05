"""
TDD Task Rewriter Module
Rewrites tasks based on actual generated data to ensure perfect alignment
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple
from tdd_logger_module import TDDLogger
from llm_caller import call_openai_api_json_async


class TDDTaskRewriter:
    """
    Rewrites tasks to match actual generated data
    """

    def __init__(self, logger: TDDLogger = None, model: str = None, reasoning_effort: str = None):
        """
        Initialize task rewriter

        Args:
            logger: TDDLogger instance
            model: Model to use (None for default)
            reasoning_effort: Reasoning effort level for LLM calls
        """
        self.logger = logger or TDDLogger()
        self.model = model
        self.reasoning_effort = reasoning_effort

    async def rewrite_tasks(self,
                           original_tasks: List[Dict[str, Any]],
                           website_data: Dict[str, Any],
                           datadict: Dict[str, Any],
                           include_full_data: bool = True) -> List[Dict[str, Any]]:
        """
        Rewrite tasks to match actual generated data

        Args:
            original_tasks: Original tasks from generation
            website_data: Actual generated website data
            datadict: Data dictionary with entity definitions
            include_full_data: If True, pass complete data to LLM instead of samples

        Returns:
            List of rewritten tasks with specific, achievable goals
        """
        self.logger.log_info(f"📝 Starting task rewriting to match actual data... (full_data={include_full_data})")

        # Analyze data characteristics
        data_analysis = self._analyze_data(website_data)

        # Prepare context for LLM
        context = {
            "data_analysis": data_analysis,
            "available_entities": list(website_data.keys()),
            "sample_data": self._get_sample_data(website_data, include_full_data=include_full_data),
            "include_full_data": include_full_data
        }

        # Call LLM to rewrite tasks
        rewritten_tasks = await self._call_llm_for_rewriting(
            original_tasks,
            context,
            website_data
        )

        # Add time configuration to each task for sandbox time synchronization
        baseline_date = website_data.get("_metadata", {}).get("baselineDate")
        if baseline_date:
            rewritten_tasks = self._add_time_config_to_tasks(rewritten_tasks, baseline_date)
            self.logger.log_info(f"  ⏰ Added set_system_time config with baselineDate: {baseline_date}")

        self.logger.log_info(f"✅ Successfully rewrote {len(rewritten_tasks)} tasks")

        return rewritten_tasks

    def _add_time_config_to_tasks(self, tasks: List[Dict[str, Any]], baseline_date: str) -> List[Dict[str, Any]]:
        """
        Add time setting configuration to each task for OSWorld sandbox.

        This ensures the VM's system time is set to the data generation date
        before each task runs, making time-sensitive data (flights, hotels, etc.)
        always valid.

        Args:
            tasks: List of rewritten tasks
            baseline_date: Date when data was generated (YYYY-MM-DD)

        Returns:
            Tasks with set_system_time config added
        """
        for task in tasks:
            if "config" not in task:
                task["config"] = []

            # Insert time setting at the beginning of config
            task["config"].insert(0, {
                "type": "set_system_time",
                "parameters": {
                    "date": baseline_date,
                    "time": "09:00:00"
                }
            })

        return tasks

    def _analyze_data(self, website_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze characteristics of generated data

        Args:
            website_data: Generated website data

        Returns:
            Dictionary with data analysis results
        """
        analysis = {}

        # Analyze products if they exist
        if "products" in website_data and isinstance(website_data["products"], list):
            products = website_data["products"]
            if products:
                # Price analysis
                prices = [float(p.get("price", 0)) for p in products if p.get("price")]
                if prices:
                    analysis["price_range"] = {
                        "min": min(prices),
                        "max": max(prices),
                        "median": sorted(prices)[len(prices)//2]
                    }

                # Rating analysis
                ratings = [float(p.get("rating", 0)) for p in products if p.get("rating")]
                if ratings:
                    analysis["rating_range"] = {
                        "min": min(ratings),
                        "max": max(ratings),
                        "high_rated_count": sum(1 for r in ratings if r >= 4.0)
                    }

                # Feature analysis
                features = {}
                for p in products:
                    # Check for common features
                    if p.get("free_shipping"):
                        features["free_shipping_count"] = features.get("free_shipping_count", 0) + 1
                    if "wireless" in str(p).lower():
                        features["wireless_count"] = features.get("wireless_count", 0) + 1
                    if p.get("in_stock"):
                        features["in_stock_count"] = features.get("in_stock_count", 0) + 1

                if features:
                    analysis["features"] = features

                # Category/type analysis
                categories = {}
                for p in products:
                    cat = p.get("category", p.get("type", "unknown"))
                    categories[cat] = categories.get(cat, 0) + 1

                analysis["categories"] = categories
                analysis["total_products"] = len(products)

        # Analyze other entities
        for entity_type, items in website_data.items():
            if entity_type != "products" and isinstance(items, list) and items:
                analysis[f"{entity_type}_count"] = len(items)

        return analysis

    def _get_sample_data(self, website_data: Dict[str, Any], limit: int = 3, include_full_data: bool = False) -> Dict[str, Any]:
        """
        Get sample data from each entity type

        Args:
            website_data: Generated website data
            limit: Number of samples per entity (ignored if include_full_data is True)
            include_full_data: If True, return complete data instead of samples

        Returns:
            Dictionary with sample or full data
        """
        samples = {}

        for entity_type, items in website_data.items():
            if isinstance(items, list) and items:
                if include_full_data:
                    samples[entity_type] = items  # Return all items
                else:
                    samples[entity_type] = items[:limit]  # Return limited samples
            else:
                samples[entity_type] = items

        return samples

    async def _call_llm_for_rewriting(self,
                                      original_tasks: List[Dict[str, Any]],
                                      context: Dict[str, Any],
                                      website_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Call LLM to rewrite tasks based on actual data

        Args:
            original_tasks: Original tasks
            context: Data analysis context
            website_data: Full website data for reference

        Returns:
            Rewritten tasks
        """
        # Determine data label based on whether we have full data or samples
        data_label = "COMPLETE DATA (all items):" if context.get("include_full_data", False) else "SAMPLE DATA (first 3 items of each entity):"

        prompt = f"""You are rewriting tasks to create clean instructions for RL agent training.

The goal is to separate:
- **instruction**: What the user wants to do (generic, no answers revealed)
- **ground_truth**: Specific data for evaluation (IDs, names, exact values)

ORIGINAL TASKS:
{json.dumps(original_tasks, indent=2)}

DATA ANALYSIS:
{json.dumps(context["data_analysis"], indent=2)}

{data_label}
{json.dumps(context["sample_data"], indent=2)}

## CRITICAL RULES FOR INSTRUCTION FIELD

The instruction field is what an RL agent will see. It must:

1. **NEVER include internal IDs** - Users cannot see IDs like prod_001, art_002, mr_003, b1, p5
2. **NEVER include specific item names that reveal the answer** - Users should discover these
3. **ONLY include filtering criteria**: category, price range, rating threshold, quantity, date ranges
4. **Be concise** - Single sentence preferred, no redundant explanations
5. **CRITICAL: ADJUST QUANTITY based on actual data availability** - Count items in the provided data that match the task criteria. If the original task asks for N items but only M items exist, YOU MUST change the instruction quantity from N to M. Example: if task says "find 5 AI podcasts" but data only has 1 AI podcast, change instruction to "find an AI podcast" (singular). The instruction MUST be achievable with the available data - never ask for more items than exist!

## EXAMPLE TRANSFORMATIONS

| BAD instruction (reveals answer) | GOOD instruction (only criteria) |
|----------------------------------|----------------------------------|
| Add Silicone Spatula Set (p1) at $12.99, Steel Cups (p2) at $19.49 to cart | Add any 3 Kitchen items under $25 with 4+ stars to cart |
| Book Cedar Meeting Hub (mr_003) for Tomorrow Afternoon at $39 | Book any meeting room available tomorrow afternoon with free cancellation |
| Download art_001, art_002, art_003 (Climate Change articles) | Download 3 climate change articles published after 2023 |
| Compare PaceFlow 2 (comfort 4.8) vs AeroRun X (comfort 4.6) and add PaceFlow 2 | Compare two running shoes over $50 and add the one with higher comfort rating to cart |
| Favorite the F-15EX review (rev_002) with rating 4.8 | Favorite the fighter jet review with the highest user rating |
| Add 'Circuit Dreams' (b4) Hardcover Sci-Fi to wishlist | Add any hardcover Science Fiction book from 2019 to your wishlist |

## OUTPUT FORMAT

Return JSON with this structure:
{{
  "rewritten_tasks": [
    {{
      "id": "task_1",
      "instruction": "Concise task description with ONLY filtering criteria (no IDs, no specific names)",
      "ground_truth": {{
        "target_ids": ["exact_id_1", "exact_id_2"],
        "target_names": ["Exact Name 1", "Exact Name 2"],
        "expected_values": {{
          "prices": [12.99, 19.49],
          "ratings": [4.5, 4.6]
        }},
        "criteria": {{
          "category": "Kitchen",
          "max_price": 25,
          "min_rating": 4.0,
          "quantity": 3
        }}
      }}
    }}
  ]
}}

## VALIDATION CHECKLIST FOR EACH INSTRUCTION

Before finalizing each instruction, verify:
- [ ] No parenthetical IDs like (p1), (prod_003), (art_001)
- [ ] No exact product/item names that give away the answer
- [ ] No exact prices like $12.99, only thresholds like "under $25"
- [ ] No exact dates like "2025-11-28", only relative terms like "this Friday" or ranges like "after 2023"
- [ ] The instruction reads naturally as if a human user wrote it
- [ ] An agent must actually search/filter to find the right items

IMPORTANT: The instruction should be something a real user would type, NOT an answer key.
"""

        # Log API call
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Rewrite Tasks",
                prompt
            )

        try:
            result, usage_info = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log successful response
            if self.logger:
                self.logger.log_api_response(
                    "Rewrite Tasks",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    call_id=call_id
                )

            # Parse result
            if isinstance(result, str):
                result = json.loads(result)

            rewritten_tasks = result.get("rewritten_tasks", [])

            # Validate and normalize each task
            for task in rewritten_tasks:
                # Ensure ID exists
                if "id" not in task:
                    task["id"] = task.get("original_id", "task_unknown")

                # Ensure instruction exists (new format)
                if "instruction" not in task:
                    # Fallback to old format if instruction not present
                    name = task.get("name", "")
                    desc = task.get("description", "")
                    task["instruction"] = name if name else desc

                # Ensure ground_truth exists (new format)
                if "ground_truth" not in task:
                    # Migrate from old data_mapping format
                    task["ground_truth"] = task.get("data_mapping", {})

                # Keep backward compatibility: also set name/description for old consumers
                if "name" not in task:
                    task["name"] = task.get("instruction", "")
                if "description" not in task:
                    task["description"] = task.get("instruction", "")

            return rewritten_tasks

        except Exception as e:
            # Log error
            if self.logger:
                self.logger.log_api_response(
                    "Rewrite Tasks",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
                self.logger.log_error(f"Failed to rewrite tasks: {str(e)}")

            # Return original tasks on failure
            return original_tasks

    def validate_rewritten_tasks(self,
                                 rewritten_tasks: List[Dict[str, Any]],
                                 website_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate that rewritten tasks reference actual data

        Args:
            rewritten_tasks: Rewritten tasks to validate
            website_data: Website data to validate against

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        for task in rewritten_tasks:
            task_id = task.get("id", "unknown")
            data_mapping = task.get("data_mapping", {})

            # Check if referenced products exist
            if "target_product_id" in data_mapping:
                product_id = data_mapping["target_product_id"]
                if "products" in website_data:
                    product_found = any(
                        p.get("id") == product_id
                        for p in website_data["products"]
                        if isinstance(p, dict)
                    )
                    if not product_found:
                        issues.append(f"Task {task_id}: Product ID '{product_id}' not found in data")

            # Check if prices match
            if "expected_price" in data_mapping and "target_product_id" in data_mapping:
                product_id = data_mapping["target_product_id"]
                expected_price = data_mapping["expected_price"]

                if "products" in website_data:
                    for p in website_data["products"]:
                        if isinstance(p, dict) and p.get("id") == product_id:
                            actual_price = p.get("price")
                            if actual_price and float(actual_price) != float(expected_price):
                                issues.append(
                                    f"Task {task_id}: Price mismatch for {product_id} "
                                    f"(expected: {expected_price}, actual: {actual_price})"
                                )
                            break

        is_valid = len(issues) == 0
        return is_valid, issues