"""
TDD Instrumentation Data Models

Data structures for instrumentation post-processing module
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any


@dataclass
class InstrumentationVariable:
    """
    Specification for a single instrumentation variable to be added
    """
    variable_name: str              # e.g., "task1_searchCompleted"
    variable_type: str              # "boolean" | "string" | "object" | "array"
    set_in_function: str            # Function name where variable should be set
    set_condition: str              # Description of when to set the variable
    value_to_set: str              # Value to set (as string representation)
    reason: str                     # Explanation of why this variable is needed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstrumentationVariable':
        """Create from dictionary"""
        return cls(**data)


@dataclass
class InstrumentationRequirement:
    """
    Instrumentation requirements for a single task
    """
    task_id: str                                    # Task identifier
    task_name: str                                  # Task name
    task_description: str                           # Task description
    needs_instrumentation: bool                     # Whether instrumentation is needed
    existing_variables: List[str] = field(default_factory=list)  # Already available localStorage vars
    required_variables: List[InstrumentationVariable] = field(default_factory=list)  # New variables needed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_description": self.task_description,
            "needs_instrumentation": self.needs_instrumentation,
            "existing_variables": self.existing_variables,
            "required_variables": [v.to_dict() for v in self.required_variables]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstrumentationRequirement':
        """Create from dictionary"""
        return cls(
            task_id=data["task_id"],
            task_name=data["task_name"],
            task_description=data["task_description"],
            needs_instrumentation=data["needs_instrumentation"],
            existing_variables=data.get("existing_variables", []),
            required_variables=[
                InstrumentationVariable.from_dict(v)
                for v in data.get("required_variables", [])
            ]
        )


@dataclass
class InstrumentationPlan:
    """
    Complete instrumentation plan for all tasks
    """
    requirements: List[InstrumentationRequirement] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "requirements": [r.to_dict() for r in self.requirements]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstrumentationPlan':
        """Create from dictionary"""
        return cls(
            requirements=[
                InstrumentationRequirement.from_dict(r)
                for r in data.get("requirements", [])
            ]
        )

    def get_variables_for_task(self, task_id: str) -> List[str]:
        """
        Get all variable names required for a specific task

        Args:
            task_id: Task identifier

        Returns:
            List of variable names
        """
        for req in self.requirements:
            if req.task_id == task_id:
                return [v.variable_name for v in req.required_variables]
        return []

    def get_all_variables(self) -> List[str]:
        """
        Get all instrumentation variable names across all tasks

        Returns:
            List of all variable names
        """
        all_vars = []
        for req in self.requirements:
            all_vars.extend([v.variable_name for v in req.required_variables])
        return all_vars

    def has_instrumentation_needs(self) -> bool:
        """Check if any task needs instrumentation"""
        return any(req.needs_instrumentation for req in self.requirements)


@dataclass
class ValidationResult:
    """
    Result of instrumentation code validation
    """
    success: bool                                   # Overall success
    original_tests_passed: bool                     # Original functionality preserved
    instrumentation_tests_passed: bool              # Instrumentation works correctly
    total_tests: int = 0                           # Total number of tests run
    passed_tests: int = 0                          # Number of tests passed
    failed_tests: int = 0                          # Number of tests failed
    iterations_used: int = 0                       # Number of fix iterations used
    message: str = ""                              # Additional message
    errors: List[str] = field(default_factory=list)  # Error messages if any

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class EvaluatorValidationResult:
    """
    Result of evaluator validation and fixing
    """
    success: bool                                   # Overall success
    total_evaluators: int = 0                       # Total number of evaluators
    validated_evaluators: int = 0                   # Number of evaluators that passed
    failed_evaluators: int = 0                      # Number of evaluators that failed
    iterations_used: int = 0                        # Number of fix iterations used
    message: str = ""                               # Additional message
    errors: List[str] = field(default_factory=list)  # Error messages if any
    failed_evaluator_ids: List[str] = field(default_factory=list)  # IDs of failed evaluators

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
