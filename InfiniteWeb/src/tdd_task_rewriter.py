"""
TDD Task Rewriter Module
Rewrites tasks based on actual generated data to ensure perfect alignment
"""

import json
import re
from typing import List, Dict, Any, Tuple
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
            "include_full_data": include_full_data,
            "datadict": datadict
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

        # Build datadict section if available
        datadict_section = ""
        if context.get("datadict"):
            datadict_section = f"""
DATA MODEL DEFINITIONS:
{json.dumps(context["datadict"], indent=2)}

Use this to understand:
- Which entities have data_pre_generation_num="none" (runtime-created, likely involve form input)
- Field types and valid enum values
- Relationships between entities
"""

        prompt = f"""You are rewriting tasks to create clean instructions for RL agent training.

The goal is to separate:
- **instruction**: What the user sees — criteria for discovery, plus any values the user must type
- **ground_truth**: Specific data for evaluation, split into discovery_targets and given_inputs

ORIGINAL TASKS:
{json.dumps(original_tasks, indent=2)}

DATA ANALYSIS:
{json.dumps(context["data_analysis"], indent=2)}

{data_label}
{json.dumps(context["sample_data"], indent=2)}
{datadict_section}
## VALUE CLASSIFICATION (CRITICAL — Read This First)

Every concrete value in the original task steps belongs to one of TWO types.
You MUST classify each value correctly before writing the instruction.

### Type D — Discovery Values (the "answer" the agent must find)

Values the agent discovers by browsing, searching, or filtering the website.
These MUST NOT appear in the instruction — replace them with filtering criteria.

Examples of discovery values:
- Product/item names the agent should find: "Silicone Spatula Set", "Cedar Meeting Hub"
- Internal IDs: prod_001, art_002, mr_003, b1, p5
- Specific prices of items: $12.99 (the agent finds this by browsing)
- Entity names found by sorting/filtering: "Laura Wilson" (highest-rated attorney)
- Specific results the agent should discover through interaction

### Type G — Given Values (arbitrary data the agent must type into forms)

Values the agent must TYPE into a form field. The agent cannot guess or discover these
from the website — they are arbitrary inputs. These MUST appear in the instruction.

How to identify: the original step says "enter/type/input/fill in '...' in the ... field".

Examples of given values:
- Registration/contact info: "Jordan Lee", "jordan.lee@example.com"
- Review/comment text: "The handmade pasta was exceptional"
- Names for user-created content: playlist named "Evening Jazz", project titled "Q2 Report"
- Message/email body: "I would like to schedule a viewing this weekend"
- Bio/profile text: "I am a community organizer focused on digital rights"
- Dates the user freely CHOOSES for an action: booking date "March 15", appointment time "2:00 PM"

NOT given values (these are discovery criteria even if typed into a search/filter field):
- Search terms describing what to find: "running shoes" in a search bar → Type D criterion
- Filter values selecting from existing categories: "Italian" in a cuisine dropdown → Type D criterion
- Dates describing when something EXISTS on the site: "after 2023" for publication date → Type D criterion

### Classification test
Ask: "Can the agent figure out this value by looking at the website data?"
- YES → Type D (discovery) — strip from instruction, put in discovery_targets
- NO  → Type G (given) — KEEP in instruction, put in given_inputs

## ADDITIONAL RULES

1. **NEVER include internal IDs** — Users cannot see IDs like prod_001, art_002. This applies to both Type D and Type G values.
2. **Be concise** — Single sentence preferred, no redundant explanations.
3. **ADJUST QUANTITY based on actual data availability** — Count items in the provided data that match the task criteria. If the original task asks for N items but only M items exist, YOU MUST change the quantity to M. The instruction MUST be achievable with the available data.
4. **Discovery dates** — For discovery values, use relative terms ("next month", "after 2023") instead of exact dates. For given values (dates the user types into a form), keep the exact date in the instruction.
5. **All given_inputs values MUST appear verbatim in the instruction** — If a value is in given_inputs, the instruction MUST contain it so the agent knows what to type.
6. **All ground_truth values MUST come from the original task steps or the provided data** — NEVER invent values that appear in neither the steps nor the data (no made-up timezones, booking IDs, or other fabricated values).

## EXAMPLE TRANSFORMATIONS

### Discovery values → Strip and replace with criteria
| BAD (reveals answer) | GOOD (criteria only) |
|---|---|
| Add Silicone Spatula Set (p1) at $12.99, Steel Cups (p2) at $19.49 to cart | Add any 3 Kitchen items under $25 with 4+ stars to cart |
| Book Cedar Meeting Hub (mr_003) for Tomorrow Afternoon at $39 | Book any meeting room available tomorrow afternoon with free cancellation |
| Compare PaceFlow 2 (comfort 4.8) vs AeroRun X (comfort 4.6) and add PaceFlow 2 | Compare two running shoes over $50 and add the one with higher comfort rating to cart |
| Favorite the F-15EX review (rev_002) with rating 4.8 | Favorite the fighter jet review with the highest user rating |

### Given values → KEEP in instruction
| BAD (strips given values) | GOOD (preserves given values) |
|---|---|
| Register for the digital security training | Register for the digital security training scheduled for next month using name 'Jordan Lee' and email 'jordan.lee@example.com' |
| Write a review for the top-rated restaurant | Write a 5-star review for the top-rated Italian restaurant with the comment 'The handmade pasta was exceptional' |
| Create a new playlist and add 3 jazz songs | Create a playlist named 'Evening Jazz' and add 3 jazz songs with 4+ star rating |
| Send a message to the property manager about the apartment | Send a message to the manager of the most affordable downtown apartment saying 'I would like to schedule a viewing this weekend' |

## OUTPUT FORMAT

Return JSON with this structure:
{{
  "rewritten_tasks": [
    {{
      "id": "task_1",
      "instruction": "Concise task description. Discovery values replaced with criteria. Given values (form inputs) included verbatim.",
      "ground_truth": {{
        "discovery_targets": {{
          "target_ids": ["exact_id_1", "exact_id_2"],
          "target_names": ["Exact Name 1", "Exact Name 2"],
          "criteria": {{
            "category": "Kitchen",
            "max_price": 25,
            "min_rating": 4.0,
            "quantity": 3
          }}
        }},
        "given_inputs": {{
          "registration_name": "Jordan Lee",
          "registration_email": "jordan.lee@example.com"
        }}
      }}
    }}
  ]
}}

Notes on the schema:
- **discovery_targets**: Items the agent must find. target_ids/target_names are for evaluator reference. criteria describes the filtering logic. Leave as empty object {{}} if the task has no discovery component (e.g., pure form-filling).
- **given_inputs**: Values the agent must type. Every value here MUST appear in the instruction. Use descriptive keys (e.g., registration_name, review_text, playlist_name, message_body). Leave as empty object {{}} if the task has no form inputs.

## VALIDATION CHECKLIST

Before finalizing each instruction, verify:
- [ ] No internal IDs like (p1), (prod_003), (art_001)
- [ ] No discovery values (item names, prices) that the agent should find by browsing
- [ ] Discovery values replaced with criteria (category, price range, rating threshold)
- [ ] ALL given values (form inputs from original steps) ARE present in the instruction
- [ ] Every value in given_inputs appears verbatim in the instruction
- [ ] Quantity adjusted to match actual data availability
- [ ] No fabricated values — everything in ground_truth comes from steps or data
- [ ] The instruction reads naturally as a real user request
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

                # Ensure ground_truth exists with new schema
                if "ground_truth" not in task:
                    task["ground_truth"] = task.get("data_mapping", {})

                gt = task["ground_truth"]

                # Migrate flat ground_truth to new discovery_targets/given_inputs schema
                if "discovery_targets" not in gt and "given_inputs" not in gt:
                    # Old-format ground_truth — wrap into discovery_targets
                    task["ground_truth"] = {
                        "discovery_targets": {
                            k: v for k, v in gt.items()
                        },
                        "given_inputs": {}
                    }

                # Ensure both sub-keys exist
                task["ground_truth"].setdefault("discovery_targets", {})
                task["ground_truth"].setdefault("given_inputs", {})

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
        Validate that rewritten tasks have correct structure, reference actual data,
        and given_inputs values appear in instruction.

        Args:
            rewritten_tasks: Rewritten tasks to validate
            website_data: Website data to validate against

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        entity_index = self._build_entity_index(website_data)

        for task in rewritten_tasks:
            task_id = task.get("id", "unknown")
            instruction = task.get("instruction", "")
            ground_truth = task.get("ground_truth", {})

            if not isinstance(instruction, str) or not instruction.strip():
                issues.append(f"Task {task_id}: Missing or empty instruction")

            if not isinstance(ground_truth, dict):
                issues.append(f"Task {task_id}: ground_truth must be an object")
                continue

            # Validate discovery_targets: check that target_ids reference real data
            discovery = ground_truth.get("discovery_targets", {})
            target_ids = discovery.get("target_ids", [])
            for tid in target_ids:
                if str(tid) not in entity_index:
                    issues.append(f"Task {task_id}: target_id '{tid}' not found in website data")

            # Validate given_inputs: each value must appear in the instruction
            given_inputs = ground_truth.get("given_inputs", {})
            for key, value in given_inputs.items():
                if isinstance(value, str) and value not in instruction:
                    issues.append(
                        f"Task {task_id}: given_input '{key}' value '{value}' "
                        f"not found in instruction"
                    )

        is_valid = len(issues) == 0
        return is_valid, issues

    def _build_entity_index(self, website_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Build a lookup from entity id to entity object across all list-based entities."""
        entity_index = {}
        for items in website_data.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    entity_index[str(item["id"])] = item
        return entity_index
