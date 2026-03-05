#!/usr/bin/env python3
"""
Generate task JSON files for generated websites (single or batch mode).

This script creates individual task JSON files for each task in generated websites,
using the task.json template and filling in website-specific information.
All generated files are saved in a 'task_jsons' subfolder.

Two modes are supported:
1. Single website mode: Process one website directory
2. Batch mode: Process multiple website directories in a batch folder

Usage:
    # Single website mode
    python src/generate_task_jsons.py --website-dir test/website1
    python src/generate_task_jsons.py --website-dir test/website1 --output-dir custom/output/

    # Batch mode
    python src/generate_task_jsons.py --batch-dir results/batch_generated/20251022_081558
    python src/generate_task_jsons.py --batch-dir results/batch_generated/20251022_081558 --output-dir output/

Output Structure:
    {output_dir}/task_jsons/
    ├── website1_1.json
    ├── website1_2.json
    ├── ...
    └── test_all.json
"""

import json
import os
import sys
import argparse
import copy
from pathlib import Path
from typing import Dict, List, Any, Tuple


def load_json(file_path: str) -> Dict[str, Any]:
    """Load and parse a JSON file.

    Args:
        file_path: Path to the JSON file

    Returns:
        Parsed JSON data

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If JSON is invalid
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], file_path: str) -> None:
    """Save data to a JSON file with pretty formatting.

    Args:
        data: Data to save
        file_path: Output file path
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def extract_website_name(website_dir: str) -> str:
    """Extract website name from directory path.

    Args:
        website_dir: Website directory path (e.g., 'test/website1')

    Returns:
        Website name (e.g., 'website1')
    """
    return os.path.basename(os.path.normpath(website_dir))


def find_evaluator_by_task_id(evaluators: List[Dict[str, Any]], task_id: str) -> Dict[str, Any]:
    """Find evaluator matching the given task_id.

    Args:
        evaluators: List of evaluator objects
        task_id: Task ID to match (e.g., 'task_1')

    Returns:
        Matching evaluator object

    Raises:
        ValueError: If no matching evaluator is found
    """
    for evaluator in evaluators:
        if evaluator.get('task_id') == task_id:
            return evaluator

    raise ValueError(f"No evaluator found for task_id: {task_id}")


def generate_task_json(
    template: Dict[str, Any],
    task: Dict[str, Any],
    evaluator: Dict[str, Any],
    website_name: str,
    task_number: int
) -> Dict[str, Any]:
    """Generate a task JSON file based on template and task data.

    Args:
        template: Template JSON structure
        task: Task data from tasks.json
        evaluator: Evaluator data from evaluators.json
        website_name: Name of the website (e.g., 'website1')
        task_number: Task sequence number (1, 2, 3, ...)

    Returns:
        Generated task JSON data
    """
    # Deep copy template to avoid modifying original
    result = copy.deepcopy(template)

    # 1. Modify id: {website_name}_{task_number}
    result['id'] = f"{website_name}_{task_number}"

    # 2. Modify instruction: prefer new 'instruction' field, fallback to old format
    instruction = task.get('instruction', '')
    if not instruction:
        # Backward compatibility: use old name:description format
        task_name = task.get('name', '')
        task_description = task.get('description', '')
        instruction = f"{task_name}: {task_description}" if task_name else task_description
    result['instruction'] = instruction

    # 3. Merge task-specific config (e.g., set_system_time) at the beginning
    task_config = task.get('config', [])
    if task_config:
        result['config'] = task_config + result.get('config', [])

    # 4. Modify chrome_open_tabs.urls_to_open
    # Find the chrome_open_tabs config item
    for config_item in result.get('config', []):
        if config_item.get('type') == 'chrome_open_tabs':
            config_item['parameters']['urls_to_open'] = [
                f"file:///home/user/{website_name}/index.html"
            ]
            break

    # 5. Modify evaluator.result.evaluation_logic
    evaluation_logic = evaluator.get('evaluation_logic', '')
    if 'evaluator' not in result:
        result['evaluator'] = {}
    if 'result' not in result['evaluator']:
        result['evaluator']['result'] = {}
    result['evaluator']['result']['evaluation_logic'] = evaluation_logic

    return result


def generate_test_all_json(task_ids: List[str], output_dir: str) -> None:
    """Generate test_all.json containing all task IDs.

    Args:
        task_ids: List of task IDs (file names without .json extension)
        output_dir: Output directory for the test_all.json file
    """
    test_all_path = os.path.join(output_dir, 'test_all.json')
    test_all_data = {
        "website_examples": task_ids
    }
    save_json(test_all_data, test_all_path)
    print(f"\nGenerated test_all.json with {len(task_ids)} task IDs")


def process_single_website(
    website_dir: str,
    template_path: str,
    output_dir: str,
    verbose: bool = True
) -> Tuple[bool, int, str, List[str]]:
    """Process a single website directory to generate task JSON files.

    Args:
        website_dir: Path to the website directory
        template_path: Path to the task.json template file
        output_dir: Output directory for generated files
        verbose: Whether to print detailed progress (default: True)

    Returns:
        Tuple of (success, num_tasks_generated, error_message, task_ids)
        - success: True if processing succeeded, False otherwise
        - num_tasks_generated: Number of task JSON files generated
        - error_message: Error description if failed, empty string if succeeded
        - task_ids: List of generated task IDs (file names without .json)
    """
    website_name = extract_website_name(website_dir)

    # Create task_jsons subfolder
    task_jsons_dir = os.path.join(output_dir, 'task_jsons')
    os.makedirs(task_jsons_dir, exist_ok=True)

    # Paths to input files
    # 直接读取重写后的任务文件（在网站根目录下）
    tasks_path = os.path.join(website_dir, 'rewritten_tasks.json')
    evaluators_path = os.path.join(website_dir, 'evaluators.json')

    # 检查重写后的任务文件是否存在
    if not os.path.exists(tasks_path):
        skip_msg = f"SKIPPED: 找不到重写后的任务文件: {tasks_path}"
        if verbose:
            print(f"\n⚠ Skipped: Missing rewritten_tasks.json")
        return False, 0, skip_msg, []

    # Print processing info if verbose
    if verbose:
        print(f"Processing website directory: {website_dir}")
        print(f"Website name: {website_name}")
        print(f"Template: {template_path}")
        print(f"Output directory: {task_jsons_dir}/")

    try:
        # Load template
        template = load_json(template_path)

        # Load rewritten tasks
        if verbose:
            print(f"Loading rewritten tasks from {tasks_path}...", end=' ')
        tasks_data = load_json(tasks_path)
        tasks = tasks_data.get('tasks', [])
        if verbose:
            print(f"Found {len(tasks)} tasks")

        # Load evaluators
        if verbose:
            print(f"Loading evaluators from {evaluators_path}...", end=' ')
        evaluators_data = load_json(evaluators_path)
        evaluators = evaluators_data.get('evaluators', [])
        if verbose:
            print(f"Found {len(evaluators)} evaluators")

        # Generate task JSON files
        if verbose:
            print("Generating task JSON files...")

        generated_files = []
        task_ids = []
        for idx, task in enumerate(tasks, start=1):
            task_id = task.get('id', f'task_{idx}')

            # Find corresponding evaluator
            try:
                evaluator = find_evaluator_by_task_id(evaluators, task_id)
            except ValueError as e:
                error_msg = f"No evaluator found for task_id: {task_id}"
                if verbose:
                    print(f"\n✗ Error: {error_msg}")
                return False, 0, error_msg, []

            # Generate task JSON
            task_json = generate_task_json(
                template=template,
                task=task,
                evaluator=evaluator,
                website_name=website_name,
                task_number=idx
            )

            # Save to file
            output_filename = f"{website_name}_{idx}.json"
            task_id_str = f"{website_name}_{idx}"
            output_path = os.path.join(task_jsons_dir, output_filename)
            save_json(task_json, output_path)

            generated_files.append(output_filename)
            task_ids.append(task_id_str)
            if verbose:
                print(f"  [{idx}/{len(tasks)}] {output_filename} ✓")

        # Success summary
        if verbose:
            print(f"\nSuccessfully generated {len(generated_files)} task JSON files in {task_jsons_dir}/")

        return True, len(generated_files), "", task_ids

    except FileNotFoundError as e:
        error_msg = str(e)
        if verbose:
            print(f"\n✗ Error: {error_msg}")
        return False, 0, error_msg, []
    except json.JSONDecodeError as e:
        error_msg = f"JSON parsing error: {e}"
        if verbose:
            print(f"\n✗ {error_msg}")
        return False, 0, error_msg, []
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        if verbose:
            print(f"\n✗ {error_msg}")
        return False, 0, error_msg, []


def process_batch_websites(
    batch_dir: str,
    template_path: str,
    output_dir: str = None
) -> Tuple[int, int, int]:
    """Process multiple website directories in a batch folder.

    Args:
        batch_dir: Path to the batch directory containing multiple website folders
        template_path: Path to the task.json template file
        output_dir: Output directory for generated files (default: batch_dir itself)

    Returns:
        Tuple of (total_websites, succeeded, total_tasks)
        - total_websites: Total number of website directories found
        - succeeded: Number of successfully processed websites
        - total_tasks: Total number of task JSON files generated
    """
    # Use batch_dir as output_dir if not specified
    if output_dir is None:
        output_dir = batch_dir

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Scan batch directory for website folders
    print(f"Scanning batch directory: {batch_dir}")

    website_dirs = []
    for item in sorted(os.listdir(batch_dir)):
        item_path = os.path.join(batch_dir, item)

        # Check if it's a directory
        if not os.path.isdir(item_path):
            continue

        # Check if it contains required files
        tasks_path = os.path.join(item_path, 'data', 'tasks.json')
        evaluators_path = os.path.join(item_path, 'evaluators.json')

        if os.path.exists(tasks_path) and os.path.exists(evaluators_path):
            website_dirs.append(item_path)

    total_websites = len(website_dirs)

    if total_websites == 0:
        print("⚠ No valid website directories found (must contain data/tasks.json and evaluators.json)")
        return 0, 0, 0

    print(f"Found {total_websites} valid website directories\n")
    print(f"Processing {total_websites} websites...")
    print(f"Output directory: {os.path.join(output_dir, 'task_jsons')}/\n")

    # Statistics
    succeeded = 0
    failed = 0
    skipped = 0
    total_tasks = 0
    failed_websites = []
    skipped_websites = []
    all_task_ids = []

    # Process each website
    for idx, website_dir in enumerate(website_dirs, start=1):
        website_name = extract_website_name(website_dir)

        # Process the website (non-verbose mode in batch)
        success, num_tasks, error_msg, task_ids = process_single_website(
            website_dir=website_dir,
            template_path=template_path,
            output_dir=output_dir,
            verbose=False
        )

        # Display progress
        if success:
            print(f"[{idx}/{total_websites}] {website_name}... ✓ ({num_tasks} tasks generated)")
            succeeded += 1
            total_tasks += num_tasks
            all_task_ids.extend(task_ids)
        elif error_msg.startswith("SKIPPED:"):
            print(f"[{idx}/{total_websites}] {website_name}... ⚠ (Skipped: missing rewritten_tasks.json)")
            skipped += 1
            skipped_websites.append({
                'website_name': website_name,
                'website_dir': website_dir
            })
        else:
            print(f"[{idx}/{total_websites}] {website_name}... ✗ (Error: {error_msg})")
            failed += 1
            failed_websites.append({
                'website_name': website_name,
                'website_dir': website_dir,
                'error': error_msg
            })

    # Print summary
    print(f"\n{'='*60}")
    print(f"Summary: {succeeded} succeeded, {skipped} skipped, {failed} failed, {total_tasks} total tasks generated")
    print(f"{'='*60}")

    if skipped_websites:
        print(f"\nSkipped websites (missing rewritten_tasks.json): {len(skipped_websites)}")
        for skip_info in skipped_websites:
            print(f"  ⚠ {skip_info['website_name']}")

    if failed_websites:
        print("\nFailed websites:")
        for fail_info in failed_websites:
            print(f"  ✗ {fail_info['website_name']}: {fail_info['error']}")

    # Generate test_all.json with all task IDs
    if all_task_ids:
        task_jsons_dir = os.path.join(output_dir, 'task_jsons')
        generate_test_all_json(all_task_ids, task_jsons_dir)

    return total_websites, succeeded, total_tasks


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Generate task JSON files for generated websites (single or batch)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single website mode
  python src/generate_task_jsons.py --website-dir test/website1
  python src/generate_task_jsons.py --website-dir test/website2 --output-dir output/
  python src/generate_task_jsons.py --website-dir test/website1 --template custom.json

  # Batch mode
  python src/generate_task_jsons.py --batch-dir results/batch_generated/20251022_081558
  python src/generate_task_jsons.py --batch-dir results/batch_generated/20251022_081558 --output-dir output/
        """
    )

    parser.add_argument(
        '--website-dir',
        default=None,
        help='Path to a single website directory (e.g., test/website1). Mutually exclusive with --batch-dir'
    )

    parser.add_argument(
        '--batch-dir',
        default=None,
        help='Path to a batch directory containing multiple website folders. Mutually exclusive with --website-dir'
    )

    parser.add_argument(
        '--template',
        default='osworld_integration/task_template.json',
        help='Path to the task template JSON file (default: osworld_integration/task_template.json)'
    )

    parser.add_argument(
        '--output-dir',
        default=None,
        help='Output directory (files saved in task_jsons/ subfolder). Default: parent dir of website-dir, or batch-dir itself for batch mode'
    )

    args = parser.parse_args()

    # Validate arguments: must provide either --website-dir or --batch-dir, but not both
    if args.website_dir and args.batch_dir:
        print("✗ Error: Cannot use both --website-dir and --batch-dir. Please choose one.")
        sys.exit(1)

    if not args.website_dir and not args.batch_dir:
        print("✗ Error: Must provide either --website-dir or --batch-dir.")
        parser.print_help()
        sys.exit(1)

    template_path = args.template

    # Batch mode
    if args.batch_dir:
        batch_dir = args.batch_dir

        # Validate batch directory exists
        if not os.path.exists(batch_dir):
            print(f"✗ Error: Batch directory not found: {batch_dir}")
            sys.exit(1)

        if not os.path.isdir(batch_dir):
            print(f"✗ Error: Not a directory: {batch_dir}")
            sys.exit(1)

        # Determine output directory (default to batch_dir for batch mode)
        output_dir = args.output_dir if args.output_dir else batch_dir

        # Process batch websites
        total_websites, succeeded, total_tasks = process_batch_websites(
            batch_dir=batch_dir,
            template_path=template_path,
            output_dir=output_dir
        )

        # Exit with appropriate code
        if succeeded == 0:
            sys.exit(1)
        elif succeeded < total_websites:
            sys.exit(0)  # Partial success
        else:
            sys.exit(0)  # Complete success

    # Single website mode
    else:
        website_dir = args.website_dir

        # Validate website directory exists
        if not os.path.exists(website_dir):
            print(f"✗ Error: Website directory not found: {website_dir}")
            sys.exit(1)

        if not os.path.isdir(website_dir):
            print(f"✗ Error: Not a directory: {website_dir}")
            sys.exit(1)

        # Determine output directory (default to parent directory for single mode)
        if args.output_dir:
            output_dir = args.output_dir
        else:
            output_dir = os.path.dirname(os.path.normpath(website_dir))
            if not output_dir:  # Handle case where website_dir has no parent
                output_dir = '.'

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Process single website
        success, num_tasks, error_msg, task_ids = process_single_website(
            website_dir=website_dir,
            template_path=template_path,
            output_dir=output_dir,
            verbose=True
        )

        # Generate test_all.json if successful
        if success and task_ids:
            task_jsons_dir = os.path.join(output_dir, 'task_jsons')
            generate_test_all_json(task_ids, task_jsons_dir)

        # Exit with appropriate code
        if success:
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == '__main__':
    main()
