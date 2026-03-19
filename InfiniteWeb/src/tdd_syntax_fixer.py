"""
TDD Syntax Fixer
Independent tool for detecting and fixing HTML/JavaScript syntax errors using LLM
"""

import os
import json
import asyncio
import argparse
import subprocess
import tempfile
import re
from typing import Dict, Any, List, Tuple, Optional

import html5lib
from bs4 import BeautifulSoup

from llm_caller import call_openai_api_json_async, call_openai_api_json_async_with_endpoint
from tdd_logger_module import TDDLogger


# Incremental fix prompt - returns only the patches needed
INCREMENTAL_FIX_PROMPT = """Fix the following {file_type} syntax errors using search-replace patches.

File: {filename}
Errors detected:
{errors_json}

Current content (with line numbers for reference):
```{code_block}
{numbered_content}
```

Return ONLY the patches needed to fix errors in JSON format:
{{
  "replacements": [
    {{
      "old": "exact string to find (include enough context to be unique)",
      "new": "replacement string with fix applied"
    }}
  ]
}}

Rules:
1. Each "old" must be an EXACT substring from the file (WITHOUT line numbers)
2. Include enough surrounding context to make "old" unique in the file
3. Keep patches minimal - only change what's needed to fix the error
4. If multiple errors are in the same area, combine into one patch
5. Do NOT include patches for code that has no errors
6. For HTML entity errors like &display=swap, change to &amp;display=swap
"""


class TDDSyntaxFixer:
    """Detects and fixes HTML/JavaScript syntax errors using LLM"""

    def __init__(self, logger: TDDLogger = None, max_fix_iterations: int = 3,
                 model: str = None, reasoning_effort: str = "minimal"):
        """
        Initialize TDD Syntax Fixer

        Args:
            logger: TDDLogger instance for logging (optional)
            max_fix_iterations: Maximum number of fix iterations (default: 3)
            model: Model to use for LLM calls (default: None, uses llm_caller default)
            reasoning_effort: Reasoning effort level (default: "minimal", options: "minimal", "medium", "high")
        """
        self.logger = logger
        self.max_fix_iterations = max_fix_iterations
        self.model = model
        self.reasoning_effort = reasoning_effort

    # ================== Public Methods ==================

    async def fix_directory(self, directory: str, output_dir: str = None) -> Dict[str, Any]:
        """
        Fix all HTML and JS files in a directory

        Args:
            directory: Input directory containing HTML/JS files
            output_dir: Output directory for fixed files (defaults to input directory)

        Returns:
            Dictionary with fix results
        """
        if self.logger:
            self.logger.start_stage("Syntax Fix")
            self.logger.log_info(f"Scanning directory: {directory}")

        output_dir = output_dir or directory
        os.makedirs(output_dir, exist_ok=True)

        results = {
            "files_processed": 0,
            "files_fixed": 0,
            "files_failed": 0,
            "files_no_errors": 0,
            "details": []
        }

        # Find all HTML and JS files
        for filename in os.listdir(directory):
            if filename.endswith(('.html', '.js')):
                file_path = os.path.join(directory, filename)
                output_path = os.path.join(output_dir, filename)

                result = await self.fix_file(file_path, output_path)
                results["details"].append(result)
                results["files_processed"] += 1

                if result["status"] == "fixed":
                    results["files_fixed"] += 1
                elif result["status"] == "failed":
                    results["files_failed"] += 1
                else:
                    results["files_no_errors"] += 1

        if self.logger:
            self.logger.log_info(f"Completed: {results['files_processed']} files processed")
            self.logger.log_info(f"  Fixed: {results['files_fixed']}")
            self.logger.log_info(f"  Failed: {results['files_failed']}")
            self.logger.log_info(f"  No errors: {results['files_no_errors']}")
            self.logger.end_stage("Syntax Fix")

        return results

    async def fix_directory_recursive(self, directory: str, output_dir: str = None,
                                       in_place: bool = True, max_concurrent: int = 5) -> Dict[str, Any]:
        """
        Fix all HTML and JS files in a directory and its subdirectories with parallel processing

        Args:
            directory: Input directory containing website subdirectories
            output_dir: Output directory (defaults to in-place modification)
            in_place: If True, modify files in place; if False, copy to output_dir
            max_concurrent: Maximum number of concurrent website directories to process

        Returns:
            Dictionary with fix results for all subdirectories
        """
        if self.logger:
            self.logger.start_stage("Syntax Fix Recursive")
            self.logger.log_info(f"Scanning directory recursively: {directory}")
            self.logger.log_info(f"Max concurrent directories: {max_concurrent}")

        # Collect all website directories
        website_dirs = []
        for root, dirs, files in os.walk(directory):
            target_files = [f for f in files if f.endswith(('.html', '.js'))]
            if target_files:
                rel_path = os.path.relpath(root, directory)
                website_dirs.append({
                    "root": root,
                    "rel_path": rel_path,
                    "dir_name": rel_path if rel_path != '.' else os.path.basename(directory),
                    "files": target_files
                })

        if self.logger:
            self.logger.log_info(f"Found {len(website_dirs)} directories with {sum(len(d['files']) for d in website_dirs)} files")

        # Process directories in parallel with semaphore
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_directory(dir_info):
            async with semaphore:
                return await self._fix_single_directory(
                    dir_info, directory, output_dir, in_place
                )

        # Run all directories in parallel
        dir_results_list = await asyncio.gather(
            *[process_directory(d) for d in website_dirs],
            return_exceptions=True
        )

        # Aggregate results
        results = {
            "directories_processed": 0,
            "files_processed": 0,
            "files_fixed": 0,
            "files_failed": 0,
            "files_no_errors": 0,
            "by_directory": {}
        }

        for dir_info, dir_result in zip(website_dirs, dir_results_list):
            if isinstance(dir_result, Exception):
                if self.logger:
                    self.logger.log_error(f"Error processing {dir_info['dir_name']}: {dir_result}")
                continue

            results["directories_processed"] += 1
            results["files_processed"] += dir_result["files_processed"]
            results["files_fixed"] += dir_result["files_fixed"]
            results["files_failed"] += dir_result["files_failed"]
            results["files_no_errors"] += dir_result["files_no_errors"]
            results["by_directory"][dir_info["dir_name"]] = dir_result

        if self.logger:
            self.logger.log_info(f"\n{'='*60}")
            self.logger.log_info(f"TOTAL: {results['directories_processed']} directories, {results['files_processed']} files")
            self.logger.log_info(f"  Fixed: {results['files_fixed']}")
            self.logger.log_info(f"  Failed: {results['files_failed']}")
            self.logger.log_info(f"  No errors: {results['files_no_errors']}")
            self.logger.log_info(f"{'='*60}")
            self.logger.end_stage("Syntax Fix Recursive")

        return results

    async def fix_directory_recursive_multi_endpoint(
        self,
        directory: str,
        endpoints: List[str],
        output_dir: str = None,
        in_place: bool = True,
        max_concurrent_per_endpoint: int = 3,
        max_concurrent_files: int = 20
    ) -> Dict[str, Any]:
        """
        Fix all HTML and JS files using multiple endpoints in parallel

        Websites are distributed across endpoints, then processed concurrently within each endpoint.

        Args:
            directory: Input directory containing website subdirectories
            endpoints: List of Azure OpenAI endpoint URLs
            output_dir: Output directory (defaults to in-place modification)
            in_place: If True, modify files in place; if False, copy to output_dir
            max_concurrent_per_endpoint: Maximum concurrent directories per endpoint

        Returns:
            Dictionary with fix results for all subdirectories
        """
        if self.logger:
            self.logger.start_stage("Syntax Fix Multi-Endpoint")
            self.logger.log_info(f"Scanning directory: {directory}")
            self.logger.log_info(f"Using {len(endpoints)} endpoints")
            self.logger.log_info(f"Max concurrent per endpoint: {max_concurrent_per_endpoint}")

        # Collect all website directories
        website_dirs = []
        for root, dirs, files in os.walk(directory):
            target_files = [f for f in files if f.endswith(('.html', '.js'))]
            if target_files:
                rel_path = os.path.relpath(root, directory)
                website_dirs.append({
                    "root": root,
                    "rel_path": rel_path,
                    "dir_name": rel_path if rel_path != '.' else os.path.basename(directory),
                    "files": target_files
                })

        total_files = sum(len(d['files']) for d in website_dirs)
        print(f"Found {len(website_dirs)} directories with {total_files} files")
        print(f"Distributing across {len(endpoints)} endpoints...")

        if self.logger:
            self.logger.log_info(f"Found {len(website_dirs)} directories with {total_files} files")

        # Distribute directories across endpoints (round-robin)
        endpoint_tasks = {ep: [] for ep in endpoints}
        for i, dir_info in enumerate(website_dirs):
            endpoint = endpoints[i % len(endpoints)]
            endpoint_tasks[endpoint].append(dir_info)

        # Print distribution
        for i, (ep, dirs) in enumerate(endpoint_tasks.items()):
            ep_short = ep.split('//')[1].split('.')[0]  # Extract short name
            print(f"  Endpoint {i+1} ({ep_short}): {len(dirs)} websites")

        # Create tasks for each endpoint
        async def process_endpoint_group(endpoint: str, dir_list: List[Dict]):
            """Process all directories assigned to one endpoint"""
            semaphore = asyncio.Semaphore(max_concurrent_per_endpoint)

            async def process_single(dir_info):
                async with semaphore:
                    return await self._fix_single_directory_with_endpoint(
                        dir_info, directory, output_dir, in_place, endpoint, max_concurrent_files
                    )

            return await asyncio.gather(
                *[process_single(d) for d in dir_list],
                return_exceptions=True
            )

        # Run all endpoint groups in parallel
        print(f"\nStarting parallel processing across {len(endpoints)} endpoints...")
        all_results = await asyncio.gather(
            *[process_endpoint_group(ep, dirs) for ep, dirs in endpoint_tasks.items()],
            return_exceptions=True
        )

        # Aggregate results
        results = {
            "directories_processed": 0,
            "files_processed": 0,
            "files_fixed": 0,
            "files_failed": 0,
            "files_no_errors": 0,
            "endpoints_used": len(endpoints),
            "by_directory": {}
        }

        for endpoint_idx, (endpoint, dir_list) in enumerate(endpoint_tasks.items()):
            endpoint_results = all_results[endpoint_idx]

            if isinstance(endpoint_results, Exception):
                if self.logger:
                    self.logger.log_error(f"Endpoint {endpoint} failed: {endpoint_results}")
                continue

            for dir_info, dir_result in zip(dir_list, endpoint_results):
                if isinstance(dir_result, Exception):
                    if self.logger:
                        self.logger.log_error(f"Error processing {dir_info['dir_name']}: {dir_result}")
                    continue

                results["directories_processed"] += 1
                results["files_processed"] += dir_result["files_processed"]
                results["files_fixed"] += dir_result["files_fixed"]
                results["files_failed"] += dir_result["files_failed"]
                results["files_no_errors"] += dir_result["files_no_errors"]
                results["by_directory"][dir_info["dir_name"]] = dir_result

        if self.logger:
            self.logger.log_info(f"\n{'='*60}")
            self.logger.log_info(f"TOTAL: {results['directories_processed']} directories, {results['files_processed']} files")
            self.logger.log_info(f"  Fixed: {results['files_fixed']}")
            self.logger.log_info(f"  Failed: {results['files_failed']}")
            self.logger.log_info(f"  No errors: {results['files_no_errors']}")
            self.logger.log_info(f"{'='*60}")
            self.logger.end_stage("Syntax Fix Multi-Endpoint")

        return results

    async def _fix_single_directory_with_endpoint(
        self,
        dir_info: Dict,
        base_dir: str,
        output_dir: str,
        in_place: bool,
        endpoint: str,
        max_concurrent_files: int = 20
    ) -> Dict[str, Any]:
        """
        Fix all files in a single directory using a specific endpoint (parallel file processing)

        Args:
            dir_info: Dictionary with directory information
            base_dir: Base directory path
            output_dir: Output directory
            in_place: Whether to modify in place
            endpoint: Specific Azure OpenAI endpoint to use
            max_concurrent_files: Maximum concurrent files to process within directory

        Returns:
            Dictionary with fix results for this directory
        """
        root = dir_info["root"]
        rel_path = dir_info["rel_path"]
        dir_name = dir_info["dir_name"]
        target_files = dir_info["files"]

        ep_short = endpoint.split('//')[1].split('.')[0]
        print(f"[{ep_short}] Processing: {dir_name} ({len(target_files)} files)")

        # Prepare file tasks
        file_tasks = []
        for filename in target_files:
            file_path = os.path.join(root, filename)

            # Determine output path
            if in_place:
                out_path = file_path
            else:
                out_path = os.path.join(output_dir, rel_path, filename)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)

            file_tasks.append((file_path, out_path))

        # Process files in parallel with semaphore
        file_semaphore = asyncio.Semaphore(max_concurrent_files)

        async def process_file(file_path, out_path):
            async with file_semaphore:
                return await self._fix_file_with_endpoint(file_path, out_path, endpoint)

        # Run all file fixes in parallel
        results_list = await asyncio.gather(
            *[process_file(fp, op) for fp, op in file_tasks],
            return_exceptions=True
        )

        # Aggregate results
        dir_results = {
            "files_processed": 0,
            "files_fixed": 0,
            "files_failed": 0,
            "files_no_errors": 0,
            "endpoint": endpoint,
            "details": []
        }

        for result in results_list:
            if isinstance(result, Exception):
                dir_results["files_failed"] += 1
                dir_results["details"].append({"status": "error", "error": str(result)})
            else:
                dir_results["details"].append(result)
                dir_results["files_processed"] += 1

                if result["status"] == "fixed":
                    dir_results["files_fixed"] += 1
                elif result["status"] == "failed":
                    dir_results["files_failed"] += 1
                else:
                    dir_results["files_no_errors"] += 1

        print(f"[{ep_short}] Done {dir_name}: {dir_results['files_fixed']} fixed, {dir_results['files_failed']} failed, {dir_results['files_no_errors']} ok")

        return dir_results

    async def _fix_file_with_endpoint(self, file_path: str, output_path: str, endpoint: str) -> Dict[str, Any]:
        """
        Fix syntax errors in a single file using a specific endpoint

        Args:
            file_path: Path to the input file
            output_path: Path for the fixed file
            endpoint: Specific Azure OpenAI endpoint to use

        Returns:
            Dictionary with fix result for this file
        """
        filename = os.path.basename(file_path)

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Preprocess: remove NULL characters
        content = self._preprocess_content(content)

        # Detect errors
        errors = self._detect_errors(file_path, content)
        errors_before = len(errors)

        if not errors:
            return {
                "file": filename,
                "status": "no_errors",
                "errors_before": 0,
                "errors_after": 0,
                "iterations": 0
            }

        # Fix with retry using specific endpoint
        fixed_content, success, iterations = await self._fix_with_retry_endpoint(
            file_path, content, endpoint
        )

        # Save fixed file
        if success or fixed_content != content:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)

        # Count remaining errors
        final_errors = self._detect_errors(file_path, fixed_content)
        errors_after = len(final_errors)

        status = "fixed" if errors_after == 0 else "failed"

        return {
            "file": filename,
            "status": status,
            "errors_before": errors_before,
            "errors_after": errors_after,
            "iterations": iterations
        }

    async def _fix_with_retry_endpoint(
        self,
        file_path: str,
        content: str,
        endpoint: str
    ) -> Tuple[str, bool, int]:
        """
        Fix errors with retry mechanism using specific endpoint

        Args:
            file_path: Path to the file
            content: File content
            endpoint: Specific Azure OpenAI endpoint to use

        Returns:
            Tuple of (fixed_content, success, iterations_used)
        """
        current_content = content

        for iteration in range(self.max_fix_iterations):
            errors = self._detect_errors(file_path, current_content)

            if not errors:
                return current_content, True, iteration + 1

            # Call LLM to fix using specific endpoint
            fixed_content = await self._call_llm_fix_with_endpoint(
                file_path, current_content, errors, endpoint
            )

            if fixed_content and fixed_content != current_content:
                current_content = fixed_content
            else:
                break

        # Final check
        final_errors = self._detect_errors(file_path, current_content)
        return current_content, len(final_errors) == 0, self.max_fix_iterations

    async def _call_llm_fix_with_endpoint(
        self,
        file_path: str,
        content: str,
        errors: List[Dict],
        endpoint: str
    ) -> Optional[str]:
        """
        Call LLM to fix syntax errors using a specific endpoint with incremental patches

        Args:
            file_path: Path to the file
            content: File content
            errors: List of detected errors
            endpoint: Specific Azure OpenAI endpoint to use

        Returns:
            Fixed content or None if failed
        """
        ext = os.path.splitext(file_path)[1].lower()
        filename = os.path.basename(file_path)

        file_type_map = {'.html': 'HTML', '.js': 'JavaScript'}
        code_block_map = {'.html': 'html', '.js': 'javascript'}

        file_type = file_type_map.get(ext, 'code')
        code_block = code_block_map.get(ext, 'text')

        # Add line numbers to content for LLM reference
        numbered_lines = []
        for i, line in enumerate(content.split('\n'), 1):
            numbered_lines.append(f"{i:4d}| {line}")
        numbered_content = '\n'.join(numbered_lines)

        # Use incremental fix prompt
        prompt = INCREMENTAL_FIX_PROMPT.format(
            file_type=file_type,
            filename=filename,
            errors_json=json.dumps(errors, indent=2),
            code_block=code_block,
            numbered_content=numbered_content
        )

        try:
            response, usage = await call_openai_api_json_async_with_endpoint(
                [{"role": "user", "content": prompt}],
                endpoint=endpoint,
                max_tokens=32000,  # Incremental fix only needs small output
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Parse response
            if isinstance(response, str):
                parsed = json.loads(response)
            else:
                parsed = response

            replacements = parsed.get("replacements", [])

            if not replacements:
                return None

            # Apply replacements
            modified, success, failed = self._apply_replacements(content, replacements)

            # Return modified content only if at least one patch succeeded
            return modified if success > 0 else None

        except Exception as e:
            if self.logger:
                self.logger.log_error(f"LLM fix failed on {endpoint}: {str(e)}")
            return None

    async def _fix_single_directory(self, dir_info: Dict, base_dir: str,
                                     output_dir: str, in_place: bool) -> Dict[str, Any]:
        """
        Fix all files in a single directory

        Args:
            dir_info: Dictionary with directory information
            base_dir: Base directory path
            output_dir: Output directory
            in_place: Whether to modify in place

        Returns:
            Dictionary with fix results for this directory
        """
        root = dir_info["root"]
        rel_path = dir_info["rel_path"]
        dir_name = dir_info["dir_name"]
        target_files = dir_info["files"]

        print(f"[START] Processing: {dir_name} ({len(target_files)} files)")

        dir_results = {
            "files_processed": 0,
            "files_fixed": 0,
            "files_failed": 0,
            "files_no_errors": 0,
            "details": []
        }

        for filename in target_files:
            file_path = os.path.join(root, filename)

            # Determine output path
            if in_place:
                out_path = file_path
            else:
                out_path = os.path.join(output_dir, rel_path, filename)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)

            result = await self.fix_file(file_path, out_path)
            dir_results["details"].append(result)
            dir_results["files_processed"] += 1

            if result["status"] == "fixed":
                dir_results["files_fixed"] += 1
            elif result["status"] == "failed":
                dir_results["files_failed"] += 1
            else:
                dir_results["files_no_errors"] += 1

        print(f"[DONE] {dir_name}: {dir_results['files_fixed']} fixed, {dir_results['files_failed']} failed, {dir_results['files_no_errors']} no errors")

        return dir_results

    async def fix_file(self, file_path: str, output_path: str = None) -> Dict[str, Any]:
        """
        Fix syntax errors in a single file

        Args:
            file_path: Path to the input file
            output_path: Path for the fixed file (defaults to input path, can be a directory)

        Returns:
            Dictionary with fix result for this file
        """
        filename = os.path.basename(file_path)

        # Handle output path - if it's a directory (or looks like one), append filename
        if output_path:
            # Check if path ends with separator or is an existing directory
            is_dir = os.path.isdir(output_path) or output_path.endswith(os.sep) or output_path.endswith('/')
            if is_dir:
                os.makedirs(output_path, exist_ok=True)
                output_path = os.path.join(output_path, filename)
            else:
                # Treat as file path, ensure parent directory exists
                parent_dir = os.path.dirname(output_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
        else:
            output_path = file_path

        if self.logger:
            self.logger.log_info(f"Processing: {filename}")

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Preprocess: remove illegal control characters
        original_content = content
        content = self._preprocess_content(content)
        preprocessed_changed = (content != original_content)

        # Detect errors
        errors = self._detect_errors(file_path, content)
        errors_before = len(errors)

        if not errors:
            # Save if preprocess cleaned control chars even though no other errors
            if preprocessed_changed:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                if self.logger:
                    self.logger.log_info(f"  Cleaned control characters in {filename}")
            elif self.logger:
                self.logger.log_info(f"  No errors found in {filename}")
            return {
                "file": filename,
                "status": "cleaned" if preprocessed_changed else "no_errors",
                "errors_before": 0,
                "errors_after": 0,
                "iterations": 0
            }

        if self.logger:
            self.logger.log_info(f"  Found {errors_before} errors in {filename}")

        # Fix with retry
        fixed_content, success, iterations = await self._fix_with_retry(file_path, content)

        # Save fixed file
        if success or fixed_content != content:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)

        # Count remaining errors
        final_errors = self._detect_errors(file_path, fixed_content)
        errors_after = len(final_errors)

        status = "fixed" if errors_after == 0 else "failed"

        if self.logger:
            if status == "fixed":
                self.logger.log_info(f"  Fixed {filename} in {iterations} iteration(s)")
            else:
                self.logger.log_warning(f"  Failed to fully fix {filename}, {errors_after} errors remain")

        return {
            "file": filename,
            "status": status,
            "errors_before": errors_before,
            "errors_after": errors_after,
            "iterations": iterations
        }

    async def detect_only(self, path: str) -> Dict[str, Any]:
        """
        Detect errors without fixing (dry-run mode)

        Args:
            path: File or directory path

        Returns:
            Dictionary with detection results
        """
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            errors = self._detect_errors(path, content)
            return {
                "file": os.path.basename(path),
                "errors": errors,
                "error_count": len(errors)
            }
        else:
            results = {"files": [], "total_errors": 0}
            for filename in os.listdir(path):
                if filename.endswith(('.html', '.js')):
                    file_path = os.path.join(path, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    errors = self._detect_errors(file_path, content)
                    results["files"].append({
                        "file": filename,
                        "errors": errors,
                        "error_count": len(errors)
                    })
                    results["total_errors"] += len(errors)
            return results

    async def detect_recursive(self, directory: str) -> Dict[str, Any]:
        """
        Detect errors in all files recursively without fixing

        Args:
            directory: Directory to scan recursively

        Returns:
            Dictionary with detection results
        """
        results = {
            "directories_scanned": 0,
            "files_scanned": 0,
            "files_with_errors": 0,
            "total_errors": 0,
            "by_directory": {}
        }

        for root, dirs, files in os.walk(directory):
            target_files = [f for f in files if f.endswith(('.html', '.js'))]

            if not target_files:
                continue

            rel_path = os.path.relpath(root, directory)
            dir_name = rel_path if rel_path != '.' else os.path.basename(directory)

            dir_results = {
                "files_scanned": 0,
                "files_with_errors": 0,
                "total_errors": 0,
                "files": []
            }

            for filename in target_files:
                file_path = os.path.join(root, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                errors = self._detect_errors(file_path, content)

                dir_results["files_scanned"] += 1
                if errors:
                    dir_results["files_with_errors"] += 1
                    dir_results["total_errors"] += len(errors)
                    dir_results["files"].append({
                        "file": filename,
                        "error_count": len(errors),
                        "errors": errors
                    })

            results["directories_scanned"] += 1
            results["files_scanned"] += dir_results["files_scanned"]
            results["files_with_errors"] += dir_results["files_with_errors"]
            results["total_errors"] += dir_results["total_errors"]

            if dir_results["files_with_errors"] > 0:
                results["by_directory"][dir_name] = dir_results

        return results

    # ================== Preprocessing Methods ==================

    def _preprocess_content(self, content: str) -> str:
        """
        Preprocess file content to remove illegal control characters and fix
        common deterministic errors.

        1. Remove illegal control chars (0x00-0x08, 0x0b, 0x0c, 0x0e-0x1f)
           that LLMs emit via broken Unicode escapes.
        2. Fix bare & in href/src URLs (LLMs always generate & instead of &amp;
           in Google Fonts and similar URLs, causing expected-named-entity errors).

        Args:
            content: Raw file content

        Returns:
            Cleaned content
        """
        import re
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
        # Fix bare & in href/src attribute URLs (loop for multiple & in one URL)
        prev = None
        while prev != content:
            prev = content
            content = re.sub(
                r'((?:href|src)=["\'][^"\']*?)&(?!amp;|lt;|gt;|quot;|#)([a-zA-Z])',
                r'\1&amp;\2',
                content
            )
        return content

    # ================== Detection Methods ==================

    def _detect_errors(self, file_path: str, content: str) -> List[Dict[str, Any]]:
        """
        Detect syntax errors based on file type

        Args:
            file_path: Path to the file (used to determine type)
            content: File content

        Returns:
            List of error dictionaries
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext == '.html':
            return self._detect_html_errors(content)
        elif ext == '.js':
            return self._detect_js_errors(content)

        return []

    def _detect_html_errors(self, content: str) -> List[Dict[str, Any]]:
        """
        Detect HTML syntax errors using html5lib

        Args:
            content: HTML content

        Returns:
            List of error dictionaries
        """
        errors = []

        # Parse HTML with html5lib
        parser = html5lib.HTMLParser(tree=html5lib.getTreeBuilder("etree"), strict=False)
        parser.parse(content)

        # Collect HTML parsing errors
        for error in parser.errors:
            if isinstance(error, tuple) and len(error) >= 2:
                position = error[0]
                error_type = error[1] if len(error) > 1 else "unknown"

                line = position[0] if isinstance(position, tuple) else 0
                column = position[1] if isinstance(position, tuple) else 0

                errors.append({
                    "type": "html",
                    "line": line,
                    "column": column,
                    "message": str(error_type)
                })

        # Extract and check inline JavaScript
        inline_js_list = self._extract_inline_js(content)
        for js_content, start_line in inline_js_list:
            js_errors = self._detect_js_errors(js_content)
            for err in js_errors:
                # Adjust line number to reflect position in HTML file
                err["line"] = (err.get("line", 0) or 0) + start_line - 1
                err["type"] = "inline_js"
                errors.append(err)

        return errors

    def _detect_js_errors(self, content: str) -> List[Dict[str, Any]]:
        """
        Detect JavaScript syntax errors using node --check

        This uses Node.js built-in syntax checking which supports modern ES2020+ syntax
        including optional chaining (?.) and nullish coalescing (??)

        Args:
            content: JavaScript content

        Returns:
            List of error dictionaries
        """
        if not content or not content.strip():
            return []

        # Create temporary file for node to check
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
                f.write(content)
                temp_path = f.name

            result = subprocess.run(
                ['node', '--check', temp_path],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                return []

            # Parse error message from node
            error_msg = result.stderr.strip()
            line_num = 0
            column = 0

            # Try to extract line number from error message
            # Format: /path/file.js:123
            line_match = re.search(r':(\d+)\s*$', error_msg.split('\n')[0])
            if line_match:
                line_num = int(line_match.group(1))

            return [{
                "type": "js",
                "line": line_num,
                "column": column,
                "message": error_msg[:200] if len(error_msg) > 200 else error_msg
            }]

        except subprocess.TimeoutExpired:
            return [{
                "type": "js",
                "line": 0,
                "column": 0,
                "message": "Syntax check timeout"
            }]
        except FileNotFoundError:
            # Node.js not installed, fall back to basic check
            return [{
                "type": "js",
                "line": 0,
                "column": 0,
                "message": "Node.js not found for syntax checking"
            }]
        except Exception as e:
            return [{
                "type": "js",
                "line": 0,
                "column": 0,
                "message": f"Syntax check error: {str(e)}"
            }]
        finally:
            # Clean up temp file
            try:
                if 'temp_path' in locals():
                    os.unlink(temp_path)
            except:
                pass

    def _extract_inline_js(self, html_content: str) -> List[Tuple[str, int]]:
        """
        Extract inline JavaScript from HTML

        Args:
            html_content: HTML content

        Returns:
            List of tuples (js_content, start_line_number)
        """
        result = []

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Find all script tags without src attribute (inline scripts)
            for script in soup.find_all('script', src=False):
                if script.string:
                    js_content = script.string

                    # Calculate start line number
                    # Find the position of this script content in original HTML
                    script_pos = html_content.find(js_content)
                    if script_pos >= 0:
                        start_line = html_content[:script_pos].count('\n') + 1
                    else:
                        start_line = 1

                    result.append((js_content, start_line))
        except Exception as e:
            if self.logger:
                self.logger.log_warning(f"Failed to extract inline JS: {str(e)}")

        return result

    # ================== Fix Methods ==================

    @staticmethod
    def _find_fuzzy(content: str, old: str) -> Optional[str]:
        """Find `old` in `content` using a fallback chain of matching strategies.

        Returns the actual substring from `content` that matches, or None.
        Strategies (tried in order):
          1. Exact match
          2. Line-trimmed: each line .strip() compared
          3. Whitespace-normalized: all whitespace collapsed to single space
          4. Block-anchor: first/last line anchors + similarity threshold
        """
        # Strategy 1: Exact match
        if old in content:
            return old

        old_lines = old.split('\n')
        content_lines = content.split('\n')

        # Strategy 2: Line-trimmed match
        search_trimmed = [l.strip() for l in old_lines]
        while search_trimmed and not search_trimmed[-1]:
            search_trimmed.pop()
        if len(search_trimmed) >= 1:
            for i in range(len(content_lines) - len(search_trimmed) + 1):
                candidate_lines = content_lines[i:i + len(search_trimmed)]
                if [l.strip() for l in candidate_lines] == search_trimmed:
                    match = '\n'.join(candidate_lines)
                    if content.count(match) == 1:
                        return match

        # Strategy 3: Whitespace-normalized match
        def normalize_ws(s):
            return re.sub(r'\s+', ' ', s).strip()
        old_norm = normalize_ws(old)
        if len(old_norm) >= 10:
            for i in range(len(content_lines)):
                for length in range(1, min(len(content_lines) - i + 1, len(old_lines) + 5)):
                    candidate = '\n'.join(content_lines[i:i + length])
                    if normalize_ws(candidate) == old_norm:
                        if content.count(candidate) == 1:
                            return candidate

        # Strategy 4: Block-anchor match (first/last line trim-match, middle lines similar)
        if len(search_trimmed) >= 2:
            first_anchor = search_trimmed[0]
            last_anchor = search_trimmed[-1]
            candidates = []
            for i in range(len(content_lines)):
                if content_lines[i].strip() != first_anchor:
                    continue
                # Search for last anchor within a reasonable range
                max_end = min(len(content_lines), i + len(search_trimmed) + 3)
                for j in range(i + 1, max_end):
                    if content_lines[j].strip() != last_anchor:
                        continue
                    candidate = '\n'.join(content_lines[i:j + 1])
                    if content.count(candidate) == 1:
                        candidates.append(candidate)
            if len(candidates) == 1:
                return candidates[0]

        return None

    def _apply_replacements(self, content: str, replacements: List[Dict]) -> Tuple[str, int, int]:
        """
        Apply search-replace patches to content using fuzzy matching fallback chain.

        Args:
            content: Original file content
            replacements: List of {old, new} replacement dictionaries

        Returns:
            Tuple[str, int, int]: (modified_content, successful_count, failed_count)
        """
        modified = content
        success = 0
        failed = 0

        for r in replacements:
            old = r.get("old", "")
            new = r.get("new", "")

            if not old:
                failed += 1
                continue

            match = self._find_fuzzy(modified, old)
            if match is not None:
                modified = modified.replace(match, new, 1)
                success += 1
            else:
                failed += 1
                if self.logger:
                    preview = old[:80].replace('\n', '\\n')
                    self.logger.log_warning(f"  Patch failed: could not find '{preview}...'")

        return modified, success, failed

    async def _fix_with_retry(self, file_path: str, content: str) -> Tuple[str, bool, int]:
        """
        Fix errors with retry mechanism

        Args:
            file_path: Path to the file
            content: File content

        Returns:
            Tuple of (fixed_content, success, iterations_used)
        """
        current_content = content
        filename = os.path.basename(file_path)

        for iteration in range(self.max_fix_iterations):
            errors = self._detect_errors(file_path, current_content)

            if not errors:
                return current_content, True, iteration + 1

            if self.logger:
                self.logger.log_info(f"  Iteration {iteration + 1}/{self.max_fix_iterations}: {len(errors)} errors")

            # Call LLM to fix
            fixed_content = await self._call_llm_fix(file_path, current_content, errors)

            if fixed_content and fixed_content != current_content:
                current_content = fixed_content
            else:
                if self.logger:
                    self.logger.log_warning(f"  LLM fix returned no changes on iteration {iteration + 1}")
                break

        # Final check
        final_errors = self._detect_errors(file_path, current_content)
        return current_content, len(final_errors) == 0, self.max_fix_iterations

    async def _call_llm_fix(self, file_path: str, content: str, errors: List[Dict]) -> Optional[str]:
        """
        Call LLM to fix syntax errors using incremental patches

        Args:
            file_path: Path to the file
            content: File content
            errors: List of detected errors

        Returns:
            Fixed content or None if failed
        """
        ext = os.path.splitext(file_path)[1].lower()
        filename = os.path.basename(file_path)

        file_type_map = {'.html': 'HTML', '.js': 'JavaScript'}
        code_block_map = {'.html': 'html', '.js': 'javascript'}

        file_type = file_type_map.get(ext, 'code')
        code_block = code_block_map.get(ext, 'text')

        # Add line numbers to content for LLM reference
        numbered_lines = []
        for i, line in enumerate(content.split('\n'), 1):
            numbered_lines.append(f"{i:4d}| {line}")
        numbered_content = '\n'.join(numbered_lines)

        # Use incremental fix prompt
        prompt = INCREMENTAL_FIX_PROMPT.format(
            file_type=file_type,
            filename=filename,
            errors_json=json.dumps(errors, indent=2),
            code_block=code_block,
            numbered_content=numbered_content
        )

        # Log API call
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Fix Syntax (Incremental)",
                prompt,
                additional_args={
                    "file": filename,
                    "error_count": len(errors),
                    "max_tokens": 32000  # Incremental fix uses fewer tokens
                }
            )

        try:
            response, usage = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                max_tokens=32000,  # Incremental fix only needs small output
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log API response
            if self.logger:
                self.logger.log_api_response(
                    "Fix Syntax (Incremental)",
                    success=True,
                    response=response,
                    usage_info=usage,
                    call_id=call_id
                )

            # Parse response
            if isinstance(response, str):
                parsed = json.loads(response)
            else:
                parsed = response

            replacements = parsed.get("replacements", [])

            if not replacements:
                if self.logger:
                    self.logger.log_warning(f"  No replacements returned for {filename}")
                return None

            # Apply replacements
            modified, success, failed = self._apply_replacements(content, replacements)

            if self.logger:
                self.logger.log_info(f"  Patches: {success} applied, {failed} failed")

            # Return modified content only if at least one patch succeeded
            return modified if success > 0 else None

        except Exception as e:
            if self.logger:
                self.logger.log_error(f"LLM fix failed: {str(e)}")
                self.logger.log_api_response(
                    "Fix Syntax (Incremental)",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            return None

    # ================== Save Methods ==================

    def save_results(self, results: Dict[str, Any], output_path: str):
        """
        Save fix results to JSON file

        Args:
            results: Results dictionary
            output_path: Path to save results
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        if self.logger:
            self.logger.log_info(f"Results saved to: {output_path}")


async def main():
    """Command line interface for TDD Syntax Fixer"""
    parser = argparse.ArgumentParser(
        description='TDD Syntax Fixer - Fix HTML/JavaScript syntax errors using LLM',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tdd_syntax_fixer.py results/generated/
  python tdd_syntax_fixer.py results/generated/index.html
  python tdd_syntax_fixer.py results/generated/ --dry-run
  python tdd_syntax_fixer.py results/generated/ -o results/fixed/
  python tdd_syntax_fixer.py results/20251124_160655/ --recursive
  python tdd_syntax_fixer.py results/20251124_160655/ --recursive --config config/running_settings/config_simple_4.1.json
        """
    )

    parser.add_argument('path', help='File or directory to fix')
    parser.add_argument('--output', '-o', help='Output directory (defaults to input location)')
    parser.add_argument('--max-iterations', '-m', type=int, default=3,
                        help='Maximum fix iterations (default: 3)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Only detect errors, do not fix')
    parser.add_argument('--recursive', '-r', action='store_true',
                        help='Recursively process all subdirectories')
    parser.add_argument('--concurrent', '-c', type=int, default=5,
                        help='Max concurrent directories per endpoint (default: 5)')
    parser.add_argument('--file-concurrent', '-f', type=int, default=20,
                        help='Max concurrent files per directory (default: 20)')
    parser.add_argument('--config', help='Config file with endpoints list (enables multi-endpoint parallel processing)')
    parser.add_argument('--log-dir', '-l', help='Directory for log files')
    parser.add_argument('--model', default='gpt-4.1', help='Model to use (e.g., gpt-4.1, gpt-5, o4-mini)')
    parser.add_argument('--reasoning-effort', choices=['minimal', 'medium', 'high'], default='minimal',
                        help='Reasoning effort level (default: minimal)')

    args = parser.parse_args()

    # Load config if provided
    endpoints = None
    if args.config:
        with open(args.config, 'r') as f:
            config = json.load(f)
            endpoints = config.get('endpoints', [])
            print(f"Loaded {len(endpoints)} endpoints from config")

    # Initialize logger if log directory specified
    logger = None
    if args.log_dir:
        os.makedirs(args.log_dir, exist_ok=True)
        logger = TDDLogger(output_dir=args.log_dir, log_level="INFO")

    # Initialize fixer
    fixer = TDDSyntaxFixer(
        logger=logger,
        max_fix_iterations=args.max_iterations,
        model=args.model,
        reasoning_effort=args.reasoning_effort
    )

    # Run
    if args.dry_run:
        print("Running in dry-run mode (detect only)...")
        if args.recursive:
            result = await fixer.detect_recursive(args.path)
        else:
            result = await fixer.detect_only(args.path)
    elif os.path.isfile(args.path):
        result = await fixer.fix_file(args.path, args.output)
    elif args.recursive and endpoints:
        # Multi-endpoint parallel processing
        print(f"Running multi-endpoint recursive fix on: {args.path}")
        print(f"  Endpoints: {len(endpoints)}, Concurrent dirs/endpoint: {args.concurrent}, Concurrent files/dir: {args.file_concurrent}")
        in_place = args.output is None
        result = await fixer.fix_directory_recursive_multi_endpoint(
            args.path, endpoints,
            output_dir=args.output,
            in_place=in_place,
            max_concurrent_per_endpoint=args.concurrent,
            max_concurrent_files=args.file_concurrent
        )
    elif args.recursive:
        print(f"Running recursive fix on: {args.path} (max {args.concurrent} concurrent)")
        in_place = args.output is None
        result = await fixer.fix_directory_recursive(
            args.path, args.output, in_place=in_place, max_concurrent=args.concurrent
        )
    else:
        result = await fixer.fix_directory(args.path, args.output)

    # Output results
    print("\n" + "=" * 60)
    print("Results:")
    print("=" * 60)
    # For recursive results, show summary only
    if args.recursive and "by_directory" in result:
        summary = {k: v for k, v in result.items() if k != "by_directory"}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nDetailed results saved to: {args.output or args.path}/syntax_fix_results.json")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # Save results
    if not args.dry_run:
        output_dir = args.output or (os.path.dirname(args.path) if os.path.isfile(args.path) else args.path)
        results_path = os.path.join(output_dir, "syntax_fix_results.json")
        fixer.save_results(result, results_path)


if __name__ == "__main__":
    asyncio.run(main())
