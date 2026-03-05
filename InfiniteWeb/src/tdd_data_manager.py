"""
TDD Data Manager Module
Centralized data management for TDD system
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field

# Import DesignAnalysis from the analyzer module
try:
    from tdd_design_analyzer import DesignAnalysis
except ImportError:
    # Fallback definition if module not available
    @dataclass
    class DesignAnalysis:
        visual_features: Dict[str, Any]
        color_scheme: Dict[str, Any]
        layout_characteristics: Dict[str, Any]
        ui_patterns: List[Dict[str, Any]]
        typography: Dict[str, Any]
        spacing_system: Dict[str, Any]
        interaction_hints: List[str]


@dataclass
class TDDTask:
    """User task structure"""
    id: str
    name: str
    description: str
    steps: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDTask':
        """Create from dictionary"""
        return cls(**data)


@dataclass
class TDDDataModels:
    """Data models extracted from tasks"""
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDDataModels':
        """Create from dictionary"""
        # Filter to only known fields to handle unexpected fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class TDDInterfaces:
    """Interface definitions"""
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    helperFunctions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDInterfaces':
        """Create from dictionary"""
        # Filter to only known fields to handle unexpected fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class TDDWrappedInterfaces:
    """Wrapped interface definitions with state data"""
    wrapped_interfaces: List[Dict[str, Any]] = field(default_factory=list)
    original_interfaces: List[Dict[str, Any]] = field(default_factory=list)
    state_data_models: List[Dict[str, Any]] = field(default_factory=list)
    implementation_mapping: List[Dict[str, Any]] = field(default_factory=list)
    helper_functions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDWrappedInterfaces':
        """Create from dictionary"""
        # Filter to only known fields to handle unexpected fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class TDDEvaluator:
    """
    Evaluator for task completion in TDD system

    The evaluation_logic is JavaScript code that returns a score from 0.0 to 1.0:
    - 1.0: Task fully completed
    - 0.0-0.9: Partial completion (checkpoint-based scoring)
    - 0.0: Task not started or no progress

    Uses checkpoint-based scoring pattern:
    ```javascript
    const checkpoints = [];
    checkpoints.push({ passed: condition, weight: 0.2 });
    // ... more checkpoints (weights sum to 1.0)
    return checkpoints.reduce((sum, cp) => sum + (cp.passed ? cp.weight : 0), 0);
    ```
    """
    task_id: str
    name: str
    description: str
    localStorage_variables: List[str]
    evaluation_logic: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDEvaluator':
        """Create from dictionary"""
        return cls(**data)


@dataclass
class TDDGenerationResult:
    """Result of TDD generation"""
    success: bool
    implementation: str = ""
    tests: str = ""
    test_results: Dict[str, Any] = field(default_factory=dict)
    data_models: Dict[str, Any] = field(default_factory=dict)
    interfaces: Dict[str, Any] = field(default_factory=dict)
    wrapped_interfaces: Dict[str, Any] = field(default_factory=dict)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    architecture: Dict[str, Any] = field(default_factory=dict)
    page_designs: List[Dict[str, Any]] = field(default_factory=list)
    design_analysis: Optional[Dict[str, Any]] = None
    evaluators: List[TDDEvaluator] = field(default_factory=list)
    generation_time: float = 0.0
    iterations_used: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TDDGenerationResult':
        """Create from dictionary"""
        return cls(**data)


class TDDDataManager:
    """Manages all data flow in TDD system"""
    
    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize data manager
        
        Args:
            output_dir: Directory for data storage
        """
        self.output_dir = output_dir or "src/test/generated"
        self.data_dir = os.path.join(self.output_dir, "data")
        
        # In-memory data storage
        self.tasks: List[TDDTask] = []
        self.data_models: Optional[TDDDataModels] = None
        self.interfaces: Optional[TDDInterfaces] = None
        self.wrapped_interfaces: Optional[TDDWrappedInterfaces] = None
        self.implementation: str = ""
        self.tests: str = ""
        self.test_results: Dict[str, Any] = {}
        self.architecture: Dict[str, Any] = {}
        self.page_designs: List[Dict[str, Any]] = []
        self.design_analysis: Optional[DesignAnalysis] = None
        self.evaluators: List[TDDEvaluator] = []
        self.generation_result: Optional[TDDGenerationResult] = None
        
        # Metadata
        self.metadata = {
            "created_at": datetime.now().isoformat(),
            "website_type": None,
            "version": "1.0.0"
        }
        
        # Setup directories
        self._setup_directories()
    
    def _setup_directories(self):
        """Create necessary directories"""
        os.makedirs(self.data_dir, exist_ok=True)
    
    # Task Management
    def set_tasks(self, tasks: List[Dict[str, Any]], website_type: str = None):
        """
        Set user tasks
        
        Args:
            tasks: List of task dictionaries
            website_type: Type of website
        """
        self.tasks = [TDDTask.from_dict(task) for task in tasks]
        if website_type:
            self.metadata["website_type"] = website_type
        self._save_data("tasks.json", {"tasks": tasks, "website_type": website_type})
    
    def get_tasks(self) -> List[TDDTask]:
        """Get all tasks"""
        return self.tasks
    
    def get_tasks_dict(self) -> List[Dict[str, Any]]:
        """Get tasks as dictionaries"""
        return [task.to_dict() for task in self.tasks]
    
    # Data Models Management
    def set_data_models(self, data_models: Dict[str, Any]):
        """
        Set data models
        
        Args:
            data_models: Data models dictionary
        """
        self.data_models = TDDDataModels.from_dict(data_models)
        self._save_data("data_models.json", data_models)
    
    def get_data_models(self) -> Optional[TDDDataModels]:
        """Get data models"""
        return self.data_models
    
    def get_data_models_dict(self) -> Dict[str, Any]:
        """Get data models as dictionary"""
        return self.data_models.to_dict() if self.data_models else {}
    
    # Interfaces Management
    def set_interfaces(self, interfaces: Dict[str, Any]):
        """
        Set interfaces
        
        Args:
            interfaces: Interfaces dictionary
        """
        self.interfaces = TDDInterfaces.from_dict(interfaces)
        self._save_data("interfaces.json", interfaces)
    
    def get_interfaces(self) -> Optional[TDDInterfaces]:
        """Get interfaces"""
        return self.interfaces
    
    def get_interfaces_dict(self) -> Dict[str, Any]:
        """Get interfaces as dictionary"""
        return self.interfaces.to_dict() if self.interfaces else {}
    
    # Wrapped Interfaces Management
    def set_wrapped_interfaces(self, wrapped_interfaces: Dict[str, Any]):
        """
        Set wrapped interfaces
        
        Args:
            wrapped_interfaces: Wrapped interfaces dictionary
        """
        self.wrapped_interfaces = TDDWrappedInterfaces.from_dict(wrapped_interfaces)
        self._save_data("wrapped_interfaces.json", wrapped_interfaces)
    
    def get_wrapped_interfaces(self) -> Optional[TDDWrappedInterfaces]:
        """Get wrapped interfaces"""
        return self.wrapped_interfaces
    
    def get_wrapped_interfaces_dict(self) -> Dict[str, Any]:
        """Get wrapped interfaces as dictionary"""
        return self.wrapped_interfaces.to_dict() if self.wrapped_interfaces else {}
    
    def get_enhanced_data_models(self) -> Dict[str, Any]:
        """
        Get enhanced data models including state data from wrapped interfaces
        
        Returns:
            Combined data models with state data
        """
        base_models = self.get_data_models_dict()
        
        if self.wrapped_interfaces and self.wrapped_interfaces.state_data_models:
            # Merge state data models with existing data models
            enhanced_entities = base_models.get("entities", []).copy()
            enhanced_entities.extend(self.wrapped_interfaces.state_data_models)
            
            enhanced_models = base_models.copy()
            enhanced_models["entities"] = enhanced_entities
            enhanced_models["has_state_models"] = True
            enhanced_models["state_model_count"] = len(self.wrapped_interfaces.state_data_models)
            
            return enhanced_models
        
        return base_models
    
    # Implementation Management
    def set_implementation(self, implementation: str):
        """
        Set implementation code
        
        Args:
            implementation: JavaScript implementation code
        """
        self.implementation = implementation
        self._save_code("business_logic.js", implementation)
    
    def get_implementation(self) -> str:
        """Get implementation code"""
        return self.implementation
    
    # Tests Management
    def set_tests(self, tests: str):
        """
        Set test code
        
        Args:
            tests: JavaScript test code
        """
        self.tests = tests
        self._save_code("test_flows.js", tests)
    
    def get_tests(self) -> str:
        """Get test code"""
        return self.tests
    
    # Test Results Management
    def set_test_results(self, test_results: Dict[str, Any]):
        """
        Set test results
        
        Args:
            test_results: Test execution results
        """
        self.test_results = test_results
        self._save_data("test_results.json", test_results)
    
    def get_test_results(self) -> Dict[str, Any]:
        """Get test results"""
        return self.test_results
    
    # Architecture Management
    def set_architecture(self, architecture: Any):
        """
        Set website architecture
        
        Args:
            architecture: WebsiteArchitecture object or dict
        """
        # Convert to dict if it's an object
        if hasattr(architecture, '__dict__'):
            self.architecture = asdict(architecture) if hasattr(architecture, '__dataclass_fields__') else vars(architecture)
        else:
            self.architecture = architecture
        self._save_data("architecture.json", self.architecture)
    
    def get_architecture(self) -> Dict[str, Any]:
        """
        Get website architecture
        
        Returns:
            Architecture dictionary
        """
        return self.architecture
    
    # Page Design Management
    def set_page_designs(self, page_designs: Any):
        """
        Set page designs
        
        Args:
            page_designs: List of PageDesign objects or dicts
        """
        if isinstance(page_designs, list):
            self.page_designs = []
            for design in page_designs:
                if hasattr(design, '__dict__'):
                    # Convert dataclass to dict
                    design_dict = asdict(design) if hasattr(design, '__dataclass_fields__') else vars(design)
                    self.page_designs.append(design_dict)
                else:
                    self.page_designs.append(design)
        else:
            self.page_designs = page_designs
        
        self._save_data("page_designs.json", self.page_designs)
    
    def get_page_designs(self) -> List[Dict[str, Any]]:
        """
        Get page designs
        
        Returns:
            List of page design dictionaries
        """
        return self.page_designs
    
    def update_page_designs_with_layouts(self, page_designs_with_layouts: List[Any]):
        """
        Update page designs with layout information
        
        Args:
            page_designs_with_layouts: List of PageDesign objects with layout field populated
        """
        self.set_page_designs(page_designs_with_layouts)
        self._save_data("page_designs_with_layouts.json", self.page_designs)
    
    def set_page_framework(self, framework: Any):
        """
        Set page framework (header/footer HTML and CSS)
        
        Args:
            framework: PageFramework object or dict containing framework_html and framework_css
        """
        if hasattr(framework, '__dataclass_fields__'):
            # It's a dataclass
            self.page_framework = framework
            from dataclasses import asdict
            framework_dict = asdict(framework)
        else:
            # It's a dict or other object
            self.page_framework = framework
            framework_dict = framework if isinstance(framework, dict) else vars(framework)
        
        # Save to file
        self._save_data("page_framework.json", framework_dict)
    
    def get_page_framework(self) -> Optional[Dict[str, Any]]:
        """
        Get page framework
        
        Returns:
            Page framework dict or None
        """
        if hasattr(self, 'page_framework'):
            if hasattr(self.page_framework, '__dataclass_fields__'):
                from dataclasses import asdict
                return asdict(self.page_framework)
            elif isinstance(self.page_framework, dict):
                return self.page_framework
            else:
                return vars(self.page_framework)
        return None
    
    # Design Analysis Management
    def set_design_analysis(self, design_analysis: Optional[DesignAnalysis]):
        """
        Set design analysis
        
        Args:
            design_analysis: DesignAnalysis object or None
        """
        self.design_analysis = design_analysis
        if design_analysis:
            # Convert to dict for storage
            analysis_dict = asdict(design_analysis) if hasattr(design_analysis, '__dataclass_fields__') else vars(design_analysis)
            self._save_data("design_analysis.json", analysis_dict)
    
    def get_design_analysis(self) -> Optional[DesignAnalysis]:
        """
        Get design analysis
        
        Returns:
            DesignAnalysis object or None
        """
        return self.design_analysis
    
    # Generation Result Management
    def create_generation_result(self, success: bool, generation_time: float, 
                                iterations_used: int) -> TDDGenerationResult:
        """
        Create generation result object
        
        Args:
            success: Whether generation was successful
            generation_time: Time taken for generation
            iterations_used: Number of iterations used
            
        Returns:
            TDDGenerationResult object
        """
        self.generation_result = TDDGenerationResult(
            success=success,
            implementation=self.implementation,
            tests=self.tests,
            test_results=self.test_results,
            data_models=self.get_enhanced_data_models(),
            interfaces=self.get_interfaces_dict(),
            wrapped_interfaces=self.get_wrapped_interfaces_dict(),
            tasks=[asdict(task) for task in self.tasks],
            architecture=self.architecture,
            page_designs=self.page_designs,
            design_analysis=asdict(self.design_analysis) if self.design_analysis else None,
            evaluators=self.evaluators,
            generation_time=generation_time,
            iterations_used=iterations_used,
            metadata=self.metadata
        )
        
        # Save complete result
        self._save_data("generation_result.json", self.generation_result.to_dict())
        
        return self.generation_result
    
    def get_generation_result(self) -> Optional[TDDGenerationResult]:
        """Get generation result"""
        return self.generation_result
    
    # Data Persistence
    def _save_data(self, filename: str, data: Any):
        """
        Save data to JSON file
        
        Args:
            filename: Name of the file
            data: Data to save
        """
        filepath = os.path.join(self.data_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _save_code(self, filename: str, code: str):
        """
        Save code to file
        
        Args:
            filename: Name of the file
            code: Code to save
        """
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(code)
    
    def _load_data(self, filename: str) -> Optional[Any]:
        """
        Load data from JSON file
        
        Args:
            filename: Name of the file
            
        Returns:
            Loaded data or None if file doesn't exist
        """
        filepath = os.path.join(self.data_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    # Data Validation
    def validate_data_models(self) -> Dict[str, Any]:
        """
        Validate data models
        
        Returns:
            Validation result dictionary
        """
        if not self.data_models:
            return {"valid": False, "errors": ["No data models set"]}
        
        errors = []
        warnings = []
        
        # Check entities
        if not self.data_models.entities:
            errors.append("No entities defined")
        else:
            for entity in self.data_models.entities:
                if 'name' not in entity:
                    errors.append(f"Entity missing name: {entity}")
                if 'fields' not in entity or not entity['fields']:
                    warnings.append(f"Entity {entity.get('name', 'unknown')} has no fields")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def validate_interfaces(self) -> Dict[str, Any]:
        """
        Validate interfaces
        
        Returns:
            Validation result dictionary
        """
        if not self.interfaces:
            return {"valid": False, "errors": ["No interfaces set"]}
        
        errors = []
        warnings = []
        
        # Check interfaces
        if not self.interfaces.interfaces:
            errors.append("No interfaces defined")
        else:
            for interface in self.interfaces.interfaces:
                if 'name' not in interface:
                    errors.append(f"Interface missing name: {interface}")
                if 'parameters' not in interface:
                    warnings.append(f"Interface {interface.get('name', 'unknown')} has no parameters")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    # Export Functions
    def export_debug_data(self, include_code: bool = True) -> Dict[str, Any]:
        """
        Export all data for debugging
        
        Args:
            include_code: Whether to include implementation and test code
            
        Returns:
            Dictionary with all data
        """
        debug_data = {
            "metadata": self.metadata,
            "tasks": self.get_tasks_dict(),
            "data_models": self.get_data_models_dict(),
            "interfaces": self.get_interfaces_dict(),
            "architecture": self.architecture,
            "page_designs": self.page_designs,
            "test_results": self.test_results,
            "validations": {
                "data_models": self.validate_data_models(),
                "interfaces": self.validate_interfaces()
            }
        }
        
        if include_code:
            debug_data["implementation"] = self.implementation[:1000] + "..." if len(self.implementation) > 1000 else self.implementation
            debug_data["tests"] = self.tests[:1000] + "..." if len(self.tests) > 1000 else self.tests
        
        return debug_data
    
    def save_debug_data(self, filename: str = "debug_data.json"):
        """
        Save debug data to file
        
        Args:
            filename: Name of the debug file
        """
        debug_data = self.export_debug_data()
        self._save_data(filename, debug_data)
    
    # Summary Functions
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of current data state
        
        Returns:
            Summary dictionary
        """
        # Calculate enhanced entities including state models
        enhanced_data = self.get_enhanced_data_models()
        base_entity_count = len(self.data_models.entities) if self.data_models else 0
        
        return {
            "website_type": self.metadata.get("website_type"),
            "task_count": len(self.tasks),
            "entity_count": len(enhanced_data.get("entities", [])),
            "base_entity_count": base_entity_count,
            "state_entity_count": enhanced_data.get("state_model_count", 0),
            "interface_count": len(self.interfaces.interfaces) if self.interfaces else 0,
            "wrapped_interface_count": len(self.wrapped_interfaces.wrapped_interfaces) if self.wrapped_interfaces else 0,
            "implementation_size": len(self.implementation),
            "tests_size": len(self.tests),
            "test_results": {
                "total": self.test_results.get("total", 0),
                "passed": self.test_results.get("passed", 0),
                "failed": self.test_results.get("failed", 0)
            } if self.test_results else None,
            "generation_success": self.generation_result.success if self.generation_result else None,
            "has_wrapped_interfaces": self.wrapped_interfaces is not None
        }
    
    def print_summary(self):
        """Print data summary to console"""
        summary = self.get_summary()
        print("\n=== TDD Data Summary ===")
        print(f"Website Type: {summary['website_type']}")
        print(f"Tasks: {summary['task_count']}")
        print(f"Total Entities: {summary['entity_count']} (Business: {summary['base_entity_count']}, State: {summary['state_entity_count']})")
        print(f"Original Interfaces: {summary['interface_count']}")
        if summary['has_wrapped_interfaces']:
            print(f"Wrapped Interfaces: {summary['wrapped_interface_count']}")
        print(f"Implementation Size: {summary['implementation_size']} chars")
        print(f"Tests Size: {summary['tests_size']} chars")
        if summary['test_results']:
            print(f"Test Results: {summary['test_results']['passed']}/{summary['test_results']['total']} passed")
        if self.page_designs:
            print(f"Page Designs: {len(self.page_designs)} pages")
        print("=" * 24)