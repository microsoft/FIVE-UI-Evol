"""
TDD Config Manager Module
Configuration management for TDD system
"""

import os
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field


@dataclass
class TDDConfig:
    """TDD system configuration"""
    
    # Output settings
    output_dir: str = "src/test/generated"
    
    # Logging settings
    log_level: str = "INFO"
    
    # Generation settings
    max_fix_iterations: int = 3
    temperature: float = 0.7
    
    # Task generation settings
    task_count_range: str = "3-5"
    custom_task_names: List[str] = field(default_factory=list)
    website_type: str = "shopping_website"
    
    # Design analysis settings
    design_image_path: str = ""  # Required: path to design image
    
    # Resource replacement settings (multiple APIs)
    pexels_api_key: str = ""  # Pexels API key for images and videos
    freesound_api_key: str = ""  # Freesound API key for audio
    youtube_api_key: str = ""  # YouTube API key for video embeds
    google_api_key: str = ""  # Google API key for file search
    google_cse_cx: str = ""  # Google Custom Search Engine ID
    image_mode: str = "Real"  # Image mode: "Real" for search-based, "Generate" for AI-generated

    # Local image search settings
    local_image_search_url: str = "http://localhost:8001"  # Local image search service URL
    local_image_search_dataset: str = "all"  # Dataset to use: lr, hr, or all
    local_image_search_min_resolution: int = 600  # Minimum resolution filter (width or height)
    
    # Architecture settings
    max_pages: int = 8
    
    # Interface wrapping is always enabled - no configuration needed
    
    # API settings
    deployment: str = "gpt-4.1"
    endpoints: List[str] = field(default_factory=lambda: [])
    load_balance_strategy: str = "round_robin"
    max_retries: int = 5
    retry_delay: float = 1.0
    
    # Data settings
    max_data_items: int = 20
    
    # Concurrency settings
    max_concurrent: int = 3  # Maximum concurrent requests for parallel processing

    # Ablation study settings
    skip_tdd_validation: bool = False  # Skip TDD validation for ablation study

    # Custom settings (for extensibility)
    custom: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDConfig':
        """Create from dictionary"""
        # Filter out unknown fields that aren't in the dataclass
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        return cls(**filtered_data)


class TDDConfigManager:
    """Manages TDD system configuration"""
    
    # Default configuration paths
    DEFAULT_CONFIG_DIR = "config"
    DEFAULT_CONFIG_FILE = "default_config.json"
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize config manager

        Args:
            config_path: Optional path to configuration file
        """
        self.config_path = config_path
        self.config = TDDConfig()
        self.config_loaded = False
        self._raw_config: Dict[str, Any] = {}  # 保存原始配置，用于组件级别配置项

        # Load configuration
        if config_path:
            self.load_config(config_path)
        else:
            self.load_defaults()
    
    def load_config(self, config_path: str):
        """
        Load configuration from file
        
        Args:
            config_path: Path to configuration file
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        # Sanitize placeholder values (e.g., "YOUR_PEXELS_API_KEY") before use
        config_data = self._sanitize_placeholders(config_data)

        # 保存原始配置，用于组件级别配置项读取
        self._raw_config = config_data

        # Merge with defaults
        merged_config = self._merge_with_defaults(config_data)
        
        # Create config object
        self.config = TDDConfig.from_dict(merged_config)
        self.config_path = config_path
        self.config_loaded = True
    
    def load_defaults(self):
        """Load default configuration"""
        # Try to load from default file if exists
        default_path = os.path.join(self.DEFAULT_CONFIG_DIR, self.DEFAULT_CONFIG_FILE)
        if os.path.exists(default_path):
            self.load_config(default_path)
        else:
            # Use built-in defaults
            self.config = TDDConfig()
            self._raw_config = {}
            self.config_loaded = True
    
    @staticmethod
    def _is_placeholder(value) -> bool:
        """Check if a config value is a placeholder that hasn't been replaced"""
        if isinstance(value, str):
            return value.startswith("YOUR_")
        return False

    def _sanitize_placeholders(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Replace placeholder values (YOUR_*) with empty defaults"""
        sanitized = {}
        for key, value in config_data.items():
            if isinstance(value, str) and self._is_placeholder(value):
                sanitized[key] = ""
            elif isinstance(value, list):
                sanitized[key] = [
                    item for item in value
                    if not (isinstance(item, str) and self._is_placeholder(item))
                ]
            else:
                sanitized[key] = value
        return sanitized

    def _merge_with_defaults(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge provided config with defaults
        
        Args:
            config_data: Configuration data from file
            
        Returns:
            Merged configuration
        """
        # Get default values
        default_config = TDDConfig().to_dict()
        
        # Deep merge
        merged = default_config.copy()
        for key, value in config_data.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                # Recursive merge for nested dicts
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        
        return merged
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value

        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found

        Returns:
            Configuration value
        """
        # 优先从原始配置读取（支持组件级别配置项）
        if key in self._raw_config:
            return self._raw_config[key]

        # 回退到 TDDConfig 对象（支持点号表示法）
        keys = key.split('.')
        value = self.config.to_dict()

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_component_config(self, component_name: str) -> Dict[str, Any]:
        """
        Get component-specific configuration (model, reasoning_effort)

        Supports two configuration formats (in order of priority):
        1. stage_configs dict: stage_configs.{component_name}.model / reasoning_effort
        2. Flat naming: {component}_model / {component}_reasoning_effort

        Args:
            component_name: Name of the component (e.g., "data_extractor", "page_generator")

        Returns:
            Dictionary with model and reasoning_effort
        """
        # Priority 1: Check stage_configs dict
        stage_configs = self._raw_config.get("stage_configs", {})
        if component_name in stage_configs:
            stage_config = stage_configs[component_name]
            return {
                "model": stage_config.get("model") or self.get("deployment"),
                "reasoning_effort": stage_config.get("reasoning_effort") or "medium"
            }

        # Priority 2: Fall back to flat naming convention
        return {
            "model": self.get(f"{component_name}_model") or self.get("deployment"),
            "reasoning_effort": self.get(f"{component_name}_reasoning_effort") or "medium"
        }
    
    def set(self, key: str, value: Any):
        """
        Set configuration value

        Args:
            key: Configuration key
            value: Value to set
        """
        # Update _raw_config first (get() reads from here with priority)
        self._raw_config[key] = value

        # Also update config object for consistency
        if hasattr(self.config, key):
            setattr(self.config, key, value)
        else:
            # Store in custom
            self.config.custom[key] = value
    
    def update(self, updates: Dict[str, Any]):
        """
        Update multiple configuration values
        
        Args:
            updates: Dictionary of updates
        """
        for key, value in updates.items():
            self.set(key, value)
    
    def validate(self) -> Dict[str, Any]:
        """
        Validate configuration
        
        Returns:
            Validation result with errors and warnings
        """
        errors = []
        warnings = []
        
        # Check output directory
        if not self.config.output_dir:
            errors.append("output_dir is required")
        
        # Check log level
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.config.log_level.upper() not in valid_log_levels:
            errors.append(f"Invalid log_level: {self.config.log_level}")
        
        # Check max iterations
        if self.config.max_fix_iterations < 1:
            warnings.append("max_fix_iterations should be at least 1")
        
        if self.config.max_fix_iterations > 10:
            warnings.append("max_fix_iterations > 10 may cause long execution times")
        
        # Check API settings
        if not self.config.endpoints:
            errors.append("At least one API endpoint is required")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def save(self, filepath: Optional[str] = None):
        """
        Save configuration to file
        
        Args:
            filepath: Optional filepath (uses current path if not provided)
        """
        save_path = filepath or self.config_path
        if not save_path:
            save_path = os.path.join(self.DEFAULT_CONFIG_DIR, "config.json")
        
        # Create directory if needed
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Save configuration
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
    
    def export_for_llm(self) -> Dict[str, Any]:
        """
        Export configuration for LLM API calls
        
        Returns:
            Configuration relevant for LLM calls
        """
        return {
            "deployment": self.config.deployment,
            "temperature": self.config.temperature,
            "endpoints": self.config.endpoints,
            "load_balance_strategy": self.config.load_balance_strategy,
            "max_retries": self.config.max_retries,
            "retry_delay": self.config.retry_delay
        }
    
    def export_for_test_execution(self) -> Dict[str, Any]:
        """
        Export configuration for test execution
        
        Returns:
            Configuration relevant for test execution
        """
        return {
            "max_fix_iterations": self.config.max_fix_iterations
        }
    
    def get_summary(self) -> str:
        """
        Get configuration summary as string
        
        Returns:
            Human-readable configuration summary
        """
        lines = [
            "=== TDD Configuration ===",
            f"Output Directory: {self.config.output_dir}",
            f"Log Level: {self.config.log_level}",
            f"Max Fix Iterations: {self.config.max_fix_iterations}",
            f"API Model: {self.config.deployment}",
            f"Endpoints: {len(self.config.endpoints)} configured",
            f"Max Data Items: {self.config.max_data_items}",
            f"Task Count Range: {self.config.task_count_range}",
            f"Pexels API Key: {'Configured' if self.config.pexels_api_key else 'Not configured'}",
            f"Freesound API Key: {'Configured' if self.config.freesound_api_key else 'Not configured'}",
            f"YouTube API Key: {'Configured' if self.config.youtube_api_key else 'Not configured'}",
            f"Google API Key: {'Configured' if self.config.google_api_key else 'Not configured'}",
            f"Website Type: {self.config.website_type}",
        ]
        
        if self.config.custom:
            lines.append(f"Custom Settings: {len(self.config.custom)} configured")
        
        if self.config_path:
            lines.append(f"Config File: {self.config_path}")
        
        lines.append("=" * 25)
        
        return "\n".join(lines)
    
    def print_summary(self):
        """Print configuration summary to console"""
        print(self.get_summary())
    
    @classmethod
    def create_default_config_file(cls, filepath: str):
        """
        Create a default configuration file
        
        Args:
            filepath: Path where to save the default config
        """
        default_config = TDDConfig()
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_config.to_dict(), f, indent=2, ensure_ascii=False)
        
        print(f"Default configuration saved to: {filepath}")