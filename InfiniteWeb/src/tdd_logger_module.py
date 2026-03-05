"""
TDD Logger Module
Separated logging functionality for TDD system
"""

import os
import json
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class LogLevel(Enum):
    """Log level enumeration"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TDDLogger:
    """Enhanced logger for TDD generation with multi-stage and multi-page support"""
    
    def __init__(self, output_dir: Optional[str] = None, 
                 log_level: str = "INFO"):
        """
        Initialize TDD Logger
        
        Args:
            output_dir: Directory for log files
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.output_dir = output_dir
        self.log_level = getattr(LogLevel, log_level.upper(), LogLevel.INFO)
        
        # Thread lock for parallel logging
        self.lock = threading.Lock()
        
        # Log storage
        self.logs = []
        self.stage_logs = {}
        
        # Current stage tracking
        self.current_stage = None
        self.stage_start_times = {}
        self.stage_end_times = {}
        
        # Stage directory mapping
        self.stage_directories = {}  # Map stage name to directory path
        self.current_stage_category = None  # prepare, backend, frontend
        
        # File paths
        self.log_file = None
        self.stage_files = {}
        
        # Multi-page stage tracking
        self.multi_page_stages = set()  # Track which stages are multi-page
        self.page_loggers = {}  # Store PageLogger instances
        self.current_multi_page_stage = None
        
        # Timing log file for parallel execution verification
        self.timing_file = None
        
        # LLM call tracking
        self.llm_call_counters = {}  # Per-stage call counters
        self.current_call_id = None
        
        # Setup logging
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration"""
        if self.output_dir:
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Always create main log file
            self.log_file = os.path.join(self.output_dir, "tdd_generation.log")
            self._write_to_file(self.log_file, f"TDD Generation Log - Started at {datetime.now()}\n")
            self._write_to_file(self.log_file, "=" * 80 + "\n")
            
            # Create timing log file for parallel execution verification
            # Only initialize timing file once (check if it already exists)
            self.timing_file = os.path.join(self.output_dir, "timing_log.txt")
            if not os.path.exists(self.timing_file):
                self._write_to_file(self.timing_file, f"Timing Log for Parallel Execution Verification\n")
                self._write_to_file(self.timing_file, f"Started at {datetime.now()}\n")
                self._write_to_file(self.timing_file, "=" * 80 + "\n")
    
    def start_stage(self, stage_name: str, category: str = None):
        """
        Start a new logging stage (single-page mode with folder structure)
        
        Args:
            stage_name: Name of the stage
            category: Stage category (prepare, backend, frontend)
        """
        # Determine category from stage name if not provided
        if category is None:
            category = self._get_stage_category(stage_name)
            
        with self.lock:
            self.current_stage = stage_name
            self.current_stage_category = category
            self.stage_start_times[stage_name] = datetime.now()
            
            # Initialize LLM call counter for this stage
            self.llm_call_counters[stage_name] = 0
            
            # Create stage folder without number prefix
            if self.output_dir:
                stage_folder = stage_name.lower().replace(' ', '_')
                if category:
                    stage_dir = os.path.join(self.output_dir, category, stage_folder)
                else:
                    stage_dir = os.path.join(self.output_dir, stage_folder)
                os.makedirs(stage_dir, exist_ok=True)
                self.stage_directories[stage_name] = stage_dir
                
                # Create the main stage log file in the folder
                stage_file = os.path.join(stage_dir, "stage.log")
                self.stage_files[stage_name] = stage_file
                self._write_to_file(stage_file, f"Stage: {stage_name}\n")
                self._write_to_file(stage_file, f"Category: {category}\n")
                self._write_to_file(stage_file, f"Started: {self.stage_start_times[stage_name]}\n")
                self._write_to_file(stage_file, "=" * 80 + "\n")
        
        # Log to main file (OUTSIDE the lock to avoid deadlock)
        self.log_info(f"{'='*60}")
        self.log_info(f"Stage Started: {stage_name} ({category})")
        self.log_info(f"Start Time: {self.stage_start_times[stage_name]}")
        self.log_info(f"{'='*60}")
    
    def end_stage(self, stage_name: str):
        """
        End a logging stage
        
        Args:
            stage_name: Name of the stage
        """
        duration = 0.0
        with self.lock:
            if stage_name in self.stage_start_times:
                self.stage_end_times[stage_name] = datetime.now()
                duration = (self.stage_end_times[stage_name] - self.stage_start_times[stage_name]).total_seconds()
                
                # Write to stage file
                if stage_name in self.stage_files:
                    stage_file = self.stage_files[stage_name]
                    self._write_to_file(stage_file, f"\nCompleted: {self.stage_end_times[stage_name]}\n")
                    self._write_to_file(stage_file, f"Duration: {duration:.2f} seconds\n")
            
            self.current_stage = None
        
        # Log stage completion (OUTSIDE the lock to avoid deadlock)
        if stage_name in self.stage_start_times:
            self.log_info(f"Stage Completed: {stage_name}")
            self.log_info(f"Duration: {duration:.2f} seconds")
            self.log_info(f"{'='*60}\n")
    
    def log(self, level: str, message: str, stage: Optional[str] = None):
        """
        Generic log method
        
        Args:
            level: Log level
            message: Log message
            stage: Optional stage name (uses current stage if not provided)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stage = stage or self.current_stage
        
        # Format log entry
        if stage:
            log_entry = f"[{timestamp}] [{level}] [{stage}] {message}"
        else:
            log_entry = f"[{timestamp}] [{level}] {message}"
        
        # Store in memory
        with self.lock:
            self.logs.append(log_entry)
            if stage:
                if stage not in self.stage_logs:
                    self.stage_logs[stage] = []
                self.stage_logs[stage].append(log_entry)
        
        # Print to console
        if level == "ERROR":
            print(f"❌ {log_entry}")
        elif level == "WARNING":
            print(f"⚠️ {log_entry}")
        else:
            print(log_entry)
        
        # Write to files
        self._write_log_to_files(log_entry, stage)
    
    def log_info(self, message: str, stage: Optional[str] = None):
        """Log info message"""
        if self._should_log(LogLevel.INFO):
            self.log("INFO", message, stage)
    
    def log_debug(self, message: str, stage: Optional[str] = None):
        """Log debug message"""
        if self._should_log(LogLevel.DEBUG):
            self.log("DEBUG", message, stage)
    
    def log_warning(self, message: str, stage: Optional[str] = None):
        """Log warning message"""
        if self._should_log(LogLevel.WARNING):
            self.log("WARNING", message, stage)
    
    def log_error(self, message: str, stage: Optional[str] = None):
        """Log error message"""
        if self._should_log(LogLevel.ERROR):
            self.log("ERROR", message, stage)
    
    def log_critical(self, message: str, stage: Optional[str] = None):
        """Log critical message"""
        if self._should_log(LogLevel.CRITICAL):
            self.log("CRITICAL", message, stage)
    
    def log_api_call(self, api_name: str, prompt: str, 
                     additional_args: Optional[Dict[str, Any]] = None,
                     stage: Optional[str] = None) -> str:
        """
        Log an API call
        
        Args:
            api_name: Name of the API being called
            prompt: The prompt being sent
            additional_args: Additional arguments to the API
            stage: Optional stage name
            
        Returns:
            call_id: Unique identifier for this API call
        """
        stage_name = stage or self.current_stage
        
        # Generate unique call ID for this LLM call
        call_id = None
        if stage_name:
            with self.lock:
                self.llm_call_counters[stage_name] = self.llm_call_counters.get(stage_name, 0) + 1
                call_id = f"call_{self.llm_call_counters[stage_name]:03d}"
        
        self.log_info("=" * 60, stage)
        self.log_info(f"API Call: {api_name}", stage)
        if stage_name and call_id:
            self.log_info(f"Call ID: {call_id}", stage)
        
        if additional_args:
            self.log_info(f"Additional Args: {json.dumps(additional_args, indent=2)}", stage)
        
        # Write prompt to separate input file AND stage.log
        self._log_prompt_to_files_only(prompt, stage)
        if call_id:
            self._log_llm_call_input(prompt, stage_name, call_id)
        
        return call_id
    
    def log_api_response(self, api_name: str, success: bool,
                        response: Optional[Any] = None,
                        error: Optional[str] = None,
                        usage_info: Optional[Dict[str, Any]] = None,
                        stage: Optional[str] = None,
                        call_id: Optional[str] = None):
        """
        Log an API response
        
        Args:
            api_name: Name of the API
            success: Whether the call was successful
            response: The response data
            error: Error message if failed
            usage_info: Token usage information
            stage: Optional stage name
            call_id: Optional call ID for this response
        """
        stage_name = stage or self.current_stage
        
        if success:
            self.log_info(f"✅ Success - API Response: {api_name}", stage)
            if call_id:
                self.log_info(f"Call ID: {call_id}", stage)
            if usage_info:
                self.log_info(f"Token Usage: {json.dumps(usage_info)}", stage)
            if response:
                # Write response to separate output file AND stage.log
                self._log_response_to_files_only(response, stage)
                if stage_name and call_id:
                    self._log_llm_call_output(response, stage_name, call_id)
        else:
            self.log_error(f"❌ Failed - API Response: {api_name}", stage)
            if call_id:
                self.log_info(f"Call ID: {call_id}", stage)
            if error:
                self.log_error(f"Error: {error}", stage)
                if stage_name and call_id:
                    self._log_llm_call_output(f"ERROR: {error}", stage_name, call_id)
    
    def log_exception(self, exception: Exception, context: str = "", 
                     stage: Optional[str] = None):
        """
        Log an exception with traceback
        
        Args:
            exception: The exception object
            context: Context where the exception occurred
            stage: Optional stage name
        """
        import traceback
        
        self.log_error(f"Exception in {context}: {str(exception)}", stage)
        self.log_error("Stack Trace:", stage)
        for line in traceback.format_exc().split('\n'):
            self.log_error(line, stage)
    
    def _should_log(self, level: LogLevel) -> bool:
        """Check if a message should be logged based on level"""
        level_values = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50
        }
        return level_values[level] >= level_values[self.log_level]
    
    def _write_log_to_files(self, log_entry: str, stage: Optional[str] = None):
        """Write log entry to appropriate files"""
        if not self.output_dir:
            return
        
        with self.lock:
            # Always write to main log
            if self.log_file:
                self._write_to_file(self.log_file, log_entry + '\n', append=True)
            
            # Always write to stage log if stage exists
            if stage and stage in self.stage_files:
                self._write_to_file(self.stage_files[stage], log_entry + '\n', append=True)
    
    def _log_prompt_to_files_only(self, prompt: str, stage: Optional[str] = None):
        """Write prompt to log files only, without console output"""
        if not self.output_dir:
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stage_name = stage or self.current_stage
        
        # Create log entries for prompt
        if stage_name:
            prompt_header = f"[{timestamp}] [INFO] [{stage_name}] Prompt:"
            separator = f"[{timestamp}] [INFO] [{stage_name}] {'-' * 40}"
        else:
            prompt_header = f"[{timestamp}] [INFO] Prompt:"
            separator = f"[{timestamp}] [INFO] {'-' * 40}"
        
        with self.lock:
            # Write to main log file
            if self.log_file:
                self._write_to_file(self.log_file, prompt_header + '\n', append=True)
                self._write_to_file(self.log_file, separator + '\n', append=True)
                for line in prompt.split('\n'):
                    if stage_name:
                        log_entry = f"[{timestamp}] [INFO] [{stage_name}] {line}"
                    else:
                        log_entry = f"[{timestamp}] [INFO] {line}"
                    self._write_to_file(self.log_file, log_entry + '\n', append=True)
                self._write_to_file(self.log_file, separator + '\n', append=True)
            
            # Write to stage log file if stage exists
            if stage_name and stage_name in self.stage_files:
                self._write_to_file(self.stage_files[stage_name], prompt_header + '\n', append=True)
                self._write_to_file(self.stage_files[stage_name], separator + '\n', append=True)
                for line in prompt.split('\n'):
                    log_entry = f"[{timestamp}] [INFO] [{stage_name}] {line}"
                    self._write_to_file(self.stage_files[stage_name], log_entry + '\n', append=True)
                self._write_to_file(self.stage_files[stage_name], separator + '\n', append=True)
    
    def _log_response_to_files_only(self, response: Any, stage: Optional[str] = None):
        """Write response content to log files only, without console output"""
        if not self.output_dir or not response:
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stage_name = stage or self.current_stage
        
        # Create log entries for response
        if stage_name:
            response_header = f"[{timestamp}] [DEBUG] [{stage_name}] Response Content:"
            separator = f"[{timestamp}] [DEBUG] [{stage_name}] {'-' * 40}"
        else:
            response_header = f"[{timestamp}] [DEBUG] Response Content:"
            separator = f"[{timestamp}] [DEBUG] {'-' * 40}"
        
        with self.lock:
            # Write to main log file
            if self.log_file:
                self._write_to_file(self.log_file, response_header + '\n', append=True)
                self._write_to_file(self.log_file, separator + '\n', append=True)
                
                if isinstance(response, str):
                    for line in response.split('\n'):
                        if stage_name:
                            log_entry = f"[{timestamp}] [DEBUG] [{stage_name}] {line}"
                        else:
                            log_entry = f"[{timestamp}] [DEBUG] {line}"
                        self._write_to_file(self.log_file, log_entry + '\n', append=True)
                else:
                    response_json = json.dumps(response, indent=2, ensure_ascii=False)
                    for line in response_json.split('\n'):
                        if stage_name:
                            log_entry = f"[{timestamp}] [DEBUG] [{stage_name}] {line}"
                        else:
                            log_entry = f"[{timestamp}] [DEBUG] {line}"
                        self._write_to_file(self.log_file, log_entry + '\n', append=True)
                
                self._write_to_file(self.log_file, separator + '\n', append=True)
            
            # Write to stage log file if stage exists
            if stage_name and stage_name in self.stage_files:
                self._write_to_file(self.stage_files[stage_name], response_header + '\n', append=True)
                self._write_to_file(self.stage_files[stage_name], separator + '\n', append=True)
                
                if isinstance(response, str):
                    for line in response.split('\n'):
                        log_entry = f"[{timestamp}] [DEBUG] [{stage_name}] {line}"
                        self._write_to_file(self.stage_files[stage_name], log_entry + '\n', append=True)
                else:
                    response_json = json.dumps(response, indent=2, ensure_ascii=False)
                    for line in response_json.split('\n'):
                        log_entry = f"[{timestamp}] [DEBUG] [{stage_name}] {line}"
                        self._write_to_file(self.stage_files[stage_name], log_entry + '\n', append=True)
                
                self._write_to_file(self.stage_files[stage_name], separator + '\n', append=True)
    
    def _write_to_file(self, filepath: str, content: str, append: bool = True):
        """Write content to file"""
        mode = 'a' if append else 'w'
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, mode, encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            print(f"Failed to write to log file {filepath}: {e}")
    
    def _get_stage_category(self, stage_name: str) -> str:
        """
        Determine the category of a stage based on its name
        
        Args:
            stage_name: Name of the stage
            
        Returns:
            Category: prepare, backend, or frontend
        """
        stage_lower = stage_name.lower().replace(' ', '_')
        
        # Prepare stages
        prepare_stages = {
            'generate_tasks', 'design_primary_architecture', 'extract_data_models',
            'design_interfaces'
        }
        
        # Backend stages
        backend_stages = {
            'generate_data', 'parallel_generation', 'validate_and_fix',
            'replace_data_images'
        }
        
        # Frontend stages
        frontend_stages = {
            'design_architecture', 'design_pages', 'analyze_design_image',
            'design_page_layouts', 'generate_page_framework', 'generate_pages',
            'replace_page_images', 'inject_data', 'generate_evaluators'
        }
        
        if stage_lower in prepare_stages:
            return 'prepare'
        elif stage_lower in backend_stages:
            return 'backend'
        elif stage_lower in frontend_stages:
            return 'frontend'
        else:
            # Default to prepare for unknown stages
            return 'prepare'
    
    def _log_llm_call_input(self, prompt: str, stage_name: str, call_id: str):
        """
        Log LLM call input to separate file
        
        Args:
            prompt: The input prompt
            stage_name: Name of the current stage
            call_id: Unique identifier for this call
        """
        if not self.output_dir or not stage_name or not call_id:
            return
            
        stage_dir = self.stage_directories.get(stage_name)
        if not stage_dir:
            return
            
        input_file = os.path.join(stage_dir, f"{call_id}_input.log")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = f"[{timestamp}] LLM Call Input\n"
        content += "=" * 80 + "\n"
        content += prompt + "\n"
        content += "=" * 80 + "\n"
        
        self._write_to_file(input_file, content, append=False)
    
    def _log_llm_call_output(self, response: Any, stage_name: str, call_id: str):
        """
        Log LLM call output to separate file
        
        Args:
            response: The API response
            stage_name: Name of the current stage
            call_id: Unique identifier for this call
        """
        if not self.output_dir or not stage_name or not call_id:
            return
            
        stage_dir = self.stage_directories.get(stage_name)
        if not stage_dir:
            return
            
        output_file = os.path.join(stage_dir, f"{call_id}_output.log")
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = f"[{timestamp}] LLM Call Output\n"
        content += "=" * 80 + "\n"
        
        if isinstance(response, str):
            content += response + "\n"
        else:
            content += json.dumps(response, indent=2, ensure_ascii=False) + "\n"
            
        content += "=" * 80 + "\n"
        
        self._write_to_file(output_file, content, append=False)
    
    def get_logs(self, stage: Optional[str] = None) -> List[str]:
        """
        Get logs for a specific stage or all logs
        
        Args:
            stage: Optional stage name
            
        Returns:
            List of log entries
        """
        with self.lock:
            if stage and stage in self.stage_logs:
                return self.stage_logs[stage].copy()
            return self.logs.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of logging session
        
        Returns:
            Dictionary with summary information
        """
        with self.lock:
            summary = {
                "total_logs": len(self.logs),
                "stages": {}
            }
            
            for stage in self.stage_start_times:
                stage_info = {
                    "start_time": self.stage_start_times[stage].isoformat(),
                    "log_count": len(self.stage_logs.get(stage, []))
                }
                
                if stage in self.stage_end_times:
                    stage_info["end_time"] = self.stage_end_times[stage].isoformat()
                    duration = (self.stage_end_times[stage] - self.stage_start_times[stage]).total_seconds()
                    stage_info["duration_seconds"] = duration
                
                summary["stages"][stage] = stage_info
            
            return summary
    
    def save_summary(self, filepath: Optional[str] = None):
        """
        Save logging summary to JSON file
        
        Args:
            filepath: Optional filepath (defaults to output_dir/summary.json)
        """
        if not filepath and self.output_dir:
            filepath = os.path.join(self.output_dir, "logging_summary.json")
        
        if filepath:
            summary = self.get_summary()
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            self.log_info(f"Logging summary saved to {filepath}")
    
    def log_step_start(self, step_name: str, pipeline: str):
        """
        Log the start of a pipeline step for parallel execution verification
        
        Args:
            step_name: Name of the step
            pipeline: Pipeline name (BACKEND/FRONTEND)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # Include milliseconds
        log_entry = f"[{timestamp}] [{pipeline.upper()}] [START] {step_name}\n"
        
        with self.lock:
            if self.timing_file:
                self._write_to_file(self.timing_file, log_entry, append=True)
        
        # Also log to main log for visibility
        self.log_info(f"📍 [{pipeline.upper()}] Started: {step_name}")
    
    def log_step_end(self, step_name: str, pipeline: str):
        """
        Log the end of a pipeline step for parallel execution verification
        
        Args:
            step_name: Name of the step
            pipeline: Pipeline name (BACKEND/FRONTEND)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # Include milliseconds
        log_entry = f"[{timestamp}] [{pipeline.upper()}] [END] {step_name}\n"
        
        with self.lock:
            if self.timing_file:
                self._write_to_file(self.timing_file, log_entry, append=True)
        
        # Also log to main log for visibility
        self.log_info(f"✅ [{pipeline.upper()}] Completed: {step_name}")
    
    def start_multi_page_stage(self, stage_name: str, category: str = None):
        """
        Start a new multi-page logging stage (creates a folder)
        
        Args:
            stage_name: Name of the stage
            category: Stage category (prepare, backend, frontend)
        """
        # Determine category from stage name if not provided
        if category is None:
            category = self._get_stage_category(stage_name)
            
        with self.lock:
            self.current_stage = stage_name
            self.current_multi_page_stage = stage_name
            self.current_stage_category = category
            self.stage_start_times[stage_name] = datetime.now()
            self.multi_page_stages.add(stage_name)
            
            # Initialize LLM call counter for this stage
            self.llm_call_counters[stage_name] = 0
            
            # Create stage folder without number prefix
            if self.output_dir:
                stage_folder = stage_name.lower().replace(' ', '_')
                if category:
                    stage_dir = os.path.join(self.output_dir, category, stage_folder)
                else:
                    stage_dir = os.path.join(self.output_dir, stage_folder)
                os.makedirs(stage_dir, exist_ok=True)
                self.stage_directories[stage_name] = stage_dir
                
                # Create main stage log file in the folder
                stage_file = os.path.join(stage_dir, "stage.log")
                self.stage_files[stage_name] = stage_file
                self._write_to_file(stage_file, f"Multi-Page Stage: {stage_name}\n")
                self._write_to_file(stage_file, f"Category: {category}\n")
                self._write_to_file(stage_file, f"Started: {self.stage_start_times[stage_name]}\n")
                self._write_to_file(stage_file, "=" * 80 + "\n")
        
        # Log to main file (OUTSIDE the lock to avoid deadlock)
        self.log_info(f"{'='*60}")
        self.log_info(f"Multi-Page Stage Started: {stage_name} ({category})")
        self.log_info(f"Start Time: {self.stage_start_times[stage_name]}")
        self.log_info(f"{'='*60}")
    
    def end_multi_page_stage(self, stage_name: str):
        """
        End a multi-page logging stage
        
        Args:
            stage_name: Name of the stage
        """
        duration = 0.0
        with self.lock:
            if stage_name in self.stage_start_times:
                self.stage_end_times[stage_name] = datetime.now()
                duration = (self.stage_end_times[stage_name] - self.stage_start_times[stage_name]).total_seconds()
                
                # Write to stage file
                if stage_name in self.stage_files:
                    stage_file = self.stage_files[stage_name]
                    self._write_to_file(stage_file, f"\nCompleted: {self.stage_end_times[stage_name]}\n")
                    self._write_to_file(stage_file, f"Duration: {duration:.2f} seconds\n")
                    
                    # Write summary of page processing
                    page_count = len([k for k in self.page_loggers if k.startswith(f"{stage_name}:")])
                    self._write_to_file(stage_file, f"Pages Processed: {page_count}\n")
            
            self.current_stage = None
            self.current_multi_page_stage = None
        
        # Log stage completion (OUTSIDE the lock to avoid deadlock)
        if stage_name in self.stage_start_times:
            self.log_info(f"Multi-Page Stage Completed: {stage_name}")
            self.log_info(f"Duration: {duration:.2f} seconds")
            self.log_info(f"{'='*60}\n")
    
    def for_page(self, page_name: str) -> 'PageLogger':
        """
        Create or get a page-specific logger for the current multi-page stage
        
        Args:
            page_name: Name of the page
            
        Returns:
            PageLogger instance for the specific page
        """
        if not self.current_multi_page_stage:
            raise RuntimeError("for_page() called outside of multi-page stage context")
        
        # Create unique key for this page in this stage
        page_key = f"{self.current_multi_page_stage}:{page_name}"
        
        # Return existing logger if already created
        if page_key in self.page_loggers:
            return self.page_loggers[page_key]
        
        # Create new page logger
        page_logger = PageLogger(
            parent=self,
            stage_name=self.current_multi_page_stage,
            page_name=page_name,
            stage_dir=self.stage_directories.get(self.current_multi_page_stage)
        )
        
        self.page_loggers[page_key] = page_logger
        return page_logger


class PageLogger:
    """Logger for individual pages within a multi-page stage"""
    
    def __init__(self, parent: TDDLogger, stage_name: str, page_name: str, 
                 stage_dir: Optional[str]):
        """
        Initialize page logger
        
        Args:
            parent: Parent TDDLogger instance
            stage_name: Name of the stage
            page_name: Name of the page
            stage_dir: Stage directory path
        """
        self.parent = parent
        self.stage_name = stage_name
        self.page_name = page_name
        self.stage_dir = stage_dir
        
        # Create page log file
        self.page_file = None
        if self.stage_dir:
            # Replace problematic characters in page name for filename
            safe_page_name = page_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('.', '_')
            self.page_file = os.path.join(self.stage_dir, f"{safe_page_name}.log")
            self._write_header()
    
    def _write_header(self):
        """Write header to page log file"""
        if self.page_file:
            with open(self.page_file, 'w', encoding='utf-8') as f:
                f.write(f"Page: {self.page_name}\n")
                f.write(f"Stage: {self.stage_name}\n")
                f.write(f"Started: {datetime.now()}\n")
                f.write("=" * 80 + "\n\n")
    
    def log_info(self, message: str):
        """Log info message for this page"""
        # Log to parent with page context
        self.parent.log_info(f"[{self.page_name}] {message}", stage=self.stage_name)
        
        # Also write to page-specific file
        if self.page_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [INFO] {message}\n"
            with open(self.page_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
    
    def log_error(self, message: str):
        """Log error message for this page"""
        # Log to parent with page context
        self.parent.log_error(f"[{self.page_name}] {message}", stage=self.stage_name)
        
        # Also write to page-specific file
        if self.page_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [ERROR] {message}\n"
            with open(self.page_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
    
    def log_warning(self, message: str):
        """Log warning message for this page"""
        # Log to parent with page context
        self.parent.log_warning(f"[{self.page_name}] {message}", stage=self.stage_name)
        
        # Also write to page-specific file
        if self.page_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [WARNING] {message}\n"
            with open(self.page_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
    
    def log_debug(self, message: str):
        """Log debug message for this page"""
        # Log to parent with page context
        self.parent.log_debug(f"[{self.page_name}] {message}", stage=self.stage_name)
        
        # Also write to page-specific file if debug level
        if self.page_file and self.parent._should_log(LogLevel.DEBUG):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [DEBUG] {message}\n"
            with open(self.page_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
    
    def _log_prompt_to_file_only(self, prompt: str):
        """Write prompt to page log file only, without console output"""
        if self.page_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.page_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] [INFO] Prompt:\n")
                f.write(f"[{timestamp}] [INFO] {'-' * 40}\n")
                for line in prompt.split('\n'):
                    f.write(f"[{timestamp}] [INFO] {line}\n")
                f.write(f"[{timestamp}] [INFO] {'-' * 40}\n")
    
    def _log_response_to_file_only(self, response: Any):
        """Write response content to page log file only, without console output"""
        if self.page_file and response and self.parent._should_log(LogLevel.DEBUG):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.page_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] [DEBUG] Response Content:\n")
                f.write(f"[{timestamp}] [DEBUG] {'-' * 40}\n")
                
                if isinstance(response, str):
                    for line in response.split('\n'):
                        f.write(f"[{timestamp}] [DEBUG] {line}\n")
                else:
                    response_json = json.dumps(response, indent=2, ensure_ascii=False)
                    for line in response_json.split('\n'):
                        f.write(f"[{timestamp}] [DEBUG] {line}\n")
                
                f.write(f"[{timestamp}] [DEBUG] {'-' * 40}\n")
    
    def log_api_call(self, api_name: str, prompt: str, 
                     additional_args: Optional[Dict[str, Any]] = None):
        """Log an API call for this page"""
        self.log_info("=" * 60)
        self.log_info(f"API Call: {api_name}")
        
        if additional_args:
            self.log_info(f"Additional Args: {json.dumps(additional_args, indent=2)}")
        
        # Only write prompt to log file, not to console
        self._log_prompt_to_file_only(prompt)
    
    def log_api_response(self, api_name: str, success: bool,
                        response: Optional[Any] = None,
                        error: Optional[str] = None,
                        usage_info: Optional[Dict[str, Any]] = None):
        """Log an API response for this page"""
        if success:
            self.log_info(f"✅ Success - API Response: {api_name}")
            if usage_info:
                self.log_info(f"Token Usage: {json.dumps(usage_info)}")
            if response:
                # Only write response to log file, not to console
                self._log_response_to_file_only(response)
        else:
            self.log_error(f"❌ Failed - API Response: {api_name}")
            if error:
                self.log_error(f"Error: {error}")