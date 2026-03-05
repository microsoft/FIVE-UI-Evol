"""
Token Tracker Module
Records and tracks token usage across different models during generation
"""

import json
import threading
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path


class TokenTracker:
    """
    Singleton class to track token usage across different models.
    Thread-safe implementation to handle concurrent API calls.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self._stats_lock = threading.Lock()
        self.reset()
    
    def reset(self):
        """Reset all token statistics"""
        with self._stats_lock:
            self.total_stats = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "api_calls": 0
            }
            
            self.model_stats = {}  # Stats per model
            self.stage_stats = {}  # Stats per generation stage
            self.start_time = datetime.now()
            self.end_time = None
    
    def record_usage(self, 
                     model: str,
                     input_tokens: int,
                     output_tokens: int,
                     total_tokens: int,
                     stage: Optional[str] = None):
        """
        Record token usage for a specific API call
        
        Args:
            model: The model name (e.g., 'gpt-4.1', 'gpt-5', 'o3')
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens
            total_tokens: Total tokens used
            stage: Optional stage name for categorization
        """
        with self._stats_lock:
            # Update total stats
            self.total_stats["input_tokens"] += input_tokens
            self.total_stats["output_tokens"] += output_tokens
            self.total_stats["total_tokens"] += total_tokens
            self.total_stats["api_calls"] += 1
            
            # Update model-specific stats
            if model not in self.model_stats:
                self.model_stats[model] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "api_calls": 0
                }
            
            self.model_stats[model]["input_tokens"] += input_tokens
            self.model_stats[model]["output_tokens"] += output_tokens
            self.model_stats[model]["total_tokens"] += total_tokens
            self.model_stats[model]["api_calls"] += 1
            
            # Update stage-specific stats if stage is provided
            if stage:
                if stage not in self.stage_stats:
                    self.stage_stats[stage] = {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "api_calls": 0,
                        "models_used": set()
                    }
                
                self.stage_stats[stage]["input_tokens"] += input_tokens
                self.stage_stats[stage]["output_tokens"] += output_tokens
                self.stage_stats[stage]["total_tokens"] += total_tokens
                self.stage_stats[stage]["api_calls"] += 1
                self.stage_stats[stage]["models_used"].add(model)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current token usage statistics"""
        with self._stats_lock:
            # Convert sets to lists for JSON serialization
            stage_stats_serializable = {}
            for stage, stats in self.stage_stats.items():
                stage_stats_serializable[stage] = {
                    **stats,
                    "models_used": list(stats["models_used"]) if "models_used" in stats else []
                }
            
            return {
                "total_stats": self.total_stats.copy(),
                "model_stats": self.model_stats.copy(),
                "stage_stats": stage_stats_serializable,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "duration_seconds": (
                    (self.end_time - self.start_time).total_seconds() 
                    if self.end_time and self.start_time else None
                )
            }
    
    def finalize(self):
        """Mark the tracking session as complete"""
        with self._stats_lock:
            self.end_time = datetime.now()
    
    def generate_report(self, format: str = "text") -> str:
        """
        Generate a usage report
        
        Args:
            format: 'text' or 'json'
        
        Returns:
            Formatted report string
        """
        self.finalize()
        stats = self.get_stats()
        
        if format == "json":
            return json.dumps(stats, indent=2, ensure_ascii=False)
        
        # Text format report
        lines = []
        lines.append("=" * 80)
        lines.append("TOKEN USAGE REPORT")
        lines.append("=" * 80)
        
        # Time information
        if stats["start_time"]:
            lines.append(f"Start Time: {stats['start_time']}")
        if stats["end_time"]:
            lines.append(f"End Time: {stats['end_time']}")
        if stats["duration_seconds"]:
            duration_min = stats["duration_seconds"] / 60
            lines.append(f"Duration: {duration_min:.2f} minutes")
        lines.append("")
        
        # Total statistics
        lines.append("TOTAL USAGE:")
        lines.append("-" * 40)
        total = stats["total_stats"]
        lines.append(f"  Total API Calls: {total['api_calls']:,}")
        lines.append(f"  Total Input Tokens: {total['input_tokens']:,}")
        lines.append(f"  Total Output Tokens: {total['output_tokens']:,}")
        lines.append(f"  Total Tokens: {total['total_tokens']:,}")
        
        # Calculate average tokens per call
        if total['api_calls'] > 0:
            avg_input = total['input_tokens'] / total['api_calls']
            avg_output = total['output_tokens'] / total['api_calls']
            avg_total = total['total_tokens'] / total['api_calls']
            lines.append(f"  Average Input Tokens per Call: {avg_input:,.0f}")
            lines.append(f"  Average Output Tokens per Call: {avg_output:,.0f}")
            lines.append(f"  Average Total Tokens per Call: {avg_total:,.0f}")
        lines.append("")
        
        # Per-model statistics
        if stats["model_stats"]:
            lines.append("USAGE BY MODEL:")
            lines.append("-" * 40)
            
            # Sort models by total tokens used
            sorted_models = sorted(
                stats["model_stats"].items(),
                key=lambda x: x[1]["total_tokens"],
                reverse=True
            )
            
            for model, model_stat in sorted_models:
                lines.append(f"\n  {model}:")
                lines.append(f"    API Calls: {model_stat['api_calls']:,}")
                lines.append(f"    Input Tokens: {model_stat['input_tokens']:,}")
                lines.append(f"    Output Tokens: {model_stat['output_tokens']:,}")
                lines.append(f"    Total Tokens: {model_stat['total_tokens']:,}")
                
                # Calculate percentage of total
                if total['total_tokens'] > 0:
                    percentage = (model_stat['total_tokens'] / total['total_tokens']) * 100
                    lines.append(f"    Percentage of Total: {percentage:.1f}%")
        
        # Per-stage statistics (if available)
        if stats["stage_stats"]:
            lines.append("")
            lines.append("USAGE BY STAGE:")
            lines.append("-" * 40)
            
            # Sort stages by total tokens used
            sorted_stages = sorted(
                stats["stage_stats"].items(),
                key=lambda x: x[1]["total_tokens"],
                reverse=True
            )
            
            for stage, stage_stat in sorted_stages:
                lines.append(f"\n  {stage}:")
                lines.append(f"    API Calls: {stage_stat['api_calls']:,}")
                lines.append(f"    Input Tokens: {stage_stat['input_tokens']:,}")
                lines.append(f"    Output Tokens: {stage_stat['output_tokens']:,}")
                lines.append(f"    Total Tokens: {stage_stat['total_tokens']:,}")
                if stage_stat.get("models_used"):
                    lines.append(f"    Models Used: {', '.join(stage_stat['models_used'])}")
        
        lines.append("")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def save_report(self, output_dir: str, filename: str = "token_usage_report"):
        """
        Save the usage report to files
        
        Args:
            output_dir: Directory to save the report
            filename: Base filename (without extension)
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Save text report
        text_report = self.generate_report(format="text")
        text_file = output_path / f"{filename}.txt"
        text_file.write_text(text_report, encoding="utf-8")
        
        # Save JSON report
        json_report = self.generate_report(format="json")
        json_file = output_path / f"{filename}.json"
        json_file.write_text(json_report, encoding="utf-8")
        
        print(f"\nToken usage reports saved to:")
        print(f"  - {text_file}")
        print(f"  - {json_file}")
        
        return str(text_file), str(json_file)


# Global instance getter
def get_token_tracker() -> TokenTracker:
    """Get the global TokenTracker instance"""
    return TokenTracker()