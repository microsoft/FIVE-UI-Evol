import os
import base64
import mimetypes
import random
import threading
import warnings
import platform
from openai import AzureOpenAI, AsyncAzureOpenAI
from azure.identity import DefaultAzureCredential, AzureCliCredential, get_bearer_token_provider
from tdd_token_tracker import get_token_tracker

# ============================================================================
# Constants Configuration
# ============================================================================

# Reasoning models - maintain in one place only
REASONING_MODELS = frozenset([
    "o3", "gpt-5", "gpt-5-codex", "gpt-5.1", "gpt-5.1-codex", "gpt-5.2", "gpt-5.2-codex", "gpt-5-mini", "o4-mini"
])

# Model-specific configurations
MODEL_CONFIG = {
    # GPT-4 系列
    "gpt-4.1": {"max_output_tokens": 32768},

    # GPT-5 系列
    "gpt-5": {"max_output_tokens": 131072, "default_reasoning_effort": "medium"},
    "gpt-5-codex": {"max_output_tokens": 128000, "default_reasoning_effort": "medium"},
    "gpt-5.1": {"max_output_tokens": 128000, "default_reasoning_effort": "medium"},
    "gpt-5.1-codex": {"max_output_tokens": 128000, "default_reasoning_effort": "medium"},
    "gpt-5.2": {"max_output_tokens": 128000, "default_reasoning_effort": "medium"},
    "gpt-5.2-codex": {"max_output_tokens": 128000, "default_reasoning_effort": "medium"},
    "gpt-5-mini": {"max_output_tokens": 65536, "default_reasoning_effort": "medium"},

    # O 系列
    "o3": {"max_output_tokens": 65536, "default_reasoning_effort": "medium"},
    "o4-mini": {"max_output_tokens": 65536, "default_reasoning_effort": "medium"},
}

# Default values
DEFAULT_MAX_TOKENS = 32768  # 未知模型的回退值
DEFAULT_MAX_RETRIES = 5
DEFAULT_REASONING_EFFORT = "minimal"

# ============================================================================
# Endpoint Configuration
# ============================================================================

# Default endpoints list - can be overridden
DEFAULT_ENDPOINTS = []
DEFAULT_DEPLOYMENT = "gpt-4.1"
DEFAULT_API_VERSION = "2025-03-01-preview"  # Updated for Responses API support

# Load balancing strategies
LOAD_BALANCE_ROUND_ROBIN = "round_robin"
LOAD_BALANCE_RANDOM = "random"

# Global variables for configuration
current_endpoints = DEFAULT_ENDPOINTS.copy()
current_deployment = DEFAULT_DEPLOYMENT
current_api_version = DEFAULT_API_VERSION
load_balance_strategy = LOAD_BALANCE_ROUND_ROBIN
round_robin_index = 0
round_robin_lock = threading.Lock()

# Client pools for each endpoint
client_pool = {}
async_client_pool = {}

def get_credential():
    """Get appropriate credential based on operating system"""
    if platform.system() == "Windows":
        return DefaultAzureCredential()
    else:
        # Linux and other Unix-like systems
        return AzureCliCredential()

def configure_load_balancing(endpoints=None, strategy=None, deployment=None, api_version=None):
    """Configure load balancing settings"""
    global current_endpoints, load_balance_strategy, round_robin_index, current_deployment, current_api_version
    
    if endpoints:
        current_endpoints = endpoints.copy()
        # Reset round robin index when endpoints change
        with round_robin_lock:
            round_robin_index = 0
        # Clear existing client pools since endpoints changed
        client_pool.clear()
        async_client_pool.clear()
    
    if strategy:
        load_balance_strategy = strategy
        
    if deployment:
        current_deployment = deployment
        
    if api_version:
        current_api_version = api_version

def get_next_endpoint():
    """Get next endpoint based on load balancing strategy"""
    global round_robin_index
    
    if not current_endpoints:
        raise ValueError("No endpoints configured")
    
    if load_balance_strategy == LOAD_BALANCE_RANDOM:
        return random.choice(current_endpoints)
    elif load_balance_strategy == LOAD_BALANCE_ROUND_ROBIN:
        with round_robin_lock:
            endpoint = current_endpoints[round_robin_index]
            round_robin_index = (round_robin_index + 1) % len(current_endpoints)
            return endpoint
    else:
        raise ValueError(f"Unknown load balance strategy: {load_balance_strategy}")

def get_client_for_endpoint(endpoint):
    """Get or create client for specific endpoint"""
    if endpoint not in client_pool:
        token_provider = get_bearer_token_provider(
            get_credential(),
            "https://cognitiveservices.azure.com/.default"
        )
        
        client_pool[endpoint] = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=current_api_version,
            timeout=600,  # 10 minutes timeout for API calls
            max_retries=0
        )

    print(f"Client created for endpoint: {endpoint}")

    return client_pool[endpoint]

def get_async_client_for_endpoint(endpoint):
    """Get or create async client for specific endpoint"""
    if endpoint not in async_client_pool:
        token_provider = get_bearer_token_provider(
            get_credential(),
            "https://cognitiveservices.azure.com/.default"
        )
        
        async_client_pool[endpoint] = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=current_api_version,
            timeout=600,  # 10 minutes timeout for API calls  
            max_retries=0
        )
    
    print(f"Client created for endpoint: {endpoint}")
    
    return async_client_pool[endpoint]

def initialize_client(endpoint=None, deployment=None, api_version=None, endpoints=None, strategy=None):
    """Initialize load balancing configuration.

    .. deprecated::
        Use :func:`configure_load_balancing` instead.
    """
    warnings.warn(
        "initialize_client is deprecated, use configure_load_balancing instead",
        DeprecationWarning,
        stacklevel=2
    )
    global current_deployment, current_api_version

    # Update global deployment and api version
    if deployment:
        current_deployment = deployment
    if api_version:
        current_api_version = api_version

    # If endpoints provided, use load balancing
    if endpoints:
        configure_load_balancing(endpoints=endpoints, strategy=strategy)
    elif endpoint:
        # Single endpoint - convert to endpoints list
        configure_load_balancing(endpoints=[endpoint], strategy="round_robin")

def get_client():
    """Get a client using load balancing"""
    endpoint = get_next_endpoint()
    return get_client_for_endpoint(endpoint)

def initialize_async_client(endpoint=None, deployment=None, api_version=None, endpoints=None, strategy=None):
    """Initialize async load balancing configuration.

    .. deprecated::
        Use :func:`configure_load_balancing` instead.
    """
    warnings.warn(
        "initialize_async_client is deprecated, use configure_load_balancing instead",
        DeprecationWarning,
        stacklevel=2
    )
    # Same logic as initialize_client since they both configure the same global settings
    # Note: initialize_client will NOT emit another warning since we already warned here
    global current_deployment, current_api_version

    if deployment:
        current_deployment = deployment
    if api_version:
        current_api_version = api_version

    if endpoints:
        configure_load_balancing(endpoints=endpoints, strategy=strategy)
    elif endpoint:
        configure_load_balancing(endpoints=[endpoint], strategy="round_robin")

def get_async_client():
    """Get an async client using load balancing"""
    endpoint = get_next_endpoint()
    return get_async_client_for_endpoint(endpoint)

def encode_image(image_path):
    """Encode image to base64 for OpenAI API"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file {image_path} not found")
    
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    
    # Determine MIME type
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith('image/'):
        mime_type = 'image/png'  # Default to PNG
    
    return f"data:{mime_type};base64,{img_b64}"

# ============================================================================
# Internal Helper Functions
# ============================================================================

def _get_effective_params(deployment, max_tokens, reasoning_effort):
    """根据模型自动获取 max_tokens，忽略传入的 max_tokens 参数。

    Args:
        deployment: The model deployment name
        max_tokens: The requested max_tokens (ignored, kept for API compatibility)
        reasoning_effort: The requested reasoning_effort

    Returns:
        Tuple of (effective_max_tokens, effective_reasoning_effort)
    """
    effective_reasoning_effort = reasoning_effort

    # 始终使用模型的最大输出限制
    if deployment in MODEL_CONFIG:
        config = MODEL_CONFIG[deployment]
        effective_max_tokens = config.get("max_output_tokens", DEFAULT_MAX_TOKENS)
        if reasoning_effort == DEFAULT_REASONING_EFFORT and "default_reasoning_effort" in config:
            effective_reasoning_effort = config["default_reasoning_effort"]
    else:
        effective_max_tokens = DEFAULT_MAX_TOKENS

    return effective_max_tokens, effective_reasoning_effort

def _build_response_params(deployment, messages, max_tokens, reasoning_effort, response_format=None):
    """Build API request parameters dictionary.

    Args:
        deployment: The model deployment name
        messages: The messages to send
        max_tokens: Maximum tokens for completion
        reasoning_effort: Reasoning effort level
        response_format: Optional response format

    Returns:
        Dictionary of API parameters
    """
    effective_max_tokens, effective_reasoning_effort = _get_effective_params(
        deployment, max_tokens, reasoning_effort
    )

    response_params = {
        "model": deployment,
        "input": messages,
        "max_output_tokens": effective_max_tokens,
        "store": False
    }

    # Add reasoning parameter for reasoning models
    if deployment in REASONING_MODELS:
        response_params["reasoning"] = {"effort": effective_reasoning_effort}

    # Add text format if specified
    if response_format:
        response_params["text"] = {"format": response_format}

    return response_params

def _process_response(response):
    """Process API response and extract content and usage info.

    Args:
        response: The API response object

    Returns:
        Tuple of (reply_text, usage_info_dict)
    """
    reply = response.output_text
    usage_info = {
        'total_tokens': response.usage.total_tokens,
        'prompt_tokens': response.usage.input_tokens,
        'completion_tokens': response.usage.output_tokens
    }

    print("Usage Info:")
    for key, value in usage_info.items():
        print(f"  {key}: {value}")

    return reply, usage_info

def _track_token_usage(deployment, usage_info, stage):
    """Track token usage with the token tracker.

    Args:
        deployment: The model deployment name
        usage_info: Dictionary with token usage info
        stage: Optional stage name for tracking
    """
    try:
        tracker = get_token_tracker()
        tracker.record_usage(
            model=deployment,
            input_tokens=usage_info['prompt_tokens'],
            output_tokens=usage_info['completion_tokens'],
            total_tokens=usage_info['total_tokens'],
            stage=stage
        )
    except Exception as e:
        print(f"Warning: Failed to record token usage: {e}")

def _execute_with_retry(client, response_params, deployment, max_retries, stage):
    """Execute API call with retry mechanism (synchronous).

    Args:
        client: The OpenAI client
        response_params: The API request parameters
        deployment: The model deployment name
        max_retries: Number of retry attempts
        stage: Optional stage name for token tracking

    Returns:
        Tuple of (reply, usage_info) or (None, None) on failure
    """
    max_tokens = response_params.get("max_output_tokens", DEFAULT_MAX_TOKENS)
    reasoning_effort = response_params.get("reasoning", {}).get("effort", DEFAULT_REASONING_EFFORT)

    print(f"Model: {deployment}, Max Tokens: {max_tokens}, Reasoning Effort: {reasoning_effort}")

    for attempt in range(max_retries):
        try:
            response = client.responses.create(**response_params)
            reply, usage_info = _process_response(response)
            _track_token_usage(deployment, usage_info, stage)

            # Check if response is valid
            if not reply or reply.strip() == "":
                print(f"Warning: Empty response received on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
                else:
                    print("All attempts resulted in empty responses")
                    return None, None

            return reply, usage_info

        except Exception as e:
            print(f"OpenAI API Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {2 ** attempt} seconds...")
            else:
                print(f"All {max_retries} attempts failed")
                return None, None

    return None, None

async def _execute_with_retry_async(client, response_params, deployment, max_retries, stage, endpoint_label=None):
    """Execute API call with retry mechanism (asynchronous).

    Args:
        client: The async OpenAI client
        response_params: The API request parameters
        deployment: The model deployment name
        max_retries: Number of retry attempts
        stage: Optional stage name for token tracking
        endpoint_label: Optional endpoint label for error messages

    Returns:
        Tuple of (reply, usage_info) or (None, None) on failure
    """
    max_tokens = response_params.get("max_output_tokens", DEFAULT_MAX_TOKENS)
    reasoning_effort = response_params.get("reasoning", {}).get("effort", DEFAULT_REASONING_EFFORT)

    if endpoint_label is None:
        print(f"Model: {deployment}, Max Tokens: {max_tokens}, Reasoning Effort: {reasoning_effort}")

    for attempt in range(max_retries):
        try:
            response = await client.responses.create(**response_params)
            reply, usage_info = _process_response(response)

            if stage:
                _track_token_usage(deployment, usage_info, stage)

            # Check if response is valid
            if not reply or reply.strip() == "":
                if endpoint_label is None:
                    print(f"Warning: Empty response received on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    continue
                else:
                    if endpoint_label is None:
                        print("All attempts resulted in empty responses")
                    return None, None

            return reply, usage_info

        except Exception as e:
            error_prefix = f"[{endpoint_label}] " if endpoint_label else ""
            print(f"{error_prefix}OpenAI API Error on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                if endpoint_label is None:
                    print(f"Retrying in {2 ** attempt} seconds...")
                continue
            else:
                if endpoint_label is None:
                    print(f"All {max_retries} attempts failed")
                return None, None

    return None, None

# ============================================================================
# Public API Functions - Synchronous
# ============================================================================

def call_openai_api(messages, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, response_format=None, reasoning_effort=DEFAULT_REASONING_EFFORT, stage=None, model=None):
    """Call Azure OpenAI API with retry mechanism.

    Args:
        messages: The messages to send to the API
        max_tokens: Maximum tokens for completion
        max_retries: Number of retry attempts
        response_format: Optional response format (e.g., {"type": "json_object"})
        reasoning_effort: Reasoning effort level for supported models
        stage: Optional stage name for token tracking
        model: Optional model override

    Returns:
        Tuple of (reply, usage_info) or (None, None) on failure
    """
    client = get_client()
    deployment = model if model is not None else current_deployment
    response_params = _build_response_params(deployment, messages, max_tokens, reasoning_effort, response_format)
    return _execute_with_retry(client, response_params, deployment, max_retries, stage)

def call_openai_with_image(prompt, image_path, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, response_format=None, reasoning_effort=DEFAULT_REASONING_EFFORT, stage=None):
    """Call OpenAI API with text prompt and image."""
    try:
        image_url = encode_image(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url}
                ]
            }
        ]
        return call_openai_api(messages, max_tokens, max_retries, response_format, reasoning_effort, stage)
    except Exception as e:
        print(f"Error calling OpenAI with image: {e}")
        return None, None

def call_openai_api_json(messages, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, reasoning_effort=DEFAULT_REASONING_EFFORT, stage=None, model=None):
    """Call OpenAI API with JSON response format - guaranteed to return valid JSON."""
    return call_openai_api(messages, max_tokens, max_retries, response_format={"type": "json_object"}, reasoning_effort=reasoning_effort, stage=stage, model=model)

def call_openai_with_image_json(prompt, image_path, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, reasoning_effort=DEFAULT_REASONING_EFFORT, stage=None):
    """Call OpenAI API with image and JSON response format."""
    return call_openai_with_image(prompt, image_path, max_tokens, max_retries, response_format={"type": "json_object"}, reasoning_effort=reasoning_effort, stage=stage)

# ============================================================================
# Public API Functions - Asynchronous
# ============================================================================

async def call_openai_api_async(messages, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, response_format=None, reasoning_effort=DEFAULT_REASONING_EFFORT, model=None, stage=None):
    """Async version of call_openai_api with retry mechanism.

    Args:
        messages: The messages to send to the API
        max_tokens: Maximum tokens for completion
        max_retries: Number of retry attempts
        response_format: Optional response format (e.g., {"type": "json_object"})
        reasoning_effort: Reasoning effort level for supported models
        model: Optional model override
        stage: Optional stage name for token tracking

    Returns:
        Tuple of (reply, usage_info) or (None, None) on failure
    """
    client = get_async_client()
    deployment = model if model is not None else current_deployment
    response_params = _build_response_params(deployment, messages, max_tokens, reasoning_effort, response_format)
    return await _execute_with_retry_async(client, response_params, deployment, max_retries, stage)

async def call_openai_with_image_async(prompt, image_path, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, response_format=None, reasoning_effort=DEFAULT_REASONING_EFFORT, stage=None, model=None):
    """Async version of call_openai_with_image."""
    try:
        image_url = encode_image(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url}
                ]
            }
        ]
        return await call_openai_api_async(messages, max_tokens, max_retries, response_format, reasoning_effort, stage=stage, model=model)
    except Exception as e:
        print(f"Error calling OpenAI with image: {e}")
        return None, None

async def call_openai_api_json_async(messages, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, reasoning_effort=DEFAULT_REASONING_EFFORT, model=None, stage=None):
    """Async version of call_openai_api_json - guaranteed to return valid JSON."""
    return await call_openai_api_async(messages, max_tokens, max_retries, response_format={"type": "json_object"}, reasoning_effort=reasoning_effort, model=model, stage=stage)

async def call_openai_api_with_tools_async(
    input_messages,
    tools,
    max_retries=DEFAULT_MAX_RETRIES,
    reasoning_effort=DEFAULT_REASONING_EFFORT,
    model=None,
    stage=None,
    client=None,
):
    """Call OpenAI Responses API with tool calling support.

    Unlike call_openai_api_async, this returns the raw response object so
    the caller can inspect output items (function_call, text, etc.).

    Args:
        input_messages: The input list (Responses API format)
        tools: List of tool definitions
        max_retries: Number of retry attempts
        reasoning_effort: Reasoning effort level
        model: Optional model override
        stage: Optional stage name for token tracking
        client: Optional pre-created async client (for endpoint pinning)

    Returns:
        Tuple of (response_object, usage_info_dict) or (None, None) on failure
    """
    if client is None:
        client = get_async_client()
    deployment = model if model is not None else current_deployment
    effective_max_tokens, effective_reasoning_effort = _get_effective_params(
        deployment, DEFAULT_MAX_TOKENS, reasoning_effort
    )

    response_params = {
        "model": deployment,
        "input": input_messages,
        "tools": tools,
        "max_output_tokens": effective_max_tokens,
        "store": False,
    }

    if deployment in REASONING_MODELS:
        response_params["reasoning"] = {"effort": effective_reasoning_effort}

    for attempt in range(max_retries):
        try:
            response = await client.responses.create(**response_params)
            usage_info = {
                'total_tokens': response.usage.total_tokens,
                'prompt_tokens': response.usage.input_tokens,
                'completion_tokens': response.usage.output_tokens,
            }
            if stage:
                _track_token_usage(deployment, usage_info, stage)
            return response, usage_info
        except Exception as e:
            print(f"OpenAI API Error (tools) on attempt {attempt + 1}: {e}")
            if attempt < max_retries - 1:
                continue
            return None, None

    return None, None


async def call_openai_api_json_async_with_endpoint(messages, endpoint, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, reasoning_effort=DEFAULT_REASONING_EFFORT, model=None, stage=None):
    """Async version of call_openai_api_json with specific endpoint - for parallel multi-endpoint processing.

    Args:
        messages: The messages to send to the API
        endpoint: The specific endpoint to use
        max_tokens: Maximum tokens for completion
        max_retries: Number of retry attempts
        reasoning_effort: Reasoning effort level for supported models
        model: Optional model override
        stage: Optional stage name for token tracking

    Returns:
        Tuple of (reply, usage_info) or (None, None) on failure
    """
    client = get_async_client_for_endpoint(endpoint)
    deployment = model if model is not None else current_deployment
    response_params = _build_response_params(deployment, messages, max_tokens, reasoning_effort, {"type": "json_object"})
    return await _execute_with_retry_async(client, response_params, deployment, max_retries, stage, endpoint_label=endpoint)

async def call_openai_with_image_json_async(prompt, image_path, max_tokens=DEFAULT_MAX_TOKENS, max_retries=DEFAULT_MAX_RETRIES, reasoning_effort=DEFAULT_REASONING_EFFORT, stage=None, model=None):
    """Async version of call_openai_with_image_json."""
    return await call_openai_with_image_async(prompt, image_path, max_tokens, max_retries, response_format={"type": "json_object"}, reasoning_effort=reasoning_effort, stage=stage, model=model)

# Export functions and constants for other modules
__all__ = [
    # Synchronous API functions
    'call_openai_api', 'call_openai_with_image', 'call_openai_api_json', 'call_openai_with_image_json',
    # Asynchronous API functions
    'call_openai_api_async', 'call_openai_with_image_async', 'call_openai_api_json_async', 'call_openai_with_image_json_async',
    'call_openai_api_with_tools_async',
    'call_openai_api_json_async_with_endpoint',
    # Utility functions
    'encode_image',
    # Client management (deprecated functions included for backward compatibility)
    'initialize_client', 'get_client', 'initialize_async_client', 'get_async_client',
    'configure_load_balancing', 'get_next_endpoint', 'get_async_client_for_endpoint',
    # Constants
    'LOAD_BALANCE_ROUND_ROBIN', 'LOAD_BALANCE_RANDOM', 'DEFAULT_ENDPOINTS',
    'REASONING_MODELS', 'MODEL_CONFIG',
    'DEFAULT_MAX_TOKENS', 'DEFAULT_MAX_RETRIES', 'DEFAULT_REASONING_EFFORT',
]