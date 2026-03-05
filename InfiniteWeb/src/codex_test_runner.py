#!/usr/bin/env python3
"""
Codex Test Runner - Orchestrates website functional testing using Codex CLI + playwright-cli skill.

This script coordinates the testing of generated websites by:
1. Preparing evaluator files for playwright-cli execution
2. Spawning Codex CLI instances (via `codex e`) to execute tests
3. Codex uses its built-in playwright-cli skill to interact with the browser
4. Collecting and aggregating results

Key differences from claude_test_runner.py:
- Uses `codex e` instead of `claude -p`
- Codex has built-in playwright-cli skill, so prompt is much simpler
- Uses `-o <file>` flag to reliably capture final output
- Uses `--skip-git-repo-check` since we run outside git repos
"""

import argparse
import asyncio
import json
import os
import sys
import time
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class TestTask:
    """Represents a single test task."""
    task_id: str
    instruction: str
    evaluation_logic: str
    website_dir: str
    website_name: str
    ground_truth: Optional[Dict[str, Any]] = None
    config: Optional[List[Dict[str, Any]]] = None


@dataclass
class TestResult:
    """Result of a single test."""
    task_id: str
    website_name: str
    result: str  # SUCCESS, PARTIAL, FAILURE, ERROR (from score)
    pass_num: int = 1
    agent_result: Optional[str] = None  # Agent's own judgment
    reason: str = ""
    steps_taken: int = 0
    duration: float = 0.0
    final_evaluation: Optional[float] = None  # 0.0-1.0 score
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'task_id': self.task_id,
            'website': self.website_name,
            'pass_num': self.pass_num,
            'result': self.result,
            'agent_result': self.agent_result,
            'reason': self.reason,
            'steps_taken': self.steps_taken,
            'duration': self.duration,
            'final_evaluation': self.final_evaluation,
            'error': self.error
        }


def get_raw_output_log_path(website_name: str, task_id: str, pass_num: int, logs_dir: str) -> str:
    """Return path for saving raw Codex stdout/stderr for debugging."""
    os.makedirs(logs_dir, exist_ok=True)
    filename = f"raw_codex_output_{website_name}_{task_id}_pass{pass_num}.txt"
    return os.path.join(logs_dir, filename)


def get_system_time_override(task: TestTask) -> Optional[str]:
    """Extract set_system_time date from task config and return a JS script
    that overrides Date to return the baseline date.

    The script is designed for page.addInitScript() — it runs automatically
    before any page script on every navigation, so evaluators using new Date()
    will get the baseline date instead of the real current time.
    """
    if not task.config:
        return None
    for cfg in task.config:
        if cfg.get('type') == 'set_system_time':
            params = cfg.get('parameters', {})
            date_str = params.get('date', '')
            time_str = params.get('time', '09:00:00')
            if date_str:
                return f'''\
(function() {{
  const __OrigDate = Date;
  const __baseline = new __OrigDate("{date_str}T{time_str}").getTime();
  const __startReal = __OrigDate.now();
  function FakeDate(...args) {{
    if (args.length === 0) return new __OrigDate(__baseline + (__OrigDate.now() - __startReal));
    return new __OrigDate(...args);
  }}
  FakeDate.prototype = __OrigDate.prototype;
  FakeDate.now = function() {{ return __baseline + (__OrigDate.now() - __startReal); }};
  FakeDate.parse = __OrigDate.parse;
  FakeDate.UTC = __OrigDate.UTC;
  window.Date = FakeDate;
}})();'''
    return None


# ============================================================================
# Prompt Template (Codex + playwright-cli skill)
# ============================================================================

CODEX_PROMPT_TEMPLATE = '''You need to complete a website functional test task.

## Browser Tool: playwright-cli
You MUST use playwright-cli commands to operate the browser. This is the ONLY allowed way to interact with the website.

### Core Commands

1. Open browser and visit index.html first (this initializes localStorage data):
   playwright-cli -s={session} open "{website_url}"

2. Take snapshot to see page elements and ref numbers:
   playwright-cli -s={session} snapshot

3. Interact with elements using ref numbers from snapshot:
   playwright-cli -s={session} click e3
   playwright-cli -s={session} fill e5 "text to input"
   playwright-cli -s={session} select e8 "option_value"

4. Navigate by clicking links on the page, do NOT use goto directly.

5. Scroll the page:
   playwright-cli -s={session} mousewheel 0 300

6. View localStorage (read-only inspection):
   playwright-cli -s={session} localstorage-list

7. Run evaluator (after completing the task):
   playwright-cli -s={session} run-code "$(cat {eval_file})"

8. Close browser when done:
   playwright-cli -s={session} close

## Strict Rules (MUST follow)
1. You MUST visit index.html first to initialize data in localStorage.
2. After each action, run snapshot to see the updated page state.
3. Use ref numbers (e1, e2...) from snapshot to interact with elements.
4. Navigate between pages by clicking links, NOT by using goto.
5. Complete ALL tasks through UI operations (clicking buttons, filling forms, selecting options, etc.).
6. Do NOT directly modify localStorage or sessionStorage in any way.
7. Do NOT call JavaScript APIs like WebsiteSDK.*, BusinessLogic.*, or any programmatic interface via run-code to perform task actions. The run-code command is ONLY for running the evaluator file.
8. Do NOT use page.evaluate() or any JavaScript execution to bypass the UI. All task actions must be performed through visible UI elements.
9. If a UI element (button, link, etc.) is disabled or unavailable, report it — do NOT work around it by calling JavaScript APIs.

## Test Task
{task_instruction}

## Evaluation Logic
```javascript
{evaluation_logic}
```

## Steps
1. Use playwright-cli to complete the test task through UI operations only.
2. After completing the task, run the evaluator:
   playwright-cli -s={session} run-code "$(cat {eval_file})"
3. Read the evaluator's returned score (0.0-1.0).

## Output
Output ONLY a single JSON object (in a ```json code block):
```json
{{
  "result": "SUCCESS" or "PARTIAL" or "FAILURE",
  "reason": "Brief description of key actions taken and what the evaluator score means",
  "steps_taken": <integer count of key actions>,
  "final_evaluation": <evaluator score 0.0-1.0>
}}
```
Notes:
- Output only this JSON, no extra text.
- result and final_evaluation must be consistent (low score should not be SUCCESS).
'''


# ============================================================================
# Evaluator File Management
# ============================================================================

def write_evaluator_file(task: TestTask, session_id: str) -> str:
    """Write evaluator logic to a temp file for playwright-cli run-code execution."""
    eval_dir = os.path.join(tempfile.gettempdir(), 'playwright_evaluators')
    os.makedirs(eval_dir, exist_ok=True)

    eval_file = os.path.join(eval_dir, f'eval_{task.task_id}_{session_id}.js')

    wrapped_logic = f"""async page => {{
  return await page.evaluate(() => {{
    {task.evaluation_logic}
  }});
}}"""

    with open(eval_file, 'w', encoding='utf-8') as f:
        f.write(wrapped_logic)

    return eval_file


def cleanup_evaluator_file(eval_file: str):
    """Remove the evaluator temp file."""
    try:
        if os.path.exists(eval_file):
            os.remove(eval_file)
    except OSError:
        pass


# ============================================================================
# Task Loading
# ============================================================================

def load_tasks_from_website(website_dir: str) -> List[TestTask]:
    """Load test tasks from a website directory."""
    tasks = []
    website_name = os.path.basename(website_dir)

    # Load rewritten tasks first, fallback to data/tasks.json
    tasks_file = os.path.join(website_dir, 'rewritten_tasks.json')
    if not os.path.exists(tasks_file):
        tasks_file = os.path.join(website_dir, 'data', 'tasks.json')

    if not os.path.exists(tasks_file):
        logger.warning(f"No tasks file found in {website_dir}")
        return tasks

    with open(tasks_file, 'r', encoding='utf-8') as f:
        tasks_data = json.load(f)

    # Load evaluators
    evaluators_file = os.path.join(website_dir, 'evaluators.json')
    evaluators = {}
    if os.path.exists(evaluators_file):
        with open(evaluators_file, 'r', encoding='utf-8') as f:
            eval_data = json.load(f)
            for evaluator in eval_data.get('evaluators', []):
                evaluators[evaluator['task_id']] = evaluator.get('evaluation_logic', '')

    task_list = tasks_data.get('tasks', [])
    for task in task_list:
        task_id = task.get('id', '')
        instruction = task.get('instruction', task.get('description', ''))
        evaluation_logic = evaluators.get(task_id, 'return true;')

        tasks.append(TestTask(
            task_id=task_id,
            instruction=instruction,
            evaluation_logic=evaluation_logic,
            website_dir=website_dir,
            website_name=website_name,
            ground_truth=task.get('ground_truth'),
            config=task.get('config'),
        ))

    return tasks


def load_tasks_from_batch(batch_dir: str) -> List[TestTask]:
    """Load test tasks from a batch directory."""
    all_tasks = []

    for item in sorted(os.listdir(batch_dir)):
        item_path = os.path.join(batch_dir, item)
        if os.path.isdir(item_path):
            if os.path.exists(os.path.join(item_path, 'index.html')):
                tasks = load_tasks_from_website(item_path)
                all_tasks.extend(tasks)
                logger.info(f"Loaded {len(tasks)} tasks from {item}")

    return all_tasks


# ============================================================================
# Codex CLI Execution
# ============================================================================

async def run_codex_test(
    task: TestTask,
    model: str,
    timeout: int,
    working_dir: str,
    headed: bool = False,
    pass_num: int = 1,
    results_base_dir: Optional[str] = None,  # deprecated, use raw_logs_dir
    raw_logs_dir: Optional[str] = None,
) -> TestResult:
    """Run a single test using Codex CLI with playwright-cli skill."""
    start_time = time.time()

    # Generate unique session ID for this test
    session_id = f"{task.task_id}_{int(time.time() * 1000) % 100000}"

    # Write evaluator to temp file
    eval_file = write_evaluator_file(task, session_id)

    # Prepare output file for codex -o flag
    output_dir = os.path.join(tempfile.gettempdir(), 'codex_outputs')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f'output_{task.task_id}_{session_id}.txt')

    # Build the prompt
    website_url = f"file://{os.path.abspath(os.path.join(task.website_dir, 'index.html'))}"
    prompt = CODEX_PROMPT_TEMPLATE.format(
        session=session_id,
        website_url=website_url,
        task_instruction=task.instruction,
        evaluation_logic=task.evaluation_logic,
        eval_file=eval_file
    )

    try:
        # Set up environment
        env = os.environ.copy()

        # Ensure OPENAI_API_KEY is set for codex authentication
        if 'OPENAI_API_KEY' not in env:
            raise ValueError("OPENAI_API_KEY environment variable must be set")

        # playwright-cli environment configuration
        env['PLAYWRIGHT_MCP_BROWSER'] = 'chromium'
        env['PLAYWRIGHT_MCP_ALLOW_UNRESTRICTED_FILE_ACCESS'] = 'true'
        if headed:
            env['PLAYWRIGHT_MCP_HEADLESS'] = 'false'

        # Set session name via env var so codex's playwright skill uses it
        env['PLAYWRIGHT_CLI_SESSION'] = session_id

        # Ensure working_dir is absolute and exists
        abs_working_dir = os.path.abspath(working_dir)
        os.makedirs(abs_working_dir, exist_ok=True)

        logger.info(f"  Running codex e (model={model}, cwd={abs_working_dir})")

        # Build codex command
        cmd = [
            'codex', 'e',
            prompt,
            '--dangerously-bypass-approvals-and-sandbox',
            '--skip-git-repo-check',
            '-C', abs_working_dir,
            '-o', output_file,
        ]
        if model:
            cmd.extend(['-m', model])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=abs_working_dir,
            env=env
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            duration = time.time() - start_time

            # Check if output file has valid results despite timeout
            # (codex may have completed the task but not exited cleanly)
            output_file_content = ""
            if os.path.exists(output_file):
                with open(output_file, 'r', encoding='utf-8', errors='replace') as f:
                    output_file_content = f.read()

            # Save raw output for debugging
            _logs_dir = raw_logs_dir or results_base_dir
            if _logs_dir is not None:
                if raw_logs_dir is None:
                    _logs_dir = os.path.join(_logs_dir, "results", "test_results", "raw_logs")
                raw_path = get_raw_output_log_path(task.website_name, task.task_id, pass_num, _logs_dir)
                try:
                    with open(raw_path, 'w', encoding='utf-8') as f:
                        f.write("=== TIMEOUT ===\n")
                        f.write(f"Timeout after {timeout}s\n\n")
                        if output_file_content:
                            f.write("=== OUTPUT FILE (-o) ===\n")
                            f.write(output_file_content)
                            f.write("\n")
                except OSError:
                    pass

            # Clean up playwright session on timeout
            await cleanup_playwright_session(session_id, env)

            # If output file has a valid result, use it instead of ERROR
            if output_file_content:
                result = parse_codex_output(output_file_content)
                score = result.get('final_evaluation')
                if score is not None:
                    logger.info(f"  Timeout but output file has result: score={score}")
                    return TestResult(
                        task_id=task.task_id,
                        website_name=task.website_name,
                        result=score_to_result(score),
                        agent_result=result.get('result'),
                        reason=result.get('reason', '') + ' [timeout but result captured]',
                        steps_taken=result.get('steps_taken', 0),
                        final_evaluation=score,
                        duration=duration,
                    )

            return TestResult(
                task_id=task.task_id,
                website_name=task.website_name,
                result='ERROR',
                error='Timeout exceeded',
                duration=duration
            )

        duration = time.time() - start_time
        stdout_text = stdout.decode('utf-8', errors='replace')
        stderr_text = stderr.decode('utf-8', errors='replace')

        # Read the output file (-o flag captures the last agent message)
        output_file_content = ""
        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8', errors='replace') as f:
                output_file_content = f.read()

        # Save raw output for debugging
        _logs_dir = raw_logs_dir or results_base_dir
        if _logs_dir is not None:
            if raw_logs_dir is None:
                _logs_dir = os.path.join(_logs_dir, "results", "test_results", "raw_logs")
            raw_path = get_raw_output_log_path(task.website_name, task.task_id, pass_num, _logs_dir)
            try:
                with open(raw_path, 'w', encoding='utf-8') as f:
                    f.write("=== STDOUT ===\n")
                    f.write(stdout_text)
                    f.write("\n\n=== STDERR ===\n")
                    f.write(stderr_text)
                    f.write("\n\n=== OUTPUT FILE (-o) ===\n")
                    f.write(output_file_content)
            except OSError:
                pass

        # Try parsing from output file first (more reliable), then stdout
        output = output_file_content or stdout_text

        result = parse_codex_output(output)
        score = result.get('final_evaluation')
        agent_result = result.get('result')

        return TestResult(
            task_id=task.task_id,
            website_name=task.website_name,
            result=score_to_result(score),
            agent_result=agent_result,
            reason=result.get('reason', ''),
            steps_taken=result.get('steps_taken', 0),
            final_evaluation=score,
            duration=duration,
            error=result.get('error')
        )

    except Exception as e:
        import traceback
        logger.error(f"  Error running test {task.task_id}: {e}\n{traceback.format_exc()}")
        return TestResult(
            task_id=task.task_id,
            website_name=task.website_name,
            result='ERROR',
            error=str(e),
            duration=time.time() - start_time
        )
    finally:
        cleanup_evaluator_file(eval_file)
        # Clean up output file
        try:
            if os.path.exists(output_file):
                os.remove(output_file)
        except OSError:
            pass


async def cleanup_playwright_session(session_id: str, env: dict):
    """Force close a playwright-cli session."""
    try:
        process = await asyncio.create_subprocess_exec(
            'playwright-cli', f'-s={session_id}', 'close',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        await asyncio.wait_for(process.communicate(), timeout=10)
    except Exception:
        pass


def parse_codex_output(output: str) -> Dict[str, Any]:
    """Parse the JSON result from Codex's output."""
    import re

    # Look for JSON block with final_evaluation or result
    json_pattern = r'\{[^{}]*(?:"final_evaluation"|"result")[^{}]*\}'
    matches = re.findall(json_pattern, output, re.DOTALL)

    for match in reversed(matches):
        try:
            result = json.loads(match)
            if 'final_evaluation' in result or 'result' in result:
                return result
        except json.JSONDecodeError:
            continue

    # Try markdown code block
    code_block_pattern = r'```(?:json)?\s*(\{[^`]+\})\s*```'
    matches = re.findall(code_block_pattern, output, re.DOTALL)

    for match in reversed(matches):
        try:
            result = json.loads(match)
            if 'final_evaluation' in result or 'result' in result:
                return result
        except json.JSONDecodeError:
            continue

    return {
        'error': 'Could not parse result from output',
        'reason': output[:500] if len(output) > 500 else output
    }


def score_to_result(score: Optional[float]) -> str:
    """Convert final_evaluation score to result category."""
    if score is None:
        return 'ERROR'
    if score >= 1.0:
        return 'SUCCESS'
    if score > 0:
        return 'PARTIAL'
    return 'FAILURE'


# ============================================================================
# Test Orchestration
# ============================================================================

async def run_all_tests(
    tasks: List[tuple],  # List of (TestTask, pass_num) tuples
    concurrent: int,
    model: str,
    timeout: int,
    output_path: str,
    working_dir: str,
    headed: bool = False
) -> List[TestResult]:
    """Run all tests with concurrent execution."""
    semaphore = asyncio.Semaphore(concurrent)
    results = []

    jsonl_path = output_path if output_path.endswith('.jsonl') else output_path.replace('.json', '.jsonl')
    os.makedirs(os.path.dirname(jsonl_path) or '.', exist_ok=True)

    # Derive raw_logs_dir from output filename
    run_name = os.path.splitext(os.path.basename(jsonl_path))[0]
    if run_name.endswith('.jsonl'):
        run_name = run_name[:-6]
    raw_logs_dir = os.path.join(os.path.dirname(jsonl_path), "raw_logs", run_name)

    async def run_with_semaphore(task: TestTask, pass_num: int, index: int) -> TestResult:
        async with semaphore:
            pass_info = f"[P{pass_num}]" if pass_num > 0 else ""
            logger.info(f"[{index + 1}/{len(tasks)}]{pass_info} Testing {task.website_name}/{task.task_id}")
            result = await run_codex_test(task, model, timeout, working_dir, headed, pass_num=pass_num, raw_logs_dir=raw_logs_dir)
            result.pass_num = pass_num

            with open(jsonl_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(result.to_dict(), ensure_ascii=False) + '\n')

            status_map = {'SUCCESS': '✓', 'PARTIAL': '◐', 'FAILURE': '✗', 'ERROR': '!'}
            status = status_map.get(result.result, '?')
            score_str = f" [{result.final_evaluation:.1f}]" if result.final_evaluation is not None else ""
            logger.info(f"  {status} {result.result}{score_str} ({result.duration:.1f}s)")
            return result

    coros = [run_with_semaphore(task, pass_num, i) for i, (task, pass_num) in enumerate(tasks)]
    results = await asyncio.gather(*coros)

    return results


def generate_summary(results: List[TestResult]) -> Dict[str, Any]:
    """Generate a summary of test results."""
    total = len(results)
    success = sum(1 for r in results if r.result == 'SUCCESS')
    partial = sum(1 for r in results if r.result == 'PARTIAL')
    failure = sum(1 for r in results if r.result == 'FAILURE')
    error = sum(1 for r in results if r.result == 'ERROR')
    total_duration = sum(r.duration for r in results)

    scores = [r.final_evaluation for r in results if r.final_evaluation is not None]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    by_website = {}
    for r in results:
        if r.website_name not in by_website:
            by_website[r.website_name] = {'total': 0, 'success': 0, 'partial': 0, 'failure': 0, 'error': 0, 'scores': []}
        by_website[r.website_name]['total'] += 1
        if r.result == 'SUCCESS':
            by_website[r.website_name]['success'] += 1
        elif r.result == 'PARTIAL':
            by_website[r.website_name]['partial'] += 1
        elif r.result == 'FAILURE':
            by_website[r.website_name]['failure'] += 1
        else:
            by_website[r.website_name]['error'] += 1
        if r.final_evaluation is not None:
            by_website[r.website_name]['scores'].append(r.final_evaluation)

    for website in by_website:
        scores = by_website[website].pop('scores')
        by_website[website]['avg_score'] = sum(scores) / len(scores) if scores else 0.0

    return {
        'summary': {
            'total_tasks': total,
            'success': success,
            'partial': partial,
            'failure': failure,
            'error': error,
            'success_rate': success / total if total > 0 else 0,
            'avg_score': avg_score,
            'total_duration': total_duration
        },
        'by_website': by_website,
        'details': [r.to_dict() for r in results]
    }


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Run functional tests on generated websites using Codex CLI + playwright-cli skill'
    )
    parser.add_argument('--website-dir', type=str,
                        help='Single website directory to test')
    parser.add_argument('--batch-dir', type=str,
                        help='Batch directory containing multiple websites')
    parser.add_argument('--task-id', type=str,
                        help='Specific task ID to test')
    parser.add_argument('--concurrent', type=int, default=5,
                        help='Number of concurrent Codex instances')
    parser.add_argument('--model', type=str, default='',
                        help='Model to use (default: codex config default)')
    parser.add_argument('--timeout', type=int, default=600,
                        help='Timeout per test in seconds')
    parser.add_argument('--output', type=str,
                        default='results/test_results/codex_test_{timestamp}.json',
                        help='Output file path')
    parser.add_argument('--headed', action='store_true',
                        help='Run browser in headed mode (visible)')
    parser.add_argument('--working-dir', type=str, default='/tmp/codex_test_workdir',
                        help='Working directory for Codex CLI')
    parser.add_argument('--passes', type=int, default=1,
                        help='Number of test passes for stability testing')

    args = parser.parse_args()

    # Verify codex is available
    if os.system('which codex > /dev/null 2>&1') != 0:
        logger.error("codex not found. Install Codex CLI first.")
        sys.exit(1)

    # Verify playwright-cli is available
    if os.system('which playwright-cli > /dev/null 2>&1') != 0:
        logger.error("playwright-cli not found. Install with: npm install -g @playwright/cli@latest")
        sys.exit(1)

    if not args.website_dir and not args.batch_dir:
        parser.error("Either --website-dir or --batch-dir is required")

    # Load tasks
    if args.website_dir:
        tasks = load_tasks_from_website(args.website_dir)
    else:
        tasks = load_tasks_from_batch(args.batch_dir)

    if not tasks:
        logger.error("No tasks found")
        sys.exit(1)

    if args.task_id:
        tasks = [t for t in tasks if t.task_id == args.task_id]
        if not tasks:
            logger.error(f"Task {args.task_id} not found")
            sys.exit(1)

    logger.info(f"Found {len(tasks)} tasks to test")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = args.output.replace('{timestamp}', timestamp)
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    try:
        all_pass_tasks = []
        for pass_num in range(1, args.passes + 1):
            for task in tasks:
                all_pass_tasks.append((task, pass_num))

        total_tasks = len(all_pass_tasks)
        logger.info(f"Running {total_tasks} total task instances ({len(tasks)} tasks x {args.passes} passes)")

        results = asyncio.run(run_all_tests(
            tasks=all_pass_tasks,
            concurrent=args.concurrent,
            model=args.model,
            timeout=args.timeout,
            output_path=output_path,
            working_dir=args.working_dir,
            headed=args.headed
        ))

        # Group results by pass
        results_by_pass = {}
        for r in results:
            if r.pass_num not in results_by_pass:
                results_by_pass[r.pass_num] = []
            results_by_pass[r.pass_num].append(r)

        all_pass_results = []
        for pass_num in range(1, args.passes + 1):
            pass_results = results_by_pass.get(pass_num, [])
            summary = generate_summary(pass_results)

            all_pass_results.append({
                'pass': pass_num,
                'summary': summary['summary'],
                'details': summary['details']
            })

            if args.passes > 1:
                pass_output_path = output_path.replace('.json', f'_pass{pass_num}.json')
            else:
                pass_output_path = output_path

            with open(pass_output_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            print(f"\n{'='*50}")
            print(f"Pass {pass_num} Summary" if args.passes > 1 else "Test Summary")
            print("=" * 50)
            s = summary['summary']
            print(f"Total: {s['total_tasks']} tasks")
            print(f"Success: {s['success']} ({s['success_rate']*100:.1f}%)")
            print(f"Partial: {s['partial']}")
            print(f"Failure: {s['failure']}")
            print(f"Error: {s['error']}")
            print(f"Avg Score: {s['avg_score']:.2f}")
            print(f"Duration: {s['total_duration']:.1f}s")
            print(f"Results saved to: {pass_output_path}")

        if args.passes > 1:
            print(f"\n{'='*50}")
            print("Stability Summary (All Passes)")
            print("=" * 50)

            task_results = {}
            for pass_data in all_pass_results:
                for detail in pass_data['details']:
                    task_id = detail['task_id']
                    if task_id not in task_results:
                        task_results[task_id] = []
                    task_results[task_id].append(detail['final_evaluation'])

            print(f"{'Task':<12} | " + " | ".join([f"Pass{i+1}" for i in range(args.passes)]) + " | Stability")
            print("-" * (20 + args.passes * 8))

            for task_id in sorted(task_results.keys()):
                scores = task_results[task_id]
                score_strs = [f"{s:.1f}" if s is not None else "ERR" for s in scores]

                valid_scores = [s for s in scores if s is not None]
                if len(valid_scores) == 0:
                    stability = "unstable"
                elif all(s == 1.0 for s in valid_scores) and len(valid_scores) == len(scores):
                    stability = "stable ✓"
                elif all(s == valid_scores[0] for s in valid_scores):
                    stability = f"stable ({valid_scores[0]:.1f})"
                else:
                    stability = "unstable"

                print(f"{task_id:<12} | " + " | ".join([f"{s:>5}" for s in score_strs]) + f" | {stability}")

            avg_scores = [p['summary']['avg_score'] for p in all_pass_results]
            success_rates = [p['summary']['success_rate'] for p in all_pass_results]
            print(f"\nAvg Score: {min(avg_scores):.2f} - {max(avg_scores):.2f}")
            print(f"Success Rate: {min(success_rates)*100:.0f}% - {max(success_rates)*100:.0f}%")

    finally:
        # Clean up any remaining playwright sessions
        os.system('playwright-cli close-all 2>/dev/null')


if __name__ == '__main__':
    main()
