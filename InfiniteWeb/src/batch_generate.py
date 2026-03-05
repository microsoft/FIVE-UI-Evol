#!/usr/bin/env python3
"""
Batch generator for TDD websites with concurrent generation support
Reads websites from config/website_seeds_template.json and generates them all
"""

import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime
import traceback
import asyncio
import argparse
from typing import List, Tuple, Dict
import time
import random

def load_websites_config(config_path):
    """Load websites configuration from JSON file"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('websites', [])
    except Exception as e:
        print(f"Error loading websites config: {e}")
        return []


def load_websites_from_jsonl(jsonl_path):
    """Load websites configuration from JSONL file with task extraction"""
    websites = []

    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)

                    # Extract instruction as website name
                    website_name = data.get('instruction', f'Website {line_num}')

                    # Extract tasks from ui_instruct
                    custom_task_names = []
                    ui_instruct = data.get('ui_instruct', [])
                    for task_item in ui_instruct:
                        task_text = task_item.get('task', '')
                        if task_text:
                            custom_task_names.append(task_text)

                    # Use image_path from JSONL file, fallback to default if not provided
                    image_path = data.get('image_path', 'resource/default.png')

                    websites.append({
                        'name': website_name,
                        'image_path': image_path,
                        'custom_task_names': custom_task_names,
                        'id': data.get('id', f'{line_num:06d}')  # Store the ID for resume functionality
                    })

                except json.JSONDecodeError as e:
                    print(f"Error parsing line {line_num}: {e}")
                    continue

    except Exception as e:
        print(f"Error loading JSONL file: {e}")
        return []

    return websites

def check_validation_failure(website_folder_path):
    """Check if validation failed due to max iterations reached"""
    validation_log_path = os.path.join(website_folder_path, 'logs', 'backend', 'validate_and_fix', 'stage.log')

    if not os.path.exists(validation_log_path):
        return False

    try:
        with open(validation_log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for max iterations failure marker
        return "Max iterations (8) reached. Some tests may still be failing." in content
    except Exception as e:
        print(f"Error reading validation log {validation_log_path}: {e}")
        return False

def check_website_completion(website_folder_path):
    """Check if a website generation is completed by examining timing_log.txt"""
    timing_log_path = os.path.join(website_folder_path, 'logs', 'timing_log.txt')

    if not os.path.exists(timing_log_path):
        return False

    try:
        with open(timing_log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for both required completion markers
        backend_complete = '[BACKEND] [END] Validate and Fix' in content
        frontend_complete = '[FRONTEND] [END] Fix Syntax' in content

        # If both stages are complete, check if validation failed
        if backend_complete and frontend_complete:
            # If validation failed, consider the website as incomplete
            if check_validation_failure(website_folder_path):
                return False
            return True

        return False
    except Exception as e:
        print(f"Error reading timing log {timing_log_path}: {e}")
        return False


def get_current_stage(website_dir: str) -> dict:
    """
    Read current execution stage from timing_log.txt

    Returns:
        dict: {
            'mode': 'prepare' | 'parallel',
            'prepare': str | None,       # Prepare stage name
            'prepare_start': float | None,  # Prepare stage start timestamp
            'backend': str | None,       # Backend current stage (None = not started, '---' = completed)
            'backend_start': float | None,  # Backend stage start timestamp
            'frontend': str | None,      # Frontend current stage
            'frontend_start': float | None  # Frontend stage start timestamp
        }
    """
    timing_log = os.path.join(website_dir, 'logs', 'timing_log.txt')
    if not os.path.exists(timing_log):
        return {'mode': 'prepare', 'prepare': 'Starting...', 'prepare_start': None,
                'backend': None, 'backend_start': None, 'frontend': None, 'frontend_start': None}

    try:
        with open(timing_log, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Parse all records
        backend_stage = None
        backend_start = None
        frontend_stage = None
        frontend_start = None
        prepare_stage = None
        prepare_start = None
        backend_done = False
        frontend_done = False

        for line in lines:
            line = line.strip()
            # Parse timestamp from line start (format: [2026-01-24 09:18:20.597] [PIPELINE] ...)
            timestamp = None
            if len(line) > 24 and line[0] == '[' and line[5] == '-' and line[8] == '-':
                try:
                    ts_str = line[1:24]  # Extract "2026-01-24 09:18:20.597"
                    timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f").timestamp()
                except:
                    pass

            if '[BACKEND]' in line:
                if '[START]' in line:
                    backend_stage = line.split('[START]')[-1].strip()[:20]
                    backend_start = timestamp
                elif '[END]' in line:
                    stage_name = line.split('[END]')[-1].strip()
                    if stage_name == backend_stage:
                        backend_stage = None  # Current stage ended
                        backend_start = None
                    if 'Validate and Fix' in line:
                        backend_done = True
            elif '[FRONTEND]' in line:
                if '[START]' in line:
                    frontend_stage = line.split('[START]')[-1].strip()[:20]
                    frontend_start = timestamp
                elif '[END]' in line:
                    stage_name = line.split('[END]')[-1].strip()
                    if stage_name == frontend_stage:
                        frontend_stage = None
                        frontend_start = None
                    if 'Fix Syntax' in line or 'Generate Evaluators' in line:
                        frontend_done = True
            elif '[PREPARE]' in line or ('[START]' in line and '[BACKEND]' not in line and '[FRONTEND]' not in line):
                if '[START]' in line:
                    prepare_stage = line.split('[START]')[-1].strip()[:20]
                    prepare_start = timestamp
                elif '[END]' in line:
                    prepare_stage = None
                    prepare_start = None

        # Determine mode
        if backend_stage or frontend_stage or backend_done or frontend_done:
            return {
                'mode': 'parallel',
                'prepare': None,
                'prepare_start': None,
                'backend': '---' if backend_done else (backend_stage or 'Processing...'),
                'backend_start': backend_start if not backend_done else None,
                'frontend': '---' if frontend_done else (frontend_stage or 'Processing...'),
                'frontend_start': frontend_start if not frontend_done else None
            }
        else:
            return {
                'mode': 'prepare',
                'prepare': prepare_stage or 'Starting...',
                'prepare_start': prepare_start,
                'backend': None,
                'backend_start': None,
                'frontend': None,
                'frontend_start': None
            }
    except:
        return {'mode': 'prepare', 'prepare': 'Processing...', 'prepare_start': None,
                'backend': None, 'backend_start': None, 'frontend': None, 'frontend_start': None}


def find_failed_websites(batch_folder, jsonl_path):
    """Find failed websites that need to be retried from a previous batch"""
    failed_websites = []
    
    if not os.path.exists(batch_folder):
        print(f"Batch folder does not exist: {batch_folder}")
        return failed_websites
    
    # Load the original JSONL to get website information by ID
    jsonl_websites = {}
    if jsonl_path:
        websites = load_websites_from_jsonl(jsonl_path)
        for website in websites:
            jsonl_websites[website['id']] = website
    
    # Scan all website folders in the batch directory
    try:
        for folder_name in os.listdir(batch_folder):
            folder_path = os.path.join(batch_folder, folder_name)
            
            # Skip files and non-website folders
            if not os.path.isdir(folder_path) or folder_name == 'batch_results.json':
                continue
            
            # Extract index from folder name (format: index_name)
            if '_' not in folder_name:
                continue
                
            try:
                folder_index = folder_name.split('_')[0]
                website_id = f"{int(folder_index):06d}"  # Convert to 6-digit ID format
                
                # Check if this website generation failed
                if not check_website_completion(folder_path):
                    # Find corresponding website info from JSONL
                    if website_id in jsonl_websites:
                        failed_website = jsonl_websites[website_id].copy()
                        failed_website['failed_folder'] = folder_path
                        failed_websites.append(failed_website)
                        print(f"Found failed website: {folder_name} (ID: {website_id})")
                    else:
                        print(f"Warning: No JSONL entry found for folder {folder_name} (ID: {website_id})")
                        
            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse folder name {folder_name}: {e}")
                continue
                
    except Exception as e:
        print(f"Error scanning batch folder {batch_folder}: {e}")
    
    return failed_websites

async def update_stage_periodically(website_index, output_dir, status_dict, status_lock, stop_event, max_concurrent):
    """Periodically update website's current stage"""
    while not stop_event.is_set():
        await asyncio.sleep(2)  # Update every 2 seconds
        stage = get_current_stage(output_dir)
        async with status_lock:
            if website_index in status_dict and '🔄' in status_dict[website_index]['status']:
                status_dict[website_index]['stage'] = stage
                print_status(status_dict, max_concurrent)


async def generate_single_website_async(website_config, tdd_config_path, base_output_dir,
                                        semaphore, status_lock, status_dict, website_index,
                                        is_resume=False, max_regeneration_attempts=3, max_concurrent=10):
    """Generate a single website asynchronously using tdd_generator.py"""
    website_name = website_config['name']
    image_path = website_config['image_path']
    custom_task_names = website_config.get('custom_task_names', [])

    # Update status to waiting
    async with status_lock:
        status_dict[website_index] = {'name': website_name, 'status': '⏳ Waiting'}
        print_status(status_dict, max_concurrent)

    async with semaphore:  # Control concurrency
        # Determine output directory
        if is_resume and 'failed_folder' in website_config:
            # In resume mode, reuse the existing folder but clean it
            output_dir = website_config['failed_folder']

            # Clean the failed folder (keep folder structure but remove generated files)
            try:
                import shutil
                if os.path.exists(output_dir):
                    # Remove all contents and recreate empty directory
                    shutil.rmtree(output_dir)
                    os.makedirs(output_dir, exist_ok=True)
                    print(f"Cleaned failed folder: {output_dir}")
            except Exception as e:
                print(f"Warning: Could not clean failed folder {output_dir}: {e}")
        else:
            # Create output directory with numbered layer: <timestamp>/<index>_<website_name>
            safe_name = website_name.replace(' ', '_').replace('/', '_')

            # website_name might be too long for filesystem, truncate if necessary
            if len(safe_name) > 20:
                safe_name = safe_name[:20]

            index_folder = f"{website_index + 1}"
            output_dir = os.path.join(base_output_dir, index_folder+"_"+safe_name)

        os.makedirs(output_dir, exist_ok=True)

        # Regeneration loop
        for attempt in range(max_regeneration_attempts):
            # Update status based on attempt number
            async with status_lock:
                task_start_time = time.time()
                if attempt == 0:
                    status_dict[website_index] = {'name': website_name, 'status': '🔄 Generating', 'task_start': task_start_time}
                else:
                    # Preserve original start time on retry
                    prev_start = status_dict.get(website_index, {}).get('task_start', task_start_time)
                    status_dict[website_index] = {'name': website_name, 'status': f'🔄 Regenerating (attempt {attempt + 1}/{max_regeneration_attempts})', 'task_start': prev_start}
                print_status(status_dict, max_concurrent)

            # Build command
            cmd = [
                sys.executable,  # Use current Python interpreter
                'src/tdd_generator.py',
                '--config', tdd_config_path,
                '--website-type', website_name,
                '--design-image', image_path,
                '--output-dir', output_dir
            ]

            # Add custom tasks if provided
            if custom_task_names:
                cmd.extend(['--custom-tasks', json.dumps(custom_task_names, ensure_ascii=False)])

            # Create stop event and stage update task
            stop_event = asyncio.Event()
            stage_task = asyncio.create_task(
                update_stage_periodically(website_index, output_dir, status_dict, status_lock, stop_event, max_concurrent)
            )

            try:
                # Set UTF-8 encoding for subprocess to avoid encoding issues
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'

                start_time = datetime.now()

                # Run the generator asynchronously with redirected output
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )

                # Wait for process to complete and read stderr
                _, stderr = await process.communicate()

                # Save stderr to log file if any
                if stderr:
                    stderr_log = os.path.join(output_dir, 'logs', 'stderr.log')
                    os.makedirs(os.path.dirname(stderr_log), exist_ok=True)
                    with open(stderr_log, 'wb') as f:
                        f.write(stderr)

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()

                if process.returncode == 0:
                    # Check if validation failed
                    if check_validation_failure(output_dir):
                        # Validation failed, need to regenerate
                        stop_event.set()
                        await stage_task
                        if attempt < max_regeneration_attempts - 1:
                            # Clean the folder for regeneration
                            import shutil
                            if os.path.exists(output_dir):
                                shutil.rmtree(output_dir)
                                os.makedirs(output_dir, exist_ok=True)
                            continue  # Try again
                        else:
                            # Max attempts reached
                            stop_event.set()
                            await stage_task
                            async with status_lock:
                                status_dict[website_index] = {'name': website_name, 'status': '❌ Validation Failed'}
                                print_status(status_dict, max_concurrent)
                            return False, f"Validation failed after {max_regeneration_attempts} attempts", duration, output_dir

                    # Success - no validation failure
                    # Stop stage update task
                    stop_event.set()
                    await stage_task

                    async with status_lock:
                        if attempt > 0:
                            status_dict[website_index] = {'name': website_name, 'status': f'✅ Completed (retry {attempt + 1})'}
                        else:
                            status_dict[website_index] = {'name': website_name, 'status': '✅ Completed'}
                        print_status(status_dict, max_concurrent)
                    return True, "Success", duration, output_dir
                else:
                    # Process failed
                    stop_event.set()
                    await stage_task
                    if attempt < max_regeneration_attempts - 1:
                        # Clean the folder for regeneration
                        import shutil
                        if os.path.exists(output_dir):
                            shutil.rmtree(output_dir)
                            os.makedirs(output_dir, exist_ok=True)
                        continue  # Try again
                    else:
                        # Extract error message from stderr
                        error_msg = ""
                        if stderr:
                            stderr_text = stderr.decode('utf-8', errors='ignore')
                            # Find the last ERROR line
                            for line in stderr_text.split('\n')[::-1]:
                                if '[ERROR]' in line and 'Stack Trace' not in line and 'Traceback' not in line:
                                    # Extract error description part
                                    error_msg = line.split('[ERROR]')[-1].strip()[:60]
                                    break
                        async with status_lock:
                            status_dict[website_index] = {
                                'name': website_name,
                                'status': '❌ Failed',
                                'error': error_msg or f"Exit code {process.returncode}"
                            }
                            print_status(status_dict, max_concurrent)
                        return False, f"Failed with return code {process.returncode}", duration, output_dir

            except Exception as e:
                # Exception occurred
                stop_event.set()
                await stage_task
                if attempt < max_regeneration_attempts - 1:
                    # Clean the folder for regeneration
                    import shutil
                    if os.path.exists(output_dir):
                        shutil.rmtree(output_dir)
                        os.makedirs(output_dir, exist_ok=True)
                    continue  # Try again
                else:
                    async with status_lock:
                        status_dict[website_index] = {'name': website_name, 'status': '❌ Error'}
                        print_status(status_dict, max_concurrent)
                    return False, str(e), 0, output_dir

        # Should not reach here
        return False, "Max regeneration attempts reached", 0, output_dir

def format_duration(seconds: float) -> str:
    """Format duration in seconds to a readable string"""
    if seconds is None:
        return ""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def print_status(status_dict, max_concurrent=10):
    """Print concise real-time status with BE/FE progress"""
    # Clear screen and move to top
    print("\033[2J\033[H", end='')

    now = time.time()

    # Statistics
    total = len(status_dict)
    running = [(idx, v) for idx, v in status_dict.items() if '🔄' in v['status']]
    completed = sum(1 for v in status_dict.values() if '✅' in v['status'])
    failed = sum(1 for v in status_dict.values() if '❌' in v['status'])
    waiting = sum(1 for v in status_dict.values() if '⏳' in v['status'])

    # Header
    print("=" * 80)
    print(f"RUNNING ({len(running)}/{total})")
    print("=" * 80)

    # Only show running websites
    for idx, item in sorted(running, key=lambda x: x[0]):
        name = item['name'][:20].ljust(20)
        stage_info = item.get('stage', {})

        # Calculate total elapsed time for this task
        task_start = item.get('task_start')
        total_elapsed = format_duration(now - task_start) if task_start else ""

        if isinstance(stage_info, dict):
            if stage_info.get('mode') == 'parallel':
                # Parallel stage: show BE and FE with duration
                be = stage_info.get('backend', '...')[:12].ljust(12)
                fe = stage_info.get('frontend', '...')[:12].ljust(12)
                be_start = stage_info.get('backend_start')
                fe_start = stage_info.get('frontend_start')
                be_dur = format_duration(now - be_start) if be_start else ""
                fe_dur = format_duration(now - fe_start) if fe_start else ""
                be_str = f"{be} {be_dur:>6}" if be_dur else be
                fe_str = f"{fe} {fe_dur:>6}" if fe_dur else fe
                print(f"[{idx+1:2d}] {name} BE:{be_str} | FE:{fe_str} | Total:{total_elapsed:>7}")
            else:
                # Prepare stage with duration
                prep = stage_info.get('prepare', 'Starting...')[:25].ljust(25)
                prep_start = stage_info.get('prepare_start')
                prep_dur = format_duration(now - prep_start) if prep_start else ""
                print(f"[{idx+1:2d}] {name} {prep} {prep_dur} | Total:{total_elapsed:>7}")
        else:
            # Compatibility with old format
            print(f"[{idx+1:2d}] {name} {str(stage_info)[:30] if stage_info else 'Starting...'} | Total:{total_elapsed:>7}")

    # If none running, show waiting items
    if not running:
        waiting_items = [(idx, v) for idx, v in status_dict.items() if '⏳' in v['status']][:5]
        for idx, item in waiting_items:
            name = item['name'][:20].ljust(20)
            print(f"[{idx+1:2d}] {name} Waiting...")

    # Bottom progress
    print()
    print(f"Progress: Completed {completed + failed}/{total} | Running {len(running)} | Waiting {waiting}")
    if failed > 0:
        print(f"         (Success: {completed}, Failed: {failed})")
        # Show failed items with error messages
        failed_items = [(idx, v) for idx, v in status_dict.items() if '❌' in v['status']]
        for idx, item in failed_items[:5]:  # Show max 5 failed items
            name = item['name'][:20].ljust(20)
            error = item.get('error', 'Unknown error')[:45]
            print(f"  [{idx+1:2d}] {name} {error}")
    print("=" * 80)

    sys.stdout.flush()

async def run_concurrent_generation(websites, tdd_config_path, output_dir, max_concurrent, timestamp, is_resume=False):
    """Run concurrent website generation"""
    semaphore = asyncio.Semaphore(max_concurrent)
    status_lock = asyncio.Lock()
    status_dict = {}

    # Create tasks for all websites
    tasks = []
    for i, website in enumerate(websites):
        task = generate_single_website_async(
            website, tdd_config_path, output_dir,
            semaphore, status_lock, status_dict, i,
            is_resume, max_concurrent=max_concurrent
        )
        tasks.append(task)

    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)

    # Clear status display and return results
    print("\033[2J\033[H")  # Clear screen

    # Convert results to expected format
    formatted_results = []
    for i, (success, message, duration, website_output_dir) in enumerate(results):
        formatted_results.append({
            'website': websites[i]['name'],
            'success': success,
            'message': message,
            'duration': duration,
            'output_dir': website_output_dir
        })

    return formatted_results

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Batch generate TDD websites with concurrent support')
    parser.add_argument('--concurrent', type=int, default=3,
                       help='Maximum number of concurrent generations (default: 3)')
    parser.add_argument('--config', type=str, default='config/config_template.json',
                       help='TDD configuration file path')
    parser.add_argument('--websites-config', type=str, default='config/website_seeds_template.json',
                       help='Websites configuration file path (JSON format)')
    parser.add_argument('--jsonl-input', type=str, default=None,
                       help='JSONL input file with websites and tasks (overrides --websites-config)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Limit the number of websites to generate (default: no limit)')
    parser.add_argument('--resume', type=str, default=None,
                       help='Resume from a previous batch generation folder by specifying the batch folder path (e.g., results/batch_generated/20240101_120000)')
    return parser.parse_args()

async def main_async():
    """Main async batch generation function"""
    # Set UTF-8 encoding for console output
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    # Parse command line arguments
    args = parse_arguments()
    
    print("=" * 80)
    print("TDD Batch Website Generator (Concurrent Mode)")
    print("=" * 80)
    
    # Configuration paths from arguments
    tdd_config_path = args.config
    base_output_dir = "results/batch_generated"
    max_concurrent = args.concurrent

    # Create timestamp for this batch (or reuse existing for resume mode)
    if args.resume:
        output_dir = args.resume
        timestamp = os.path.basename(args.resume)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(base_output_dir, timestamp)

    print(f"\nConfiguration:")

    # Handle resume mode
    if args.resume:
        if not args.jsonl_input:
            print("Error: --resume requires --jsonl-input to match failed websites with original tasks")
            return
            
        print(f"  Resume mode: {args.resume}")
        print(f"  JSONL input: {args.jsonl_input}")
        
        # Find failed websites from the previous batch
        failed_websites = find_failed_websites(args.resume, args.jsonl_input)
        
        if not failed_websites:
            print("No failed websites found to retry. All websites appear to be completed successfully.")
            return
            
        websites = failed_websites
        print(f"  Found {len(websites)} failed websites to retry")
        
    else:
        # Load websites based on input format (normal mode)
        if args.jsonl_input:
            print(f"  JSONL input: {args.jsonl_input}")
            websites = load_websites_from_jsonl(args.jsonl_input)
        else:
            websites_config_path = args.websites_config
            print(f"  Websites config: {websites_config_path}")
            websites = load_websites_config(websites_config_path)

    print(f"  TDD config: {tdd_config_path}")
    print(f"  Output directory: {output_dir}")
    print(f"  Max concurrent: {max_concurrent} websites")
    if args.limit:
        print(f"  Generation limit: {args.limit} websites")
    if not websites:
        if args.resume:
            print("No failed websites found to retry!")
        else:
            print("No websites found in configuration!")
        return
    
    if args.resume:
        print(f"\nFound {len(websites)} failed websites to retry:")
    else:
        print(f"\nFound {len(websites)} websites to generate:")
    
    # Only shuffle if not using JSONL input and not in resume mode (preserve order)
    if not args.jsonl_input and not args.resume:
        # Shuffle websites for random order generation
        random.shuffle(websites)

    # Apply limit if specified (but not in resume mode)
    if not args.resume:
        limit = args.limit
        original_count = len(websites)
        if limit and limit < len(websites):
            websites = websites[:limit]
            if args.jsonl_input:
                print(f"\nSelected first {limit} websites from {original_count} total websites (preserving JSONL order).")
            else:
                print(f"\nRandomly selected {limit} websites from {original_count} total websites.")

    if args.resume:
        print("\nRetry order (based on failed websites):")
    elif args.jsonl_input:
        print("\nGeneration order (preserving JSONL sequence):")
    else:
        print("\nShuffled generation order:")
    
    for i, website in enumerate(websites, 1):
        task_count = len(website.get('custom_task_names', []))
        name_display = website['name'][:100]
        if len(website['name']) > 100:
            name_display += "..."
            
        if args.resume and 'failed_folder' in website:
            folder_name = os.path.basename(website['failed_folder'])
            if task_count > 0:
                print(f"  {i}. {name_display} (folder: {folder_name}, image: {website['image_path']}, tasks: {task_count})")
            else:
                print(f"  {i}. {name_display} (folder: {folder_name}, image: {website['image_path']})")
        else:
            if task_count > 0:
                print(f"  {i}. {name_display} (image: {website['image_path']}, tasks: {task_count})")
            else:
                print(f"  {i}. {name_display} (image: {website['image_path']})")

    
    # Generate websites concurrently
    print("\n" + "=" * 80)
    if args.resume:
        print(f"Starting concurrent retry generation ({max_concurrent} workers)...")
    else:
        print(f"Starting concurrent batch generation ({max_concurrent} workers)...")
    print("=" * 80)
    print("\nPress Ctrl+C to cancel generation\n")
    
    overall_start = time.time()
    
    try:
        # Run concurrent generation
        results = await run_concurrent_generation(
            websites, tdd_config_path, output_dir, max_concurrent, timestamp, bool(args.resume)
        )
    except KeyboardInterrupt:
        print("\n\nGeneration cancelled by user")
        return
    
    overall_end = time.time()
    overall_duration = overall_end - overall_start
    
    # Print summary
    print("\n" + "=" * 80)
    print("GENERATION SUMMARY")
    print("=" * 80)
    
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"\nTotal websites: {len(results)}")
    print(f"  Successful: {len(successful)}")
    print(f"  Failed: {len(failed)}")
    print(f"  Success rate: {len(successful)/len(results)*100:.1f}%")
    
    if successful:
        print(f"\n✓ Successfully generated ({len(successful)}):")
        for r in successful:
            print(f"  - {r['website']} ({r['duration']:.2f}s)")
    
    if failed:
        print(f"\n✗ Failed to generate ({len(failed)}):")
        for r in failed:
            print(f"  - {r['website']}: {r['message']}")

    # Save results to file
    results_file = os.path.join(output_dir, "batch_results.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': timestamp,
            'total': len(results),
            'successful': len(successful),
            'failed': len(failed),
            'details': results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to: {results_file}")
    print(f"Generated websites in: {output_dir}")
    
    # Calculate time savings
    sequential_duration = sum(r['duration'] for r in results)
    time_saved = sequential_duration - overall_duration
    speedup = sequential_duration / overall_duration if overall_duration > 0 else 1
    
    print(f"\nTime Statistics:")
    print(f"  Overall time: {overall_duration:.2f}s ({overall_duration/60:.1f} minutes)")
    print(f"  Sequential time (estimated): {sequential_duration:.2f}s ({sequential_duration/60:.1f} minutes)")
    print(f"  Time saved: {time_saved:.2f}s ({time_saved/60:.1f} minutes)")
    print(f"  Speedup: {speedup:.2f}x")
    
def main():
    """Entry point that runs the async main function"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\nGeneration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()