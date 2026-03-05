#!/usr/bin/env python3
"""
ReAct Test Runner (structured tools version) - Uses OpenAI Responses API native tool calling.

Key design: native multi-tool calling with structured browser tools
- Playwright-cli commands are defined as OpenAI function tools (browser_click, browser_fill, etc.)
- LLM outputs function_call items; we execute each and send function_call_output back
- LLM sees individual results from every tool call before deciding next actions
- One page snapshot is taken after each turn's browser actions and sent as a user message
- Snapshot is auto-truncated to 300 lines (head-keep)

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
# Tool Definitions (OpenAI function calling format)
# ============================================================================

PLAYWRIGHT_TOOLS = [
    {
        "type": "function",
        "name": "browser_click",
        "description": "Click an element on the page by its reference ID from the snapshot.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Element reference ID (e.g. 'e5')"
                }
            },
            "required": ["ref"],
        },
    },
    {
        "type": "function",
        "name": "browser_fill",
        "description": "Fill text into an input field.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Element reference ID (e.g. 'e10')"
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into the field"
                },
            },
            "required": ["ref", "text"],
        },
    },
    {
        "type": "function",
        "name": "browser_select",
        "description": "Select a dropdown option by value.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Element reference ID (e.g. 'e8')"
                },
                "value": {
                    "type": "string",
                    "description": "The option value to select"
                },
            },
            "required": ["ref", "value"],
        },
    },
    {
        "type": "function",
        "name": "browser_scroll",
        "description": "Scroll the page vertically. Use positive dy to scroll down, negative to scroll up.",
        "parameters": {
            "type": "object",
            "properties": {
                "dy": {
                    "type": "integer",
                    "description": "Vertical scroll distance in pixels (e.g. 300 = down, -300 = up)"
                }
            },
            "required": ["dy"],
        },
    },
    {
        "type": "function",
        "name": "browser_snapshot",
        "description": "Take a fresh snapshot of the current page. Returns the truncated accessibility tree (~300 lines). Use this when you need to see the current page state without performing a browser action.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "browser_localstorage_keys",
        "description": "List all localStorage keys with their value sizes and a short preview. Use this to understand the data structure before reading specific keys.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "browser_localstorage_get",
        "description": "Read the full value of a specific localStorage key. Use after browser_localstorage_keys to read a key you need.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The localStorage key to read (e.g. 'posts', 'userSession')"
                }
            },
            "required": ["key"],
        },
    },
    {
        "type": "function",
        "name": "snapshot_search",
        "description": "Search for a keyword in the full page snapshot. Returns matching lines with surrounding context and line numbers. Use this to find elements not visible in the truncated snapshot.",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "The keyword to search for (case-insensitive)"
                }
            },
            "required": ["keyword"],
        },
    },
    {
        "type": "function",
        "name": "snapshot_more",
        "description": "Read a specific line range from the current page snapshot. Use after seeing a truncated snapshot to view more lines.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_line": {
                    "type": "integer",
                    "description": "Starting line number (1-based)"
                },
                "end_line": {
                    "type": "integer",
                    "description": "Ending line number (inclusive)"
                },
            },
            "required": ["start_line", "end_line"],
        },
    },
    {
        "type": "function",
        "name": "evaluate_task",
        "description": "Run the evaluator to check if the task has been completed successfully. Call this when you believe you have finished the task.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "give_up",
        "description": "Give up on the task if it seems impossible (e.g. required UI elements don't exist, data is missing).",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why the task cannot be completed"
                }
            },
            "required": ["reason"],
        },
    },
    {
        "type": "function",
        "name": "browser_dialog_accept",
        "description": "Accept (click OK/Yes) a JavaScript dialog (alert, confirm, prompt). Use this when a modal dialog is blocking the page.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "type": "function",
        "name": "browser_dialog_dismiss",
        "description": "Dismiss (click Cancel/No) a JavaScript dialog (alert, confirm, prompt). Use this when a modal dialog is blocking the page.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


# ============================================================================
# System Prompt (v4 - tool calling)
# ============================================================================

REACT_SYSTEM_PROMPT = '''You are a website functional test agent. You operate a browser via tool calls to complete a given test task.

## Page Snapshot
After each set of browser actions you receive a truncated accessibility tree snapshot (first ~300 lines).
If the snapshot is truncated and you need to see more, use:
- snapshot_search(keyword) to find specific elements
- snapshot_more(start_line, end_line) to read a specific line range

Snapshot format:
- [ref=e5] is the element reference used in browser_click/browser_fill/browser_select
- Element types: link, button, textbox, listitem, heading, article, img, etc.
- Text content appears in quotes after the element type
- Nested elements are indented

## Rules
1. Complete the task through UI operations ONLY (clicking, filling forms, selecting).
2. Navigate between pages by clicking links, do NOT modify URLs directly.
3. Do NOT directly modify localStorage or call JavaScript APIs.
4. Read the snapshot carefully to find the right elements before clicking.
5. If you need to see more of the page, use browser_scroll or snapshot_search/snapshot_more.
6. Call multiple tools per turn for efficiency (e.g. fill a form then click submit).
7. Always click Save/Submit buttons to persist changes BEFORE calling evaluate_task. The evaluator checks localStorage which is only updated after saving.
8. If a modal dialog (alert/confirm/prompt) appears and blocks the page, use browser_dialog_accept or browser_dialog_dismiss to handle it.
9. If clicking a checkbox input times out, try clicking its label element instead.
10. For tasks requiring multiple items, gather all needed info (IDs, names) in one pass before switching pages.
11. You have a limited step budget. Be efficient and avoid unnecessary actions.
12. DATA-FIRST STRATEGY: For tasks requiring items matching specific criteria (cost, rating, date, count), read localStorage data first using browser_localstorage_keys and browser_localstorage_get to identify qualifying items BEFORE browsing the UI. This is much more efficient than checking items one by one through the UI.
13. If browser_select fails (dropdown has no options or wrong values), switch to reading localStorage data directly instead of retrying the filter.
14. When actions have logical dependencies (e.g. compare THEN bookmark the winner), complete each step and verify the result before proceeding. Do NOT parallelize dependent actions.

## Test Task
{task_instruction}

## Evaluation Logic (for reference - helps you understand what the evaluator checks)
```javascript
{evaluation_logic}
```

You have {max_steps} browser action steps available. Plan efficiently.
'''


# ============================================================================
# playwright-cli Command Executor
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
# Snapshot Reader
# ============================================================================

SNAPSHOT_MAX_LINES = 300


def _get_latest_snapshot_path(working_dir: str) -> Optional[str]:
    """Return the path to the most recent snapshot YAML file, or None."""
    snapshot_dir = os.path.join(working_dir, '.playwright-cli')
    if not os.path.isdir(snapshot_dir):
        return None
    yml_files = sorted(
        glob.glob(os.path.join(snapshot_dir, 'page-*.yml')),
        key=os.path.getmtime
    )
    return yml_files[-1] if yml_files else None


def _read_snapshot_lines(working_dir: str) -> List[str]:
    """Read all lines from the latest snapshot file."""
    path = _get_latest_snapshot_path(working_dir)
    if not path:
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().splitlines()


def read_latest_snapshot(working_dir: str, max_lines: int = SNAPSHOT_MAX_LINES) -> str:
    """Read the most recent snapshot YAML, truncated to max_lines."""
    lines = _read_snapshot_lines(working_dir)
    if not lines:
        return "(no snapshot available)"

    total = len(lines)
    if max_lines > 0 and total > max_lines:
        result = '\n'.join(lines[:max_lines])
        result += f'\n... ({total - max_lines} more lines, use snapshot_search or snapshot_more to see them)'
        return result

    return '\n'.join(lines)


def do_snapshot_search(working_dir: str, keyword: str, context: int = 3) -> str:
    """Search for a keyword in the current snapshot, returning matching lines with context."""
    lines = _read_snapshot_lines(working_dir)
    if not lines:
        return "(no snapshot available)"

    keyword_lower = keyword.lower()
    matches = [i for i, line in enumerate(lines) if keyword_lower in line.lower()]

    if not matches:
        return f"No matches found for \"{keyword}\" in snapshot ({len(lines)} lines total)"

    result_parts = []
    shown = set()
    for match_idx in matches:
        start = max(0, match_idx - context)
        end = min(len(lines), match_idx + context + 1)
        for i in range(start, end):
            if i not in shown:
                marker = " >>>" if i == match_idx else "    "
                result_parts.append(f"L{i+1:>4}{marker} {lines[i]}")
                shown.add(i)
        result_parts.append("    ---")

    header = f"Found {len(matches)} match(es) for \"{keyword}\" (snapshot has {len(lines)} lines total):"
    return header + '\n' + '\n'.join(result_parts)


def do_snapshot_more(working_dir: str, start_line: int, end_line: int) -> str:
    """Read a specific line range from the current snapshot."""
    lines = _read_snapshot_lines(working_dir)
    if not lines:
        return "(no snapshot available)"

    total = len(lines)
    start = max(1, start_line) - 1
    end = min(total, end_line)

    if start >= total:
        return f"(line {start_line} is beyond the end of the snapshot, which has {total} lines)"

    selected = lines[start:end]
    result = '\n'.join(f"L{start+i+1:>4}  {line}" for i, line in enumerate(selected))

    if end < total:
        result += f'\n... ({total - end} more lines remaining)'

    return result


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
# Tool Executor
# ============================================================================

async def execute_tool(
    tool_name: str,
    tool_args: dict,
    session_id: str,
    eval_file: str,
    abs_working_dir: str,
    env: dict,
    log_lines: List[str],
) -> Tuple[str, bool, bool, Optional[float], str]:
    """Execute a single tool call and return its result.

    Returns: (result_text, is_browser_action, is_terminal, score, reason)
    """
    if tool_name == "browser_click":
        ref = tool_args.get("ref", "")
        log_lines.append(f"    [tool] browser_click({ref})")
        output = await exec_playwright(session_id, f'click {ref}', abs_working_dir, env, timeout=15)
        log_lines.append(f"    Output: {output[:200]}")
        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot = read_latest_snapshot(abs_working_dir)
        return f"{output}\n\nPage snapshot:\n{snapshot}", True, False, None, ""

    elif tool_name == "browser_fill":
        ref = tool_args.get("ref", "")
        text = tool_args.get("text", "")
        log_lines.append(f'    [tool] browser_fill({ref}, "{text[:50]}")')
        # Escape double quotes in text for shell
        escaped_text = text.replace('"', '\\"')
        output = await exec_playwright(session_id, f'fill {ref} "{escaped_text}"', abs_working_dir, env, timeout=15)
        log_lines.append(f"    Output: {output[:200]}")
        return output, True, False, None, ""

    elif tool_name == "browser_select":
        ref = tool_args.get("ref", "")
        value = tool_args.get("value", "")
        log_lines.append(f'    [tool] browser_select({ref}, "{value}")')
        escaped_value = value.replace('"', '\\"')
        output = await exec_playwright(session_id, f'select {ref} "{escaped_value}"', abs_working_dir, env, timeout=15)
        log_lines.append(f"    Output: {output[:200]}")
        # On failure, enumerate actual <option> values to help LLM retry or switch strategy
        if "Timeout" in output or "did not find" in output or "Error" in output:
            log_lines.append("    -> Select failed, enumerating options")
            safe_ref = ref.replace("'", "\\'")
            enum_js = (
                "async page => { return await page.evaluate((r) => {"
                " var el = document.querySelector('[aria-ref="'+r+'"]');"
                " if (!el || el.tagName !== 'SELECT') return 'Not a select';"
                " return JSON.stringify(Array.from(el.options).map(function(o)"
                "{ return {value:o.value,text:o.textContent.trim()}; }));"
                " }, '" + safe_ref + "'); }"
            )
            escaped_enum = enum_js.replace('"', '\\"')
            opts_out = await exec_playwright(session_id, f'run-code "{escaped_enum}"', abs_working_dir, env, timeout=10)
            log_lines.append(f"    Options: {opts_out[:300]}")
            output = (
                f'Select failed for "{value}". Available options:\n{opts_out}\n'
                'Retry with an exact value from the list, or read localStorage '
                'data to find qualifying items without filters.'
            )
        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot = read_latest_snapshot(abs_working_dir)
        return f"{output}\n\nPage snapshot:\n{snapshot}", True, False, None, ""

    elif tool_name == "browser_scroll":
        dy = tool_args.get("dy", 300)
        log_lines.append(f"    [tool] browser_scroll(dy={dy})")
        await exec_playwright(session_id, f'mousewheel 0 {dy}', abs_working_dir, env, timeout=10)
        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot = read_latest_snapshot(abs_working_dir)
        direction = "down" if dy > 0 else "up"
        result = f"Scrolled {direction}.\n\nPage snapshot:\n{snapshot}"
        log_lines.append(f"    Output: {result[:200]}")
        return result, True, False, None, ""

    elif tool_name == "browser_snapshot":
        log_lines.append("    [tool] browser_snapshot()")
        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot = read_latest_snapshot(abs_working_dir)
        log_lines.append(f"    Snapshot: ({len(snapshot.splitlines())} lines)")
        return f"Page snapshot:\n{snapshot}", False, False, None, ""

    elif tool_name == "browser_localstorage_keys":
        log_lines.append("    [tool] browser_localstorage_keys()")
        js_code = "async page => { return await page.evaluate(() => { const r = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); const v = localStorage.getItem(k); r[k] = { length: v.length, preview: v.substring(0, 80) }; } return JSON.stringify(r, null, 2); }); }"
        escaped_js = js_code.replace('"', '\\"')
        output = await exec_playwright(session_id, f'run-code "{escaped_js}"', abs_working_dir, env, timeout=10)
        log_lines.append(f"    Output: {output[:500]}")
        return output, False, False, None, ""

    elif tool_name == "browser_localstorage_get":
        key = tool_args.get("key", "")
        log_lines.append(f'    [tool] browser_localstorage_get("{key}")')
        # Escape single quotes in the key for JS string
        safe_key = key.replace("'", "\\'")
        js_code = f"async page => {{ return await page.evaluate(() => localStorage.getItem('{safe_key}')); }}"
        escaped_js = js_code.replace('"', '\\"')
        output = await exec_playwright(session_id, f'run-code "{escaped_js}"', abs_working_dir, env, timeout=10)
        log_lines.append(f"    Output: ({len(output)} chars)")
        # Truncate very large values
        if len(output) > 5000:
            output = output[:5000] + f"\n... (truncated, {len(output) - 5000} more chars)"
        return output, False, False, None, ""

    elif tool_name == "snapshot_search":
        keyword = tool_args.get("keyword", "")
        log_lines.append(f'    [tool] snapshot_search("{keyword}")')
        result = do_snapshot_search(abs_working_dir, keyword)
        log_lines.append(f"    Result: {result[:200]}")
        return result, False, False, None, ""

    elif tool_name == "snapshot_more":
        start_line = tool_args.get("start_line", 1)
        end_line = tool_args.get("end_line", 300)
        log_lines.append(f"    [tool] snapshot_more({start_line}, {end_line})")
        result = do_snapshot_more(abs_working_dir, start_line, end_line)
        log_lines.append(f"    Result: ({len(result.splitlines())} lines)")
        return result, False, False, None, ""

    elif tool_name == "evaluate_task":
        log_lines.append("    [tool] evaluate_task()")
        eval_output = await exec_playwright(
            session_id,
            f'run-code "$(cat {eval_file})"',
            abs_working_dir, env, timeout=15
        )
        score = parse_eval_score(eval_output)
        log_lines.append(f"    Evaluator output: {eval_output[:300]}")
        log_lines.append(f"    Score: {score}")
        return f"Evaluation score: {score}", False, True, score, ""

    elif tool_name == "give_up":
        reason = tool_args.get("reason", "unknown")
        log_lines.append(f"    [tool] give_up({reason})")
        log_lines.append("    -> AUTO-EVALUATE on GIVE_UP")
        # Dismiss any blocking dialogs before evaluating
        await exec_playwright(session_id, 'dialog-dismiss', abs_working_dir, env, timeout=5)
        eval_output = await exec_playwright(
            session_id,
            f'run-code "$(cat {eval_file})"',
            abs_working_dir, env, timeout=15
        )
        score = parse_eval_score(eval_output)
        log_lines.append(f"    Score: {score}")
        return f"Evaluation score: {score}", False, True, score, f"Agent gave up: {reason}"

    elif tool_name == "browser_dialog_accept":
        log_lines.append("    [tool] browser_dialog_accept()")
        output = await exec_playwright(session_id, 'dialog-accept', abs_working_dir, env, timeout=10)
        log_lines.append(f"    Output: {output[:200]}")
        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot = read_latest_snapshot(abs_working_dir)
        return f"{output}\n\nPage snapshot:\n{snapshot}", True, False, None, ""

    elif tool_name == "browser_dialog_dismiss":
        log_lines.append("    [tool] browser_dialog_dismiss()")
        output = await exec_playwright(session_id, 'dialog-dismiss', abs_working_dir, env, timeout=10)
        log_lines.append(f"    Output: {output[:200]}")
        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot = read_latest_snapshot(abs_working_dir)
        return f"{output}\n\nPage snapshot:\n{snapshot}", True, False, None, ""

    else:
        log_lines.append(f"    [tool] UNKNOWN: {tool_name}({tool_args})")
        return f"Unknown tool: {tool_name}", False, False, None, ""


# ============================================================================
# ReAct Loop Core (v4 - native tool calling)
# ============================================================================

async def run_react_test(
    task: TestTask,
    model: str,
    timeout: int,
    working_dir: str,
    headed: bool = False,
    pass_num: int = 1,
    max_steps: int = 25,
    reasoning_effort: str = "medium",
    raw_logs_dir: Optional[str] = None,
) -> TestResult:
    """Run a single test using native OpenAI tool calling loop."""
    start_time = time.time()
    total_tokens = 0
    log_lines = []

    # Pin to one endpoint for KV cache locality
    pinned_endpoint = get_next_endpoint()
    pinned_client = get_async_client_for_endpoint(pinned_endpoint)

    session_id = f"{task.task_id}_{int(time.time() * 1000) % 100000}"
    eval_file = write_evaluator_file(task, session_id)
    website_url = f"file://{os.path.abspath(os.path.join(task.website_dir, 'index.html'))}"

    env = os.environ.copy()
    env['PLAYWRIGHT_MCP_BROWSER'] = 'chromium'
    env['PLAYWRIGHT_MCP_ALLOW_UNRESTRICTED_FILE_ACCESS'] = 'true'
    if headed:
        env['PLAYWRIGHT_MCP_HEADLESS'] = 'false'

    abs_working_dir = os.path.abspath(working_dir)
    os.makedirs(abs_working_dir, exist_ok=True)

    log_lines.append("=== REACT TEST LOG (v4 - tool calling) ===")
    log_lines.append(f"Task: {task.task_id} | Website: {task.website_name} | Model: {model}")
    log_lines.append(f"Session: {session_id} | Max steps: {max_steps}")
    log_lines.append(f"Task instruction: {task.instruction}")
    log_lines.append("")

    score = None
    step_counter = 0       # counts browser actions (click/fill/select/scroll)
    reason = ""
    error_msg = None
    turn = 0

    try:
        # Step 1: Open browser and get initial snapshot
        log_lines.append("[Init] OPEN BROWSER")
        open_output = await exec_playwright(
            session_id, f'open "{website_url}"', abs_working_dir, env, timeout=30
        )
        log_lines.append(f"Result: {open_output[:500]}")
        log_lines.append("")

        # Inject Date override if set_system_time config exists
        time_override_js = get_system_time_override(task)
        if time_override_js:
            time_script_path = os.path.join(abs_working_dir, '.time_override.js')
            with open(time_script_path, 'w') as f:
                f.write(f'async page => {{ await page.addInitScript(`{time_override_js}`); await page.reload(); }}')
            await exec_playwright(
                session_id, f'run-code "$(cat {time_script_path})"',
                abs_working_dir, env, timeout=15
            )
            log_lines.append(f"[Init] Date override injected: {task.config[0]['parameters']['date']}")

        await exec_playwright(session_id, 'snapshot', abs_working_dir, env, timeout=10)
        snapshot_yaml = read_latest_snapshot(abs_working_dir)

        system_prompt = REACT_SYSTEM_PROMPT.format(
            task_instruction=task.instruction,
            evaluation_logic=task.evaluation_logic,
            max_steps=max_steps,
        )

        # Responses API input list (flat list of items)
        input_list = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Browser opened. Initial page snapshot:\n{snapshot_yaml}"},
        ]

        # Step 2: Tool calling loop
        overall_deadline = start_time + timeout
        max_turns = 50  # safety limit on API calls

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
                        tools=PLAYWRIGHT_TOOLS,
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

            # Convert model output to plain dicts (filter out reasoning items
            # which cause store=False errors on subsequent API calls)
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

            # Cap tool calls per turn to prevent mass-clicking waste
            MAX_TOOLS_PER_TURN = 6
            if len(function_calls) > MAX_TOOLS_PER_TURN:
                log_lines.append(f"  -> Capping from {len(function_calls)} to {MAX_TOOLS_PER_TURN} tool calls")
                function_calls = function_calls[:MAX_TOOLS_PER_TURN]

            if not function_calls:
                # Model didn't call any tools - might be stuck or confused
                log_lines.append(f"  -> No tool calls, prompting retry")
                input_list.append({
                    "role": "user",
                    "content": "Please use the available tools to interact with the page. Call browser_click, browser_fill, browser_select, browser_scroll, browser_snapshot, browser_localstorage_keys, browser_localstorage_get, snapshot_search, snapshot_more, evaluate_task, or give_up."
                })
                continue

            # Execute each tool call and collect results
            is_terminal = False

            for fc in function_calls:
                tool_name = fc.name
                try:
                    tool_args = json.loads(fc.arguments)
                except json.JSONDecodeError:
                    tool_args = {}
                call_id = fc.call_id

                result_text, is_browser, is_term, eval_score, term_reason = \
                    await execute_tool(
                        tool_name, tool_args,
                        session_id, eval_file,
                        abs_working_dir, env, log_lines,
                    )

                if is_browser:
                    step_counter += 1

                # Append function_call_output to input list
                input_list.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result_text[:8000],
                })

                if is_term:
                    is_terminal = True
                    score = eval_score
                    if term_reason:
                        reason = term_reason

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
            # Try to dismiss any blocking dialogs first
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
    max_steps: int = 25,
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
        description='Run functional tests on generated websites using native tool calling (LLM + playwright-cli)'
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
    parser.add_argument('--max-steps', type=int, default=35,
                        help='Maximum browser action steps per test (default: 35)')
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
