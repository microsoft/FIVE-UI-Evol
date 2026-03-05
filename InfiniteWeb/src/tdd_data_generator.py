"""
TDD Data Generator Module

Two-phase data generation with dependency graph:
  Step 1: LLM field classification (entity_data / self_derived / derived)
  Step 2: Dependency graph construction + auto-promote "none" entities
  Step 3: Phase 1 - layered multi-turn generation (derived fields excluded)
  Step 4: Phase 2 - derived field backfill (pure code, no LLM)
"""

import json
import difflib
import traceback
from datetime import datetime
from typing import Dict, Any, List, Tuple, Set
from dataclasses import dataclass
from tdd_logger_module import TDDLogger
from llm_caller import call_openai_api_json_async


@dataclass
class GeneratedData:
    """Generated data for the website"""
    static_data: Dict[str, List[Dict[str, Any]]]  # Key is entity name, value is list of data items


class TDDDataGenerator:
    """
    Generates concrete data based on data models/dictionary.
    Uses a two-phase approach: layered multi-turn generation + derived field backfill.
    """

    def __init__(self, logger: TDDLogger = None, max_items: int = 20,
                 model: str = None, reasoning_effort: str = "medium"):
        self.logger = logger or TDDLogger()
        self.max_items = max_items
        self.model = model
        self.reasoning_effort = reasoning_effort

    # ─────────────────────────────────────────────
    # Public entry point (signature unchanged)
    # ─────────────────────────────────────────────

    async def generate_data(self,
                           data_models: Dict[str, Any],
                           website_type: str,
                           tasks: List[Dict[str, Any]] = None,
                           navigation_links: Dict[str, List[Dict]] = None) -> GeneratedData:
        self.logger.start_stage("Generate Data")
        self.logger.log_info(f"Generating data for {website_type} website (two-phase)...")

        if navigation_links:
            header_count = len(navigation_links.get('header_links', []))
            footer_count = len(navigation_links.get('footer_links', []))
            self.logger.log_info(f"  Using navigation links for ID consistency: {header_count} header, {footer_count} footer")

        entities = data_models.get("entities", [])
        relationships = data_models.get("relationships", [])

        # Build name->entity lookup and name->storage_key mapping
        entity_map = {}        # entity_name -> entity dict
        storage_key_map = {}   # entity_name -> storage_key
        for e in entities:
            name = e["name"]
            entity_map[name] = e
            storage_key_map[name] = e.get("storage_key", name.lower())

        # ── Step 1: LLM field classification ──
        self.logger.log_info("Step 1: Classifying fields via LLM...")
        field_classifications, backfill_script = await self._classify_fields(
            entities, relationships, website_type
        )
        self.logger.log_info(f"  Classified {len(field_classifications)} fields")

        derived_count = sum(1 for fc in field_classifications if fc["type"] == "derived")
        self.logger.log_info(f"  Found {derived_count} derived fields requiring backfill")

        # ── Step 2: Dependency graph + auto-promote + topo layers ──
        self.logger.log_info("Step 2: Building dependency graph...")
        graph = self._build_dependency_graph(relationships, field_classifications)
        promoted = self._auto_promote(entity_map, graph)
        for p_name, p_reason in promoted:
            self.logger.log_info(f"  Auto-promoted: {p_name} -> 'few' ({p_reason})")

        layers = self._topological_layers(entity_map, graph)
        for i, layer in enumerate(layers):
            self.logger.log_info(f"  Layer {i}: {', '.join(layer)}")

        # ── Step 3: Phase 1 – layered multi-turn generation ──
        self.logger.log_info("Step 3: Phase 1 - layered multi-turn generation...")
        current_date = datetime.now().strftime("%Y-%m-%d")
        all_layer_data = await self._phase_one_generate(
            layers, entity_map, storage_key_map,
            field_classifications, graph,
            website_type, current_date, tasks, navigation_links
        )

        # ── Step 4: Phase 2 – derived field backfill ──
        self.logger.log_info("Step 4: Phase 2 - derived field backfill...")
        merged = {}
        for layer_data in all_layer_data:
            merged.update(layer_data)

        merged = self._backfill_derived_fields(merged, backfill_script)

        # ── Step 4.5: Validate and fix enum values ──
        merged = self._validate_enum_values(merged, data_models)

        # Add metadata
        merged["_metadata"] = {
            "baselineDate": current_date,
            "generatedAt": datetime.now().isoformat()
        }

        # Log summary
        self.logger.log_info(f"Generated data for {len(merged)} entity types")
        for entity_type, items in merged.items():
            if isinstance(items, list):
                self.logger.log_info(f"  - {entity_type}: {len(items)} items")

        self.logger.end_stage("Generate Data")
        return GeneratedData(static_data=merged)

    # ─────────────────────────────────────────────
    # Step 1: LLM field classification
    # ─────────────────────────────────────────────

    async def _classify_fields(self,
                               entities: List[Dict],
                               relationships: List[Dict],
                               website_type: str) -> Tuple[List[Dict], str]:
        """
        Call LLM to classify each field as entity_data / self_derived / derived,
        and generate a Python backfill script for derived fields.

        Returns:
            (field_classifications, backfill_script_code)
        """
        # Build compact entity summary for prompt
        entity_summaries = []
        for e in entities:
            fields = [f"{f['name']}({f.get('type','string')})" for f in e.get("fields", [])]
            entity_summaries.append({
                "name": e["name"],
                "storage_key": e.get("storage_key", e["name"].lower()),
                "data_pre_generation_num": e.get("data_pre_generation_num", "none"),
                "fields": fields
            })

        prompt = f"""You are a data schema analyst. Analyze the entities and relationships below and classify every field of every entity.

Website type: {website_type}

ENTITIES:
{json.dumps(entity_summaries, indent=2)}

RELATIONSHIPS:
{json.dumps(relationships, indent=2)}

For each field, classify it as one of:
- "entity_data": The field holds inherent data of the entity (title, name, count, description, dates, IDs, foreign keys, etc.)
- "self_derived": The field is derived from other fields of the SAME entity (e.g., isArticle derived from contentType). These are safe for the LLM to generate together.
- "derived": The field's value depends on the EXISTENCE or VALUE of records in a DIFFERENT entity (e.g., isBookmarkedByAgent depends on whether a Bookmark record exists for this item). These will be computed by a backfill script AFTER all entities are generated.

IMPORTANT RULES:
1. Foreign key fields (like userId, postId, categoryId) are "entity_data", NOT "derived"
2. Boolean flags that indicate whether the current entity is referenced by another entity ARE "derived" (e.g., isBookmarked, isSaved, isFollowing, isInFeed)
3. Count/aggregate fields that summarize data from other entities ARE "derived" (e.g., followerCount computed from Follow records)
4. Simple status/type fields are "entity_data" even if they sound derived (e.g., status, type, role)
5. For "derived" fields, specify the source_entity and the derivation logic type
6. If there are NO derived fields, return an empty backfill script

Return JSON:
{{
  "field_classifications": [
    {{
      "entity": "EntityName",
      "field": "fieldName",
      "type": "entity_data"
    }},
    {{
      "entity": "EntityName",
      "field": "booleanFlag",
      "type": "derived",
      "source_entity": "OtherEntity",
      "derivation": "exists_check"
    }},
    {{
      "entity": "EntityName",
      "field": "selfDerivedField",
      "type": "self_derived"
    }}
  ],
  "backfill_script": "def backfill_derived_fields(data):\\n    # ... Python code ...\\n    return data"
}}

The backfill_script must be a valid Python function named `backfill_derived_fields` that:
- Takes a single `data` dict argument where keys are storage_keys (lowercase entity names) and values are lists of records
- Sets derived fields on each record based on actual data in other entity lists
- Returns the modified data dict
- Uses .get() for safe access
- If no derived fields exist, just return data unchanged"""

        messages = [{"role": "user", "content": prompt}]

        call_id = self.logger.log_api_call(
            "Classify Fields",
            prompt,
            additional_args={"website_type": website_type}
        )

        try:
            result, usage_info = await call_openai_api_json_async(
                messages, model=self.model, reasoning_effort=self.reasoning_effort
            )
            if isinstance(result, str):
                result = json.loads(result)

            self.logger.log_api_response(
                "Classify Fields", success=True, response=result,
                usage_info=usage_info, stage="Classify Fields", call_id=call_id
            )
        except Exception as e:
            self.logger.log_error(f"Field classification failed: {e}")
            self.logger.log_error(traceback.format_exc())
            self.logger.log_api_response(
                "Classify Fields", success=False, error=str(e),
                stage="Classify Fields", call_id=call_id
            )
            raise

        field_classifications = result.get("field_classifications", [])
        backfill_script = result.get("backfill_script", "def backfill_derived_fields(data):\n    return data")

        return field_classifications, backfill_script

    # ─────────────────────────────────────────────
    # Step 2a: Build dependency graph
    # ─────────────────────────────────────────────

    def _build_dependency_graph(self,
                                relationships: List[Dict],
                                field_classifications: List[Dict]) -> Dict[str, Set[str]]:
        """
        Build a directed dependency graph: entity_name -> set of entity names it depends on.
        Sources: relationship foreign keys + derived field source entities.
        """
        graph: Dict[str, Set[str]] = {}

        for rel in relationships:
            from_entity = rel["from"]
            to_entity = rel["to"]
            graph.setdefault(from_entity, set()).add(to_entity)

        for fc in field_classifications:
            if fc["type"] == "derived":
                graph.setdefault(fc["entity"], set()).add(fc["source_entity"])

        return graph

    # ─────────────────────────────────────────────
    # Step 2b: Auto-promote "none" entities
    # ─────────────────────────────────────────────

    def _auto_promote(self,
                      entity_map: Dict[str, Dict],
                      graph: Dict[str, Set[str]]) -> List[Tuple[str, str]]:
        """
        If entity A (non-none) depends on entity B (none), promote B to "few".
        Returns list of (promoted_name, reason) tuples.
        """
        promoted = []
        for entity_name, deps in graph.items():
            entity = entity_map.get(entity_name)
            if not entity or entity.get("data_pre_generation_num") == "none":
                continue

            for dep_name in deps:
                dep_entity = entity_map.get(dep_name)
                if dep_entity and dep_entity.get("data_pre_generation_num") == "none":
                    dep_entity["data_pre_generation_num"] = "few"
                    reason = f"{entity_name} depends on it"
                    dep_entity["_promoted_reason"] = reason
                    promoted.append((dep_name, reason))

        return promoted

    # ─────────────────────────────────────────────
    # Step 2c: Topological sort into layers
    # ─────────────────────────────────────────────

    def _topological_layers(self,
                            entity_map: Dict[str, Dict],
                            graph: Dict[str, Set[str]]) -> List[List[str]]:
        """
        Topological sort entities into layers. Layer 0 has no dependencies,
        layer 1 depends only on layer 0, etc.
        Only entities with data_pre_generation_num != "none" are included.
        """
        to_generate = {
            name for name, e in entity_map.items()
            if e.get("data_pre_generation_num") != "none"
        }

        layers = []
        remaining = set(to_generate)
        resolved = set()

        while remaining:
            current_layer = set()
            for entity in remaining:
                deps = graph.get(entity, set()) & to_generate
                if deps <= resolved:
                    current_layer.add(entity)

            if not current_layer:
                # Break circular dependency by picking the entity with fewest unresolved deps
                self.logger.log_warning(f"Circular dependency detected among: {remaining}")
                best = min(remaining, key=lambda e: len((graph.get(e, set()) & to_generate) - resolved))
                current_layer = {best}

            layers.append(sorted(current_layer))
            resolved |= current_layer
            remaining -= current_layer

        return layers

    # ─────────────────────────────────────────────
    # Step 3: Phase 1 – layered multi-turn generation
    # ─────────────────────────────────────────────

    async def _phase_one_generate(self,
                                  layers: List[List[str]],
                                  entity_map: Dict[str, Dict],
                                  storage_key_map: Dict[str, str],
                                  field_classifications: List[Dict],
                                  graph: Dict[str, Set[str]],
                                  website_type: str,
                                  current_date: str,
                                  tasks: List[Dict] = None,
                                  navigation_links: Dict = None) -> List[Dict]:
        """
        Multi-turn LLM conversation: one turn per layer.
        Each turn sees the system prompt + all previous turns (KV cache reuse).
        Derived fields are excluded from each layer's entity definition.
        """
        # Build derived fields lookup: (entity_name, field_name) -> True
        derived_fields: Set[Tuple[str, str]] = set()
        for fc in field_classifications:
            if fc["type"] == "derived":
                derived_fields.add((fc["entity"], fc["field"]))

        # Build system message
        system_content = self._build_system_prompt(website_type, current_date, tasks, navigation_links)
        messages = [{"role": "user", "content": system_content}]

        # We'll collect data from each layer
        all_layer_data = []

        for layer_idx, layer_entities in enumerate(layers):
            self.logger.log_info(f"  Generating layer {layer_idx}: {', '.join(layer_entities)}...")

            user_msg = self._build_layer_prompt(
                layer_idx, layer_entities, entity_map, storage_key_map,
                derived_fields, graph, len(layers)
            )

            messages.append({"role": "user", "content": user_msg})

            call_id = self.logger.log_api_call(
                f"Generate Data Layer {layer_idx}",
                user_msg,
                additional_args={"layer": layer_idx, "entities": layer_entities}
            )

            try:
                result, usage_info = await call_openai_api_json_async(
                    messages, model=self.model, reasoning_effort=self.reasoning_effort
                )
                if isinstance(result, str):
                    result = json.loads(result)

                self.logger.log_api_response(
                    f"Generate Data Layer {layer_idx}",
                    success=True, response=result,
                    usage_info=usage_info,
                    stage=f"Generate Data Layer {layer_idx}",
                    call_id=call_id
                )
            except Exception as e:
                self.logger.log_error(f"Layer {layer_idx} generation failed: {e}")
                self.logger.log_error(traceback.format_exc())
                self.logger.log_api_response(
                    f"Generate Data Layer {layer_idx}",
                    success=False, error=str(e),
                    stage=f"Generate Data Layer {layer_idx}",
                    call_id=call_id
                )
                raise

            # Append assistant response to conversation for next turn
            messages.append({"role": "assistant", "content": json.dumps(result)})

            # Collect generated data from this layer
            all_layer_data.append(result)

            # Log layer summary
            for key, items in result.items():
                if isinstance(items, list):
                    self.logger.log_info(f"    {key}: {len(items)} items")

        return all_layer_data

    def _build_system_prompt(self, website_type: str, current_date: str,
                             tasks: List[Dict] = None,
                             navigation_links: Dict = None) -> str:
        """Build the system/context prompt for the multi-turn conversation."""
        tasks_context = ""
        if tasks:
            tasks_context = f"""
USER TASKS CONTEXT:
{json.dumps(tasks, indent=2)}

TASK-BASED DATA REQUIREMENTS:
- Generate data that specifically supports the completion of the above tasks
- Ensure data quantity and content enable realistic task execution
- Create data relationships that facilitate the task workflows
- Include sufficient variety to support all task scenarios

"""

        navigation_context = ""
        if navigation_links:
            header_links = navigation_links.get('header_links', [])
            footer_links = navigation_links.get('footer_links', [])
            if header_links or footer_links:
                navigation_context = f"""
**NAVIGATION LINKS (MUST MATCH IDs EXACTLY):**
The website uses the following navigation links. When generating data, you MUST ensure the IDs used in these links match the IDs in your generated data.

Header Links:
{json.dumps(header_links, indent=2)}

Footer Links:
{json.dumps(footer_links, indent=2)}

CRITICAL: Look at the URL parameters in these links (e.g., categoryId=business, productId=123).
The ID values in these URLs MUST exist in your generated data.
For example, if a link has "categoryId=business", you MUST generate a Category with "id": "business".
Do NOT add entity-type prefixes (cat_, page_, prod_, etc.) to id values that appear in navigation URLs.

"""

        return f"""You are a data generator specializing in realistic website data.
You will generate data layer by layer. Each turn I will ask you to generate entities for one layer.
Previously generated data from earlier turns is visible in the conversation history — use it to ensure foreign key consistency.

Website Type: {website_type}
Current Date: {current_date}
Maximum Items Per Entity: {self.max_items}
{tasks_context}{navigation_context}
CRITICAL CONSTRAINTS:
1. Use the exact storage_key as JSON key in your output
2. Use EXACT field names as specified
3. Follow field types: string, number, boolean, array, datetime as specified
4. Volume guidance based on generation_type and max_items ({self.max_items}):
   - "many": Generate a substantial amount, approaching but not exceeding {self.max_items} items
   - "few": Generate a small representative set, around 20-30% of {self.max_items}
5. No extra fields beyond what is specified
6. Foreign key fields MUST reference IDs from previously generated data
7. **Enum fields**: When a field has "type": "enum" with "values", use ONLY those exact values. Do NOT invent alternatives, use different casing, or rephrase them. Store enum values as plain strings in the output.
8. **Enum format**: All enum-like string values (status, type, category, mode, etc.) MUST use lowercase_snake_case format.

**IMAGE URL REQUIREMENTS:**
Use ONLY real, working image services:
- Unsplash: https://images.unsplash.com/photo-[ID]?w=800&h=600&fit=crop&auto=format&q=80
- Picsum: https://picsum.photos/800/600?random=[1-1000]
- Placeholder.com: https://via.placeholder.com/800x600/4F46E5/FFFFFF?text=[text]

NEVER use fake URLs like cdn.example.com or placeholder.example.com

Return ONLY a JSON object with storage_keys as keys and arrays of records as values.
Do NOT wrap in "static_data" — just return the flat object."""

    def _build_layer_prompt(self,
                            layer_idx: int,
                            layer_entities: List[str],
                            entity_map: Dict[str, Dict],
                            storage_key_map: Dict[str, str],
                            derived_fields: Set[Tuple[str, str]],
                            graph: Dict[str, Set[str]],
                            total_layers: int) -> str:
        """Build the user message for a single layer turn."""
        parts = []
        if layer_idx == 0:
            parts.append(f"Generate data for Layer {layer_idx + 1}/{total_layers} (no dependencies).\n")
        else:
            parts.append(f"Generate data for Layer {layer_idx + 1}/{total_layers}.")
            parts.append("Previously generated data is in the conversation above — reference those IDs.\n")

        for entity_name in layer_entities:
            entity = entity_map[entity_name]
            storage_key = storage_key_map[entity_name]
            gen_type = entity.get("data_pre_generation_num", "few")
            promoted_reason = entity.get("_promoted_reason", "")

            # Filter out derived fields from the field list
            fields_for_generation = []
            excluded_derived = []
            for f in entity.get("fields", []):
                if (entity_name, f["name"]) in derived_fields:
                    excluded_derived.append(f["name"])
                else:
                    fields_for_generation.append(f)

            # Build field descriptions
            field_lines = []
            for f in fields_for_generation:
                desc = f.get("description", "")
                req = " (required)" if f.get("required") else ""
                pk = " (primary_key)" if f.get("primary_key") else ""
                if f.get("type") == "enum" and f.get("values"):
                    enum_vals = ", ".join(f"'{v}'" for v in f["values"])
                    field_lines.append(f"    - {f['name']}: enum [{enum_vals}]{pk}{req}")
                else:
                    field_lines.append(f"    - {f['name']}: {f.get('type', 'string')}{pk}{req} {desc}")

            parts.append(f"\n{entity_name} (storage_key: \"{storage_key}\", generation_type: \"{gen_type}\")")
            if promoted_reason:
                parts.append(f"  [Auto-promoted from 'none': {promoted_reason}]")
            if entity.get("description"):
                parts.append(f"  Description: {entity['description']}")
            parts.append("  Fields:")
            parts.extend(field_lines)

            # Add image field for visual entities if missing
            visual_entities = ['product', 'brand', 'service', 'category', 'user']
            existing_field_names = {f["name"] for f in fields_for_generation}
            if any(v in storage_key.lower() for v in visual_entities):
                if not any('image' in fn.lower() for fn in existing_field_names):
                    parts.append(f"    - image: string (auto-added for visual entity)")

            # Note dependencies
            deps = graph.get(entity_name, set())
            if deps:
                dep_list = ", ".join(sorted(deps))
                parts.append(f"  Dependencies: references data from {dep_list}")

            # Note excluded derived fields
            if excluded_derived:
                parts.append(f"  NOTE: The following fields are DERIVED and should NOT be generated (they will be computed later):")
                for df in excluded_derived:
                    parts.append(f"    - {df}")

        parts.append(f"\nReturn JSON with keys: {', '.join(storage_key_map[e] for e in layer_entities)}")

        return "\n".join(parts)

    # ─────────────────────────────────────────────
    # Step 4: Phase 2 – derived field backfill
    # ─────────────────────────────────────────────

    def _backfill_derived_fields(self, data: Dict[str, Any], backfill_script: str) -> Dict[str, Any]:
        """
        Execute the LLM-generated backfill script to populate derived fields.
        Falls back to returning data unchanged if the script fails.
        """
        if not backfill_script or backfill_script.strip() == "":
            self.logger.log_info("  No backfill script to execute")
            return data

        try:
            # Execute the backfill script in a restricted namespace
            namespace = {}
            exec(backfill_script, namespace)

            if "backfill_derived_fields" in namespace:
                data = namespace["backfill_derived_fields"](data)
                self.logger.log_info("  Backfill script executed successfully")
            else:
                self.logger.log_warning("  Backfill script missing backfill_derived_fields function")

        except Exception as e:
            self.logger.log_warning(f"  Backfill script execution failed: {e}")
            self.logger.log_warning(f"  Script:\n{backfill_script}")
            self.logger.log_warning("  Proceeding without backfill")

        return data

    def _validate_enum_values(self, static_data: Dict[str, Any], data_models: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate generated data against enum type constraints in data models.
        Auto-fix invalid values using closest match.
        """
        enum_constraints = {}
        for entity in data_models.get("entities", []):
            storage_key = entity.get("storage_key", "")
            for field in entity.get("fields", []):
                if field.get("type") == "enum":
                    values = field.get("values")
                    if values and isinstance(values, list) and len(values) > 0:
                        if storage_key not in enum_constraints:
                            enum_constraints[storage_key] = {}
                        enum_constraints[storage_key][field["name"]] = values

        if not enum_constraints:
            return static_data

        fix_count = 0
        for storage_key, field_constraints in enum_constraints.items():
            items = static_data.get(storage_key)
            if not isinstance(items, list):
                continue
            for item in items:
                for field_name, allowed in field_constraints.items():
                    value = item.get(field_name)
                    if value is None or value in allowed:
                        continue
                    matches = difflib.get_close_matches(str(value), allowed, n=1, cutoff=0.4)
                    replacement = matches[0] if matches else allowed[0]
                    self.logger.log_warning(
                        f"  Enum fix: {storage_key}.{field_name}: '{value}' -> '{replacement}'"
                    )
                    item[field_name] = replacement
                    fix_count += 1

        if fix_count > 0:
            self.logger.log_info(f"  Fixed {fix_count} enum value(s) to match enum constraints")

        return static_data
