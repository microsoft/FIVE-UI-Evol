#!/usr/bin/env python3
"""
ReAct Test Runner v8 - Bash-based architecture.

Key design: single bash tool + evaluate_task
- LLM writes arbitrary bash commands (playwright-cli, cat, grep, etc.)
- Output is truncated with tail-keep strategy; full output saved to temp file
- Snapshot files are managed by LLM (read with cat/grep/sed)
- Matches Codex's flexibility while using standard tool calling API

Reuses infrastructure from codex_test_runner.py:
- TestTask / TestResult data structures
- Task loading (load_tasks_from_website / load_tasks_from_batch)
- Evaluator file management
- Score-to-result mapping
- Summary generation
"""

import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
import logging

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from codex_test_runner import (
    TestTask, TestResult,
    load_tasks_from_website, load_tasks_from_batch,
    write_evaluator_file, cleanup_evaluator_file,
    score_to_result, generate_summary,
    get_system_time_override,
)
from llm_caller import (
    call_openai_api_with_tools_async,
    configure_load_balancing,
    get_next_endpoint,
    get_async_client_for_endpoint,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Tool Definitions (2 tools: bash + evaluate_task)
# ============================================================================

TOOLS = [
    {
        "type": "function",
        "name": "bash",
        "description": "Execute a bash command. Use for playwright-cli browser operations, reading files, processing data with unix tools, etc. Output is truncated to last 300 lines or 50KB (whichever is hit first) — full output is saved to a temp file whose path is shown.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30, max 120)"
                }
            },
            "required": ["command"],
        },
    },
    {
        "type": "function",
        "name": "evaluate_task",
        "description": "Run the task evaluator to check your score. Call this AFTER completing all required UI actions and saving changes. Returns a score from 0.0 to 1.0.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


# ============================================================================
# System Prompt (v8 - bash based)
# ============================================================================

SYSTEM_PROMPT = '''You are a website functional test agent. You operate a browser via bash commands.

## Browser Tool: playwright-cli
Session ID: {session_id}
All playwright-cli commands must use: playwright-cli -s={session_id} <command>

### Core Commands
- Snapshot: playwright-cli -s={session_id} snapshot
- Click: playwright-cli -s={session_id} click e3
- Fill: playwright-cli -s={session_id} fill e5 "text"
- Select: playwright-cli -s={session_id} select e8 "value"
- Scroll: playwright-cli -s={session_id} mousewheel 0 300
- Dialog accept: playwright-cli -s={session_id} dialog-accept
- Dialog dismiss: playwright-cli -s={session_id} dialog-dismiss
- Run JS (read-only): playwright-cli -s={session_id} run-code "async page => {{ ... }}"

### Page Snapshot
After each bash call, you will see a hint like:
  [Latest snapshot: .playwright-cli/page-xxx.yml (150 lines, 8000 bytes)]

This tells you the file path, line count, and byte size.
- If the file is small (<=300 lines), read it in full: cat .playwright-cli/page-xxx.yml
- If large (>300 lines), use grep to find the element you need:
    grep -n "keyword" .playwright-cli/page-xxx.yml
  Then read a specific range around the match:
    sed -n '50,80p' .playwright-cli/page-xxx.yml

IMPORTANT: Chain action + snapshot + read into ONE bash call to save steps:
  playwright-cli -s={session_id} click e5 && playwright-cli -s={session_id} snapshot && SNAP=$(ls -t .playwright-cli/page-*.yml | head -1) && cat "$SNAP"

When you already know what to look for, use grep instead of cat to reduce output:
  playwright-cli -s={session_id} click e5 && playwright-cli -s={session_id} snapshot && SNAP=$(ls -t .playwright-cli/page-*.yml | head -1) && grep -n "Submit\\|Save\\|Confirm" "$SNAP"

Snapshot YAML format:
- [ref=e5] is the element reference for click/fill/select
- Element types: link, button, textbox, heading, article, etc.
- Text in quotes after element type

### Reading localStorage
Use run-code to read data (read-only):
  playwright-cli -s={session_id} run-code "async page => {{ return await page.evaluate(() => {{ const r = {{}}; for (let i = 0; i < localStorage.length; i++) {{ const k = localStorage.key(i); const v = localStorage.getItem(k); r[k] = {{ length: v.length, preview: v.substring(0, 80) }}; }} return JSON.stringify(r, null, 2); }}); }}"
  playwright-cli -s={session_id} run-code "async page => {{ return await page.evaluate(() => localStorage.getItem('recipes')); }}"

### Rules
1. Visit index.html FIRST to initialize localStorage data.
2. Complete tasks through UI operations only (clicking, filling, selecting).
3. Do NOT directly modify localStorage or sessionStorage.
4. Do NOT call JavaScript APIs (WebsiteSDK, BusinessLogic) via run-code.
5. run-code is ONLY for reading data and running the evaluator.
6. Navigate by clicking links, NOT by using goto.
7. DATA-FIRST: For criteria-matching tasks, read localStorage first to identify qualifying items before browsing the UI.
8. After completing all actions and saving, call the evaluate_task tool.
9. Always click Save/Submit buttons to persist changes BEFORE calling evaluate_task.
10. If a checkbox click times out, try clicking its label element instead.

### Efficiency
- ALWAYS chain commands with && in one bash call: action && snapshot && read.
- NEVER read the same localStorage key twice without performing actions in between.
- If scrolling does not reveal new content (snapshot unchanged), stop and try a different approach.
- Do NOT read the website's source HTML files from disk. Use the browser only.

## Test Task
{task_instruction}

## Evaluation Logic (reference)
```javascript
{evaluation_logic}
```

You have {max_steps} bash steps available. Plan efficiently — chain commands to use fewer steps.
'''


# ============================================================================
# Bash Command Executor (with truncation)
# ============================================================================

BASH_MAX_OUTPUT_LINES = 300
BASH_MAX_OUTPUT_BYTES = 50_000  # 50KB


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    else:
        return f"{n / (1024 * 1024):.1f}MB"


async def execute_bash(command: str, working_dir: str, env: dict, timeout: int = 30) -> str:
    """Execute a bash command and return output with tail truncation.

    Truncation design (inspired by pi-mono/bash.ts):
    - Tail-keep: keeps the LAST N lines / bytes
    - If truncated, full output saved to temp file
    - Truncation hint appended AFTER content: [Showing lines X-Y of Z. Full output: path]
    - Single-line edge case: if output is 1 line that exceeds byte limit, show tail bytes
    """
    timeout = min(max(timeout, 5), 120)  # clamp to 5-120s

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            cwd=working_dir,
            env=env,
        )

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return f"Command timed out after {timeout}s"

        output = stdout.decode('utf-8', errors='replace')

    except Exception as e:
        return f"Command error: {e}"

    # Check if truncation needed
    lines = output.splitlines(keepends=True)
    total_lines = len(lines)
    total_bytes = len(output.encode('utf-8'))

    if total_lines <= BASH_MAX_OUTPUT_LINES and total_bytes <= BASH_MAX_OUTPUT_BYTES:
        return output

    # Save full output to temp file
    temp_path = os.path.join(working_dir, f'.bash_output_{int(time.time()*1000)%100000}.txt')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(output)
    except OSError:
        temp_path = "(failed to save)"

    # Keep head lines within both limits (head-keep: preserve beginning)
    kept_lines = []
    kept_bytes = 0
    for line in lines:
        line_bytes = len(line.encode('utf-8'))
        if kept_bytes + line_bytes > BASH_MAX_OUTPUT_BYTES:
            break
        if len(kept_lines) >= BASH_MAX_OUTPUT_LINES:
            break
        kept_lines.append(line)
        kept_bytes += line_bytes

    truncated_content = ''.join(kept_lines)
    end_line = len(kept_lines)

    # Build truncation hint (appended after content)
    remaining = total_lines - end_line
    if total_lines == 1:
        # Single long line edge case
        hint = f"\n\n[Showing first {_format_size(kept_bytes)} of line 1 (line is {_format_size(total_bytes)}). Use grep/sed to find specific content. Full output: {temp_path}]"
    else:
        hint = f"\n\n[Showing lines 1-{end_line} of {total_lines} ({remaining} more lines). Use grep to find specific content, or sed -n '{end_line+1},{total_lines}p' to read more. Full output: {temp_path}]"

    return truncated_content + hint


# ============================================================================
# Snapshot Hint Helper
# ============================================================================

def get_latest_snapshot_hint(working_dir: str) -> str:
    """Return a hint string with the latest snapshot file path and size info."""
    snapshot_dir = os.path.join(working_dir, '.playwright-cli')
    if not os.path.isdir(snapshot_dir):
        return ""
    files = sorted(
        glob.glob(os.path.join(snapshot_dir, 'page-*.yml')),
        key=os.path.getmtime
    )
    if files:
        rel_path = os.path.relpath(files[-1], working_dir)
        try:
            with open(files[-1], 'r', encoding='utf-8') as f:
                content = f.read()
            total_lines = len(content.splitlines())
            total_bytes = len(content.encode('utf-8'))
            size_hint = f" ({total_lines} lines, {total_bytes} bytes)"
            if total_lines <= 300:
                size_hint += " — small enough to read in full with: cat " + rel_path
        except OSError:
            size_hint = ""
        return f"\n[Latest snapshot: {rel_path}{size_hint}]"
    return ""


# ============================================================================
# playwright-cli Executor (for evaluator only)
# ============================================================================

async def exec_playwright(
    session_id: str,
    command: str,
    working_dir: str,
    env: dict,
    timeout: int = 30
) -> str:
    """Execute a playwright-cli command and return its stdout output."""
    full_cmd = f'playwright-cli -s={session_id} {command}'

    try:
        process = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=working_dir
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )

        output = stdout.decode('utf-8', errors='replace')
        if not output.strip() and stderr:
            output = stderr.decode('utf-8', errors='replace')
        return output

    except asyncio.TimeoutError:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        return f"(command timed out after {timeout}s)"
    except Exception as e:
        return f"(command error: {e})"


async def cleanup_playwright_session(session_id: str, env: dict, working_dir: str):
    """Force close a playwright-cli session."""
    try:
        await exec_playwright(session_id, 'close', working_dir, env, timeout=10)
    except Exception:
        pass


# ============================================================================
# Evaluator Score Parser
# ============================================================================

def convert_output_to_input(output_items) -> List[dict]:
    """Convert response.output SDK objects to plain dicts for input list.

    The Responses API with store=False cannot reference stored items by ID.
    ResponseReasoningItem has an ID that causes 400 errors on subsequent calls.
    We filter those out and convert function_call/message items to plain dicts.
    """
    result = []
    for item in output_items:
        if item.type == "function_call":
            result.append({
                "type": "function_call",
                "call_id": item.call_id,
                "name": item.name,
                "arguments": item.arguments,
            })
        elif item.type == "message":
            for content in item.content:
                if hasattr(content, "text") and content.text:
                    result.append({
                        "role": "assistant",
                        "content": content.text,
                    })
        # Skip 'reasoning' items - they reference stored state (store=False)
    return result


def parse_eval_score(eval_output: str) -> Optional[float]:
    """Extract numeric score from evaluator run-code output."""
    match = re.search(r'###\s*Result\s*\n\s*([0-9.]+)', eval_output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    numbers = re.findall(r'\b([01](?:\.\d+)?)\b', eval_output)
    if numbers:
        try:
            return float(numbers[-1])
        except ValueError:
            pass

    return None


# ============================================================================
# ReAct Loop Core (v8 - bash based)
# ============================================================================

async def run_react_test(
    task: TestTask,
    model: str,
    timeout: int,
    working_dir: str,
    headed: bool = False,
    pass_num: int = 1,
    max_steps: int = 50,
    reasoning_effort: str = "medium",
    raw_logs_dir: Optional[str] = None,
) -> TestResult:
    """Run a single test using bash-based tool calling loop."""
    start_time = time.time()
    total_tokens = 0
    log_lines = []

    session_id = f"{task.task_id}_{int(time.time() * 1000) % 100000}"
    eval_file = write_evaluator_file(task, session_id)
    website_url = f"file://{os.path.abspath(os.path.join(task.website_dir, 'index.html'))}"

    # Pin this task to a single endpoint for KV cache locality
    pinned_endpoint = get_next_endpoint()
    pinned_client = get_async_client_for_endpoint(pinned_endpoint)

    env = os.environ.copy()
    env['PLAYWRIGHT_MCP_BROWSER'] = 'chromium'
    env['PLAYWRIGHT_MCP_ALLOW_UNRESTRICTED_FILE_ACCESS'] = 'true'
    if headed:
        env['PLAYWRIGHT_MCP_HEADLESS'] = 'false'

    abs_working_dir = os.path.abspath(working_dir)
    os.makedirs(abs_working_dir, exist_ok=True)

    log_lines.append("=== REACT TEST LOG (v8 - bash based) ===")
    log_lines.append(f"Task: {task.task_id} | Website: {task.website_name} | Model: {model}")
    log_lines.append(f"Session: {session_id} | Max steps: {max_steps}")
    log_lines.append(f"Task instruction: {task.instruction}")
    log_lines.append("")

    score = None
    step_counter = 0       # counts bash tool invocations
    reason = ""
    error_msg = None
    turn = 0

    try:
        # Step 1: Open browser
        log_lines.append("[Init] OPEN BROWSER")
        open_output = await exec_playwright(
            session_id, f'open "{website_url}"', abs_working_dir, env, timeout=30
        )
        log_lines.append(f"Result: {open_output[:500]}")
        log_lines.append("")

        # Inject Date override if set_system_time config exists
        time_override_js = get_system_time_override(task)
        if time_override_js:
            # Write JS to temp file to avoid shell escaping issues
            time_script_path = os.path.join(abs_working_dir, '.time_override.js')
            with open(time_script_path, 'w') as f:
                f.write(f'async page => {{ await page.addInitScript(`{time_override_js}`); await page.reload(); }}')
            await exec_playwright(
                session_id, f'run-code "$(cat {time_script_path})"',
                abs_working_dir, env, timeout=15
            )
            log_lines.append(f"[Init] Date override injected: {task.config[0]['parameters']['date']}")

        snapshot_hint = get_latest_snapshot_hint(abs_working_dir)

        system_prompt = SYSTEM_PROMPT.format(
            session_id=session_id,
            task_instruction=task.instruction,
            evaluation_logic=task.evaluation_logic,
            max_steps=max_steps,
        )

        # Responses API input list
        input_list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Browser opened:\n{open_output}{snapshot_hint}\n\nRead the snapshot file to see the page, then begin the task."},
        ]

        # Step 2: Tool calling loop
        overall_deadline = start_time + timeout
        max_turns = 80  # safety limit on API calls

        for turn in range(1, max_turns + 1):
            if time.time() > overall_deadline:
                log_lines.append(f"[Turn {turn}] TIMEOUT")
                reason = f"Timeout after {timeout}s"
                break

            if step_counter >= max_steps:
                reason = f"Max steps ({max_steps}) reached"
                log_lines.append(f"[Turn {turn}] MAX STEPS REACHED ({step_counter})")
                break

            # Call LLM with tools
            remaining_time = overall_deadline - time.time()
            try:
                response, usage_info = await asyncio.wait_for(
                    call_openai_api_with_tools_async(
                        input_messages=input_list,
                        tools=TOOLS,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        stage="react_test",
                        client=pinned_client,
                    ),
                    timeout=min(remaining_time, 180)
                )
            except asyncio.TimeoutError:
                log_lines.append(f"[Turn {turn}] LLM call timed out")
                reason = f"LLM call timed out at turn {turn}"
                break

            if response is None:
                log_lines.append(f"[Turn {turn}] LLM returned None")
                reason = "LLM returned None response"
                break

            if usage_info:
                total_tokens += usage_info.get('total_tokens', 0)

            # Convert model output to plain dicts (filter out reasoning items)
            converted_output = convert_output_to_input(response.output)
            input_list += converted_output

            # Separate function_call items and log text output
            function_calls = [item for item in response.output if item.type == "function_call"]

            # Log text output from message items (if any)
            for item in response.output:
                if item.type == "message":
                    for content in item.content:
                        if hasattr(content, "text") and content.text:
                            log_lines.append(f"[Turn {turn}] LLM TEXT: {content.text[:500]}")

            log_lines.append(f"[Turn {turn}] {len(function_calls)} tool call(s): {[fc.name for fc in function_calls]}")

            if not function_calls:
                log_lines.append(f"  -> No tool calls, prompting retry")
                input_list.append({
                    "role": "user",
                    "content": "Please use the bash tool to run commands, or call evaluate_task when done."
                })
                continue

            # Execute each tool call
            is_terminal = False

            for fc in function_calls:
                tool_name = fc.name
                try:
                    tool_args = json.loads(fc.arguments)
                except json.JSONDecodeError:
                    tool_args = {}
                call_id = fc.call_id

                if tool_name == "bash":
                    command = tool_args.get("command", "")
                    cmd_timeout = tool_args.get("timeout", 30)
                    log_lines.append(f"    [bash] {command[:200]}")

                    result_text = await execute_bash(command, abs_working_dir, env, cmd_timeout)

                    # Append latest snapshot hint
                    result_text += get_latest_snapshot_hint(abs_working_dir)

                    log_lines.append(f"    Output: ({len(result_text)} chars)")
                    step_counter += 1

                elif tool_name == "evaluate_task":
                    log_lines.append("    [tool] evaluate_task()")
                    # Dismiss any blocking dialogs before evaluating
                    await exec_playwright(session_id, 'dialog-dismiss', abs_working_dir, env, timeout=5)
                    eval_output = await exec_playwright(
                        session_id,
                        f'run-code "$(cat {eval_file})"',
                        abs_working_dir, env, timeout=15
                    )
                    eval_score = parse_eval_score(eval_output)
                    log_lines.append(f"    Evaluator output: {eval_output[:300]}")
                    log_lines.append(f"    Score: {eval_score}")
                    result_text = f"Evaluation score: {eval_score}"
                    is_terminal = True
                    score = eval_score

                else:
                    log_lines.append(f"    [unknown tool] {tool_name}({tool_args})")
                    result_text = f"Unknown tool: {tool_name}. Use 'bash' or 'evaluate_task'."

                # Append function_call_output to input list
                input_list.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result_text,
                })

            log_lines.append(f"  Steps so far: {step_counter}")
            log_lines.append("")

            if is_terminal:
                break

        else:
            reason = f"Max turns ({max_turns}) exceeded"
            log_lines.append(f"[MAX TURNS] Exceeded {max_turns} LLM calls")

        # Auto-evaluate if we didn't get a score yet
        if score is None and not error_msg:
            log_lines.append("[AUTO-EVALUATE] Running evaluator (no explicit evaluate_task)")
            await exec_playwright(session_id, 'dialog-dismiss', abs_working_dir, env, timeout=5)
            eval_output = await exec_playwright(
                session_id,
                f'run-code "$(cat {eval_file})"',
                abs_working_dir, env, timeout=15
            )
            score = parse_eval_score(eval_output)
            log_lines.append(f"  Score: {score}")

    except Exception as e:
        import traceback
        error_msg = str(e)
        reason = f"Error: {error_msg}"
        log_lines.append(f"[ERROR] {traceback.format_exc()}")
        logger.error(f"  Error running test {task.task_id}: {e}")

    finally:
        await cleanup_playwright_session(session_id, env, abs_working_dir)
        cleanup_evaluator_file(eval_file)

    duration = time.time() - start_time

    log_lines.append("")
    log_lines.append("=== SUMMARY ===")
    log_lines.append(f"Steps: {step_counter} | Turns: {turn} | Tokens: {total_tokens} | Duration: {duration:.1f}s | Score: {score}")
    log_lines.append("")

    if raw_logs_dir is not None:
        os.makedirs(raw_logs_dir, exist_ok=True)
        raw_filename = f"raw_react_output_{task.website_name}_{task.task_id}_pass{pass_num}.txt"
        raw_path = os.path.join(raw_logs_dir, raw_filename)
        try:
            with open(raw_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_lines))
        except OSError:
            pass

    return TestResult(
        task_id=task.task_id,
        website_name=task.website_name,
        result=score_to_result(score),
        agent_result=None,
        reason=reason,
        steps_taken=step_counter,
        final_evaluation=score,
        duration=duration,
        error=error_msg,
    )


# ============================================================================
# Test Orchestration
# ============================================================================

async def run_all_tests(
    tasks: List[tuple],
    concurrent: int,
    model: str,
    timeout: int,
    output_path: str,
    working_dir: str,
    headed: bool = False,
    max_steps: int = 50,
    reasoning_effort: str = "medium",
) -> List[TestResult]:
    """Run all tests with concurrent execution."""
    semaphore = asyncio.Semaphore(concurrent)

    # All output files go under the same directory as output_path
    run_dir = os.path.dirname(output_path)
    jsonl_path = os.path.join(run_dir, 'results.jsonl')
    raw_logs_dir = os.path.join(run_dir, 'raw_logs')
    os.makedirs(raw_logs_dir, exist_ok=True)

    async def run_with_semaphore(task: TestTask, pass_num: int, index: int) -> TestResult:
        async with semaphore:
            pass_info = f"[P{pass_num}]" if pass_num > 0 else ""
            logger.info(f"[{index + 1}/{len(tasks)}]{pass_info} Testing {task.website_name}/{task.task_id}")

            task_working_dir = os.path.join(working_dir, f"{task.task_id}_{pass_num}_{int(time.time()*1000)%100000}")
            os.makedirs(task_working_dir, exist_ok=True)

            result = await run_react_test(
                task, model, timeout, task_working_dir,
                headed, pass_num, max_steps, reasoning_effort,
                raw_logs_dir=raw_logs_dir,
            )
            result.pass_num = pass_num

            with open(jsonl_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(result.to_dict(), ensure_ascii=False) + '\n')

            status_map = {'SUCCESS': '\u2713', 'PARTIAL': '\u25d0', 'FAILURE': '\u2717', 'ERROR': '!'}
            status = status_map.get(result.result, '?')
            score_str = f" [{result.final_evaluation:.1f}]" if result.final_evaluation is not None else ""
            logger.info(f"  {status} {result.result}{score_str} ({result.duration:.1f}s, {result.steps_taken} steps)")

            try:
                import shutil
                shutil.rmtree(task_working_dir, ignore_errors=True)
            except Exception:
                pass

            return result

    coros = [run_with_semaphore(task, pass_num, i) for i, (task, pass_num) in enumerate(tasks)]
    results = await asyncio.gather(*coros)

    return results


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Run functional tests on generated websites using bash-based tool calling (LLM + playwright-cli)'
    )
    parser.add_argument('--website-dir', type=str,
                        help='Single website directory to test')
    parser.add_argument('--batch-dir', type=str,
                        help='Batch directory containing multiple websites')
    parser.add_argument('--task-id', type=str,
                        help='Specific task ID to test')
    parser.add_argument('--concurrent', type=int, default=5,
                        help='Number of concurrent test instances')
    parser.add_argument('--model', type=str, default='gpt-5.1',
                        help='Model to use (default: gpt-5.1)')
    parser.add_argument('--timeout', type=int, default=300,
                        help='Timeout per test in seconds')
    parser.add_argument('--output-dir', type=str,
                        default='results/test_results',
                        help='Output directory (a timestamped subfolder will be created inside)')
    parser.add_argument('--headed', action='store_true',
                        help='Run browser in headed mode (visible)')
    parser.add_argument('--working-dir', type=str, default='/tmp/react_test_workdir',
                        help='Working directory for playwright-cli')
    parser.add_argument('--passes', type=int, default=1,
                        help='Number of test passes for stability testing')
    parser.add_argument('--max-steps', type=int, default=50,
                        help='Maximum bash steps per test (default: 50)')
    parser.add_argument('--reasoning-effort', type=str, default='medium',
                        choices=['minimal', 'low', 'medium', 'high'],
                        help='LLM reasoning effort (default: medium)')

    # LLM configuration
    parser.add_argument('--endpoints', type=str, nargs='+',
                        default=None,
                        help='Azure OpenAI endpoint(s)')
    parser.add_argument('--config', type=str, default=None,
                        help='Config JSON file for endpoint/model settings')

    args = parser.parse_args()

    if os.system('which playwright-cli > /dev/null 2>&1') != 0:
        logger.error("playwright-cli not found. Install with: npm install -g @anthropic-ai/playwright-cli")
        sys.exit(1)

    if not args.website_dir and not args.batch_dir:
        parser.error("Either --website-dir or --batch-dir is required")

    if args.config:
        with open(args.config, 'r') as f:
            config = json.load(f)
        configure_load_balancing(
            endpoints=config.get('endpoints'),
            deployment=config.get('deployment', args.model),
        )
    elif args.endpoints:
        configure_load_balancing(endpoints=args.endpoints, deployment=args.model)
    else:
        configure_load_balancing(deployment=args.model)

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
    logger.info(f"Model: {args.model} | Max steps: {args.max_steps} | Reasoning: {args.reasoning_effort}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(args.output_dir, timestamp)
    os.makedirs(run_dir, exist_ok=True)
    output_path = os.path.join(run_dir, 'results.json')

    logger.info(f"Output directory: {run_dir}")

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
            headed=args.headed,
            max_steps=args.max_steps,
            reasoning_effort=args.reasoning_effort,
        ))

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
                pass_output_path = os.path.join(run_dir, f'results_pass{pass_num}.json')
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
            print(f"Results saved to: {run_dir}")

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
                    stability = "stable \u2713"
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
        os.system('playwright-cli close-all 2>/dev/null')


if __name__ == '__main__':
    main()
