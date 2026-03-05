"""
TDD Interface Wrapper Module
Analyzes interfaces and wraps them for user-friendly calling patterns
"""

import json
from typing import List, Dict, Any, Tuple
from llm_caller import call_openai_api_json
from tdd_logger_module import TDDLogger


class TDDInterfaceWrapper:
    """Wraps interfaces to hide system-managed parameters"""
    
    def __init__(self, logger: TDDLogger = None, model=None, reasoning_effort=None):
        """
        Initialize the interface wrapper

        Args:
            logger: Optional TDDLogger instance
            model: Model to use (None for default)
            reasoning_effort: Reasoning effort level for LLM calls
        """
        self.logger = logger or TDDLogger()
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    def wrap_interfaces(self, original_interfaces: Dict[str, Any], 
                       data_models: Dict[str, Any], 
                       website_type: str) -> Dict[str, Any]:
        """
        Analyze original interfaces and generate wrapped interfaces with state data
        
        Args:
            original_interfaces: Original interface definitions
            data_models: Existing data models
            website_type: Type of website
            
        Returns:
            Dictionary containing wrapped interfaces and state data models
        """
        self.logger.start_stage("Wrap Interfaces")
        self.logger.log_info("🔄 Analyzing interfaces for parameter wrapping...")
        
        # Prepare interface analysis prompt
        prompt = self._create_analysis_prompt(original_interfaces, data_models, website_type)
        
        # Log API call
        self.logger.log_api_call(
            "Analyze and Wrap Interfaces",
            prompt,
            additional_args={
                "model": "gpt-4",
                "temperature": 0.7
            },
            stage="Wrap Interfaces"
        )

        try:
            # Call LLM to analyze and wrap interfaces
            messages = [{"role": "user", "content": prompt}]
            response, usage_info = call_openai_api_json(
                messages,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log API response
            self.logger.log_api_response(
                "Analyze and Wrap Interfaces",
                True,
                response,
                usage_info=usage_info,
                stage="Wrap Interfaces"
            )
            
            # Parse response
            if isinstance(response, str):
                wrapper_result = json.loads(response)
            else:
                wrapper_result = response
            
            # Validate and enhance result
            validated_result = self._validate_wrapper_result(wrapper_result, original_interfaces)
            
            # Log summary
            wrapped_count = len(validated_result.get("wrapped_interfaces", []))
            state_count = len(validated_result.get("state_data_models", []))
            self.logger.log_info(f"✅ Wrapped {wrapped_count} interfaces, generated {state_count} state models")
            
            self.logger.end_stage("Wrap Interfaces")
            return validated_result
            
        except Exception as e:
            error_msg = f"Failed to wrap interfaces: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.log_api_response(
                "Analyze and Wrap Interfaces",
                False,
                error=str(e),
                stage="Wrap Interfaces"
            )
            self.logger.end_stage("Wrap Interfaces")
            raise
    
    def _create_analysis_prompt(self, original_interfaces: Dict[str, Any], 
                              data_models: Dict[str, Any], 
                              website_type: str) -> str:
        """Create the LLM prompt for interface analysis"""
        
        prompt = f"""
You are a software architect analyzing interface parameters for a {website_type}.

Your task: Identify parameters that should be hidden from user-facing interfaces and generate wrapped versions.

ORIGINAL INTERFACES:
{json.dumps(original_interfaces, indent=2)}

EXISTING DATA MODELS:
{json.dumps(data_models, indent=2)}

PARAMETER CLASSIFICATION RULES:

1. SYSTEM-MANAGED PARAMETERS (should be hidden):
   - User identity: userId, guestId, sessionId, currentUser
   - System context: cartId, deviceId, timestamp, requestId, correlationId
   - Authentication: authToken, userRole, permissions, isAuthenticated
   - Technical tracking: traceId, activityId, transactionId
   - Environment: locale, timezone, region, currency
   
2. USER-PROVIDED PARAMETERS (should remain exposed):
   - Business data: productId, quantity, rating, comment
   - User selections: selectedSize, color, filters
   - User input: searchQuery, address, paymentDetails

ANALYSIS CRITERIA:
- Ask: "Would a user type this value into a form or select it from a UI?"
- If YES → Keep as parameter (user-provided)
- If NO → Hide and manage through state (system-managed)

REQUIRED OUTPUT:

1. WRAPPED INTERFACES: User-friendly versions with hidden parameters removed
2. STATE DATA MODELS: localStorage-based entities to provide hidden parameters  
3. IMPLEMENTATION MAPPING: How wrapped interfaces call original interfaces

EXAMPLE TRANSFORMATION:
Original: addToCart(userId, guestId, productId, quantity, selectedSize)
Wrapped: addToCart(productId, quantity, selectedSize)
State Needed: UserSession with currentUserId/currentGuestId

Return JSON in this exact format:
{{
    "wrapped_interfaces": [
        {{
            "name": "addToCart",
            "description": "Add product to cart (user-facing interface)",
            "parameters": [
                {{"name": "productId", "type": "string", "required": true}},
                {{"name": "quantity", "type": "number", "required": true, "default": 1}},
                {{"name": "selectedSize", "type": "string", "required": false}}
            ],
            "returns": {{
                "type": "object",
                "properties": {{
                    "success": {{"type": "boolean"}},
                    "message": {{"type": "string"}}
                }}
            }},
            "sideEffects": ["Creates cart if needed", "Updates cart totals"],
            "relatedTasks": ["task_1"]
        }}
    ],
    "state_data_models": [
        {{
            "name": "UserSession",
            "fields": [
                {{"name": "id", "type": "string", "primary_key": true}},
                {{"name": "currentUserId", "type": "string", "foreign_key": "User.id", "required": false}},
                {{"name": "currentGuestId", "type": "string", "required": false}},
                {{"name": "activeCartId", "type": "string", "foreign_key": "Cart.id", "required": false}},
                {{"name": "isAuthenticated", "type": "boolean", "required": true}},
                {{"name": "startedAt", "type": "datetime", "required": true}},
                {{"name": "lastActiveAt", "type": "datetime", "required": true}}
            ],
            "dynamic": true,
            "description": "Manages current user session state in localStorage"
        }}
    ],
    "implementation_mapping": [
        {{
            "wrapped_function": "addToCart",
            "original_function": "addToCart",
            "parameter_mapping": {{
                "userId": "_getCurrentSession().currentUserId",
                "guestId": "_getCurrentSession().currentGuestId",
                "productId": "productId",
                "quantity": "quantity",
                "selectedSize": "selectedSize"
            }},
            "state_dependencies": ["UserSession"]
        }}
    ],
    "helper_functions": [
        {{
            "name": "_getCurrentSession",
            "description": "Get current user session from localStorage",
            "returns": "UserSession object",
            "visibility": "private"
        }}
    ]
}}

IMPORTANT:
- Focus on localStorage-based state management for web applications
- Ensure all system-managed parameters have corresponding state data
- Maintain original interface functionality while simplifying user-facing signatures
- Consider guest/anonymous user scenarios in session management
"""
        
        return prompt
    
    def _validate_wrapper_result(self, result: Dict[str, Any], 
                                original_interfaces: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and enhance the wrapper result"""
        
        # Ensure required fields exist
        if "wrapped_interfaces" not in result:
            result["wrapped_interfaces"] = []
        if "state_data_models" not in result:
            result["state_data_models"] = []
        if "implementation_mapping" not in result:
            result["implementation_mapping"] = []
        if "helper_functions" not in result:
            result["helper_functions"] = []
        
        # Add metadata
        result["metadata"] = {
            "generated_at": "system_timestamp",
            "original_interface_count": len(original_interfaces.get("interfaces", [])),
            "wrapped_interface_count": len(result["wrapped_interfaces"]),
            "state_model_count": len(result["state_data_models"])
        }
        
        # Validate state data models have required fields
        for model in result["state_data_models"]:
            if "fields" not in model:
                model["fields"] = []
            if "dynamic" not in model:
                model["dynamic"] = True  # State data is typically dynamic
            if "description" not in model:
                model["description"] = f"State model for {model.get('name', 'unknown')}"
        
        return result
    
    def generate_wrapper_summary(self, wrapper_result: Dict[str, Any]) -> str:
        """Generate a human-readable summary of the wrapping result"""
        lines = []
        lines.append("=== Interface Wrapping Summary ===\n")
        
        # Wrapped interfaces summary
        wrapped = wrapper_result.get("wrapped_interfaces", [])
        lines.append(f"Wrapped Interfaces: {len(wrapped)}")
        for interface in wrapped:
            original_params = len(interface.get("parameters", []))
            lines.append(f"  - {interface['name']}() → {original_params} parameters")
        
        # State data models summary
        state_models = wrapper_result.get("state_data_models", [])
        lines.append(f"\nState Data Models: {len(state_models)}")
        for model in state_models:
            field_count = len(model.get("fields", []))
            lines.append(f"  - {model['name']} ({field_count} fields)")
        
        # Implementation mapping summary
        mappings = wrapper_result.get("implementation_mapping", [])
        lines.append(f"\nImplementation Mappings: {len(mappings)}")
        for mapping in mappings:
            wrapped_name = mapping.get("wrapped_function", "")
            original_name = mapping.get("original_function", "")
            lines.append(f"  - {wrapped_name}() → {original_name}()")
        
        return "\n".join(lines)
    
    def wrap_additional_interfaces(self, additional_interfaces: Dict[str, Any], 
                                   existing_wrapped_result: Dict[str, Any],
                                   data_models: Dict[str, Any], 
                                   website_type: str) -> Dict[str, Any]:
        """
        Wrap additional interfaces and merge with existing wrapped result
        
        Args:
            additional_interfaces: New interfaces to wrap
            existing_wrapped_result: Existing wrapped interfaces result
            data_models: Data models for context
            website_type: Type of website
            
        Returns:
            Updated wrapped interfaces result with new interfaces merged
        """
        self.logger.log_info(f"🔄 Wrapping {len(additional_interfaces.get('interfaces', []))} additional interfaces...")
        
        try:
            # Wrap the additional interfaces
            new_wrapped_result = self.wrap_interfaces(additional_interfaces, data_models, website_type)
            
            # Merge results
            merged_result = self._merge_wrapped_results(existing_wrapped_result, new_wrapped_result)
            
            self.logger.log_info(f"✅ Successfully merged additional wrapped interfaces")
            return merged_result
            
        except Exception as e:
            error_msg = f"Failed to wrap additional interfaces: {str(e)}"
            self.logger.log_error(error_msg)
            raise Exception(error_msg)
    
    def _merge_wrapped_results(self, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge two wrapped interface results
        
        Args:
            existing: Existing wrapped result
            new: New wrapped result to merge
            
        Returns:
            Merged wrapped result
        """
        merged = existing.copy()
        
        # Merge wrapped interfaces (avoid duplicates)
        existing_wrapped = merged.get("wrapped_interfaces", [])
        new_wrapped = new.get("wrapped_interfaces", [])
        
        for new_interface in new_wrapped:
            # Check if interface already exists
            exists = any(ei['name'] == new_interface['name'] for ei in existing_wrapped)
            if not exists:
                existing_wrapped.append(new_interface)
                self.logger.log_info(f"  Added wrapped interface: {new_interface['name']}")
        
        merged["wrapped_interfaces"] = existing_wrapped
        
        # Merge state data models (avoid duplicates)
        existing_state = merged.get("state_data_models", [])
        new_state = new.get("state_data_models", [])
        
        for new_model in new_state:
            # Check if model already exists
            exists = any(em['name'] == new_model['name'] for em in existing_state)
            if not exists:
                existing_state.append(new_model)
                self.logger.log_info(f"  Added state model: {new_model['name']}")
        
        merged["state_data_models"] = existing_state
        
        # Merge implementation mappings (avoid duplicates)
        existing_mappings = merged.get("implementation_mapping", [])
        new_mappings = new.get("implementation_mapping", [])
        
        for new_mapping in new_mappings:
            # Check if mapping already exists
            exists = any(em['wrapped_function'] == new_mapping['wrapped_function'] 
                        for em in existing_mappings)
            if not exists:
                existing_mappings.append(new_mapping)
                self.logger.log_info(f"  Added mapping: {new_mapping['wrapped_function']}")
        
        merged["implementation_mapping"] = existing_mappings
        
        # Merge helper functions (avoid duplicates)
        existing_helpers = merged.get("helper_functions", [])
        new_helpers = new.get("helper_functions", [])
        
        for new_helper in new_helpers:
            # Check if helper already exists
            exists = any(eh['name'] == new_helper['name'] for eh in existing_helpers)
            if not exists:
                existing_helpers.append(new_helper)
                self.logger.log_info(f"  Added helper function: {new_helper['name']}")
        
        merged["helper_functions"] = existing_helpers
        
        # Update metadata
        merged["metadata"] = {
            "generated_at": "system_timestamp",
            "wrapped_interface_count": len(merged["wrapped_interfaces"]),
            "state_model_count": len(merged["state_data_models"])
        }
        
        return merged


if __name__ == "__main__":
    # Test the interface wrapper
    print("Testing TDD Interface Wrapper...")
    
    # Sample data for testing
    sample_interfaces = {
        "interfaces": [
            {
                "name": "addToCart",
                "parameters": [
                    {"name": "userId", "type": "string", "required": True},
                    {"name": "productId", "type": "string", "required": True},
                    {"name": "quantity", "type": "number", "required": True, "default": 1}
                ]
            }
        ]
    }
    
    sample_data_models = {
        "entities": [
            {"name": "User", "fields": [{"name": "id", "type": "string"}]},
            {"name": "Product", "fields": [{"name": "id", "type": "string"}]}
        ]
    }
    
    wrapper = TDDInterfaceWrapper()
    result = wrapper.wrap_interfaces(sample_interfaces, sample_data_models, "shopping_website")
    
    # Print summary
    summary = wrapper.generate_wrapper_summary(result)
    print(summary)