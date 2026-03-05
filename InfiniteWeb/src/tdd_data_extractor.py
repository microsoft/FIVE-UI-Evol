"""
TDD Data Extractor
Extracts data models from user tasks using LLM
"""

import json
from typing import List, Dict, Any
from llm_caller import call_openai_api_json


class TDDDataExtractor:
    """Extracts data models from user tasks for TDD generation"""

    def __init__(self, logger=None, model=None, reasoning_effort="medium"):
        self.logger = logger
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    def extract_data_models(self, tasks: List[Dict[str, Any]], website_type: str,
                          primary_architecture: Any = None) -> Dict[str, Any]:
        """
        Extract all data entities and fields from tasks
        
        Args:
            tasks: List of user tasks with steps
            website_type: Type of website (e.g., shopping_website)
            primary_architecture: Primary architecture design (optional)
            
        Returns:
            Dictionary containing entities with fields and relationships
        """
        # Prepare architecture context if provided
        architecture_context = ""
        if primary_architecture:
            # Extract all fields from primary architecture
            if hasattr(primary_architecture, '__dict__'):
                arch_dict = {k: v for k, v in primary_architecture.__dict__.items() if v}
            elif isinstance(primary_architecture, dict):
                arch_dict = primary_architecture
            else:
                arch_dict = {}

            if arch_dict:
                architecture_context = f"""
        Website Primary Architecture (includes pages, header_links, footer_links):
        {json.dumps(arch_dict, indent=2, ensure_ascii=False)}
        """
        
        prompt = f"""
        You are a data architect. Analyze the user tasks and extract ALL data entities and fields needed.
        
        Website Type: {website_type}
        User Tasks: {json.dumps(tasks, indent=2)}
        {architecture_context}
        
        For each task, identify:
        1. Core entities directly mentioned (e.g., Product, Cart)
        2. Supporting entities needed for functionality  
        3. All necessary fields for each entity
        4. Relationships between entities
        
        IMPORTANT REQUIREMENTS:
        - This is for SINGLE-USER agent training only - NO multi-user support needed
        - DO NOT include User entity or userId/sessionId fields
        - DO NOT include authentication-related entities
        - Extract ALL entities needed, not just the minimal set
        - Include all fields necessary for the tasks
        - Specify data types for each field
        - Supported field types: string, number, boolean, array, datetime, enum
        - Identify primary keys (but NO foreign keys to User)
        - Specify data_pre_generation_num for each entity: "many", "few", or "none"
          - "many": Generate 10-20 items (for catalog entities like Product, Category)
          - "few": Generate 3-5 items (for limited entities like Brand, Department)
          - "none": No pre-generation needed (for runtime entities like Cart, Order)
          - NOTE: When you decide data_pre_generation_num, consider that every task should be executable separately with pre-generated data(e.g. "Finish an assignment need enrolled courses, which need to be pre-generated")
        - Provide storage_key for localStorage (lowercase plural form)
        - CRITICAL - Use "type": "enum" for Fixed-Choice Fields:
          For any field whose valid values are a CLOSED set defined at design time
          (users cannot add new values at runtime):
          - Use "type": "enum" (NOT "type": "string") and include "values" array listing ALL valid options
          - Enum values MUST use lowercase_snake_case format (no hyphens, no Title Case, no UPPER_CASE)
          - Check ALL URL parameter values in header_links and footer_links above.
            (e.g., categoryId=movies, content_type=movies), the enum values MUST include that exact value as-is.
            Do NOT change format (e.g., keep "movies" not "movie", keep "home_garden" not "home-garden")
          - Typical enum fields: status, type, priority, visibility, mode, frequency,
            paymentMethod, locationType, contentType, httpMethod, sampleContext
          - Do NOT use enum for fields where users may create new values at runtime
            (e.g., category names users can add, free-form tags, custom labels).
            Use "type": "string" for those instead.

        Return JSON in this format:
        {{
            "entities": [
                {{
                    "name": "Product",
                    "storage_key": "products",
                    "fields": [
                        {{"name": "id", "type": "string", "primary_key": true}},
                        {{"name": "name", "type": "string", "required": true}},
                        {{"name": "price", "type": "number", "required": true}},
                        {{"name": "status", "type": "enum", "required": true, "values": ["active", "draft", "archived"]}},
                        {{"name": "image", "type": "string", "required": false}},
                        {{"name": "description", "type": "string", "required": false}}
                    ],
                    "data_pre_generation_num": "many",
                    "description": "Product available for purchase"
                }},
                {{
                    "name": "Cart",
                    "storage_key": "cart",
                    "fields": [
                        {{"name": "id", "type": "string", "primary_key": true}},
                        {{"name": "items", "type": "array", "description": "Array of cart items"}},
                        {{"name": "createdAt", "type": "datetime"}}
                    ],
                    "data_pre_generation_num": "none",
                    "description": "Shopping cart (single cart for the agent)"
                }}
            ],
            "relationships": [
                {{
                    "from": "CartItem",
                    "to": "Product",
                    "type": "belongs_to",
                    "field": "productId"
                }},
                {{
                    "from": "CartItem",
                    "to": "Cart",
                    "type": "belongs_to",
                    "field": "cartId"
                }}
            ]
        }}
        """
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            self.logger.log_info("Extracting data models from tasks...")
            call_id = self.logger.log_api_call(
                "Extract Data Models",
                prompt,
                additional_args={"website_type": website_type}
            )

        try:
            response, usage = call_openai_api_json(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Parse JSON response
            if isinstance(response, str):
                data_models = json.loads(response)
            else:
                data_models = response
            
            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    "Extract Data Models",
                    success=True,
                    response=data_models,
                    usage_info=usage,
                    call_id=call_id
                )
                self.logger.log_info(f"Successfully extracted {len(data_models.get('entities', []))} entities")
            
            return data_models
            
        except Exception as e:
            import traceback
            if self.logger:
                self.logger.log_error(f"Failed to extract data models: {str(e)}")
                self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
                # Log failed API response
                self.logger.log_api_response(
                    "Extract Data Models",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            raise
    
    def validate_data_models(self, data_models: Dict[str, Any]) -> bool:
        """
        Validate extracted data models for completeness
        
        Args:
            data_models: Extracted data models
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # Check required structure
            if not isinstance(data_models, dict):
                if self.logger:
                    self.logger.log_error(f"Data models is not a dict: {type(data_models)}")
                return False
            
            if 'entities' not in data_models:
                if self.logger:
                    self.logger.log_error(f"Missing 'entities' key. Keys found: {list(data_models.keys())}")
                return False
            
            # Check each entity
            for i, entity in enumerate(data_models['entities']):
                if not all(k in entity for k in ['name', 'fields', 'storage_key', 'data_pre_generation_num']):
                    missing = [k for k in ['name', 'fields', 'storage_key', 'data_pre_generation_num'] if k not in entity]
                    if self.logger:
                        self.logger.log_error(f"Entity {i} missing required keys: {missing}. Keys found: {list(entity.keys())}")
                    return False
                
                # Validate data_pre_generation_num value
                if entity.get('data_pre_generation_num') not in ['many', 'few', 'none']:
                    if self.logger:
                        self.logger.log_error(f"Entity '{entity['name']}' has invalid data_pre_generation_num: {entity.get('data_pre_generation_num')}. Must be 'many', 'few', or 'none'")
                    return False
                
                # Check fields
                for j, field in enumerate(entity['fields']):
                    if not all(k in field for k in ['name', 'type']):
                        missing = [k for k in ['name', 'type'] if k not in field]
                        if self.logger:
                            self.logger.log_error(f"Entity '{entity['name']}' field {j} missing required keys: {missing}. Keys found: {list(field.keys())}")
                        return False
            
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Exception during validation: {str(e)}")
            return False
    
    def generate_schema_summary(self, data_models: Dict[str, Any]) -> str:
        """
        Generate a human-readable summary of the data schema
        
        Args:
            data_models: Extracted data models
            
        Returns:
            Formatted string summary
        """
        summary = []
        summary.append("=== Data Schema Summary ===\n")
        
        # Entities
        summary.append("Entities:")
        for entity in data_models.get('entities', []):
            gen_num = entity.get('data_pre_generation_num', 'none')
            gen_tag = f" [{gen_num.upper()}]" if gen_num else ""
            storage_key = entity.get('storage_key', 'N/A')
            summary.append(f"  - {entity['name']} (storage: {storage_key}, generation: {gen_num}){gen_tag}")
            for field in entity['fields']:
                field_type = field['type']
                required_tag = " *" if field.get('required', False) else ""
                pk_tag = " [PK]" if field.get('primary_key', False) else ""
                fk_tag = f" [FK→{field['foreign_key']}]" if field.get('foreign_key') else ""
                summary.append(f"    • {field['name']}: {field_type}{required_tag}{pk_tag}{fk_tag}")
        
        # Relationships
        if 'relationships' in data_models and data_models['relationships']:
            summary.append("\nRelationships:")
            for rel in data_models['relationships']:
                summary.append(f"  - {rel['from']} {rel['type']} {rel['to']} (via {rel.get('field', 'N/A')})")
        
        return "\n".join(summary)
