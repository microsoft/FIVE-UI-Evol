#!/usr/bin/env python3
"""
Claude Test Runner - Orchestrates website functional testing using Claude Code.

This script coordinates the testing of generated websites by:
1. Starting the Browser API server
2. Loading tasks from website directories
3. Spawning Claude Code instances (via `claude -p`) to execute tests
4. Collecting and aggregating results
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
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


@dataclass
class TestResult:
    """Result of a single test."""
    task_id: str
    website_name: str
    result: str  # SUCCESS, PARTIAL, FAILURE, ERROR (from score)
    pass_num: int = 1  # Pass number for stability testing
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


# ============================================================================
# Prompt Template (Text-based)
# ============================================================================

CLAUDE_PROMPT_TEMPLATE = '''你需要完成网站功能测试任务。

## 浏览器 API (纯文本)
服务地址: http://localhost:{port}

### 核心概念
- 每次操作后返回页面的 **elements** (完整 HTML 源码) 和 **text** (页面可见文本)
- 分析 HTML 找到可点击元素，使用 CSS 选择器操作
- **不能直接修改 localStorage**，必须通过 UI 操作

### 可用操作

1. **启动会话并打开网站**:
```bash
curl -s -X POST http://localhost:{port}/api/session/start -H "Content-Type: application/json" -d '{{"url":"{website_url}"}}'
```
返回: session_id, url

2. **获取页面状态** (元素 + 文本):
```bash
curl -s http://localhost:{port}/api/session/SESSION_ID/page
```
返回: elements, text, url, title

3. **执行操作** (点击或输入):
```bash
# 点击元素 (使用 CSS 选择器)
curl -s -X POST http://localhost:{port}/api/session/SESSION_ID/act -H "Content-Type: application/json" -d '{{"action":"click","selector":"button.btn-primary"}}'

# 点击链接导航到其他页面
curl -s -X POST http://localhost:{port}/api/session/SESSION_ID/act -H "Content-Type: application/json" -d '{{"action":"click","selector":"a[href=\\"forums.html\\"]"}}'

# 输入文本
curl -s -X POST http://localhost:{port}/api/session/SESSION_ID/act -H "Content-Type: application/json" -d '{{"action":"type","selector":"input[name=\\"keywords\\"]","text":"bakery","press_enter":true}}'
```
返回: success, elements, text, url

4. **滚动页面**:
```bash
curl -s -X POST http://localhost:{port}/api/session/SESSION_ID/scroll -H "Content-Type: application/json" -d '{{"direction":"down","amount":300}}'
```

5. **运行评估器**:
```bash
curl -s -X POST http://localhost:{port}/api/session/SESSION_ID/evaluate -H "Content-Type: application/json" -d '{{"logic":"return true;"}}'
```

6. **关闭会话**:
```bash
curl -s -X DELETE http://localhost:{port}/api/session/SESSION_ID
```

### 重要注意事项
**必须先访问 index.html**：网站的数据初始化脚本只在 index.html 中运行。如果直接跳转到其他页面（如 search.html、category.html），localStorage 中不会有任何产品/商家数据，导致搜索和筛选返回空结果。

### 工作流程
1. 启动会话，打开 **index.html**（这会初始化 localStorage 数据）
2. 获取页面状态 (/page)，分析 elements 和 text
3. 通过点击页面上的链接导航到目标页面（必须通过点击，不能直接跳转）
4. 根据任务指令执行操作 (/act)
5. 检查返回的 elements 和 text 确认操作结果
6. 重复直到完成任务
7. 运行评估器验证 (/evaluate)
8. 关闭会话

### 元素选择技巧
- 使用 CSS 选择器定位元素
- 常用选择器:
  - `button[data-action="contact-business"]` - 带 data-action 的按钮
  - `article.business-card` - 商家卡片 (可点击进入详情)
  - `input[name="senderName"]` - 表单输入框
  - `a[href="categories.html"]` - 链接
  - `select#sortSelect` - 下拉选择框
  - `input[type="checkbox"]` - 复选框

## 测试任务
{task_instruction}

## 评估逻辑
```javascript
{evaluation_logic}
```

## 输出要求
完成测试后，输出以下 JSON:
```json
{{
  "result": "SUCCESS/PARTIAL/FAILURE",
  "reason": "说明完成了什么操作",
  "steps_taken": 5,
  "final_evaluation": 1.0
}}
```
注意：
- result: 你对任务完成情况的判断（SUCCESS=完全成功, PARTIAL=部分完成, FAILURE=失败）
- final_evaluation: 评估器返回的分数（0.0-1.0）
'''


# ============================================================================
# Task Loading
# ============================================================================

def load_tasks_from_website(website_dir: str) -> List[TestTask]:
    """Load test tasks from a website directory."""
    tasks = []
    website_name = os.path.basename(website_dir)

    # Load rewritten tasks
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

    # Create TestTask objects
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
            ground_truth=task.get('ground_truth')
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
# Claude Code Execution
# ============================================================================

async def run_claude_test(
    task: TestTask,
    port: int,
    model: str,
    timeout: int,
    working_dir: str
) -> TestResult:
    """Run a single test using Claude Code."""
    start_time = time.time()

    # Build the prompt
    website_url = f"file://{os.path.abspath(os.path.join(task.website_dir, 'index.html'))}"
    prompt = CLAUDE_PROMPT_TEMPLATE.format(
        port=port,
        website_url=website_url,
        task_instruction=task.instruction,
        evaluation_logic=task.evaluation_logic.replace('\n', ' ')
    )

    try:
        # Set up environment with proxy if configured
        env = os.environ.copy()
        if os.environ.get('CLAUDE_PROXY_URL'):
            env['ANTHROPIC_BASE_URL'] = os.environ['CLAUDE_PROXY_URL']

        process = await asyncio.create_subprocess_exec(
            'claude', '-p', prompt,
            '--model', model,
            '--dangerously-skip-permissions',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
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
            return TestResult(
                task_id=task.task_id,
                website_name=task.website_name,
                result='ERROR',
                error='Timeout exceeded',
                duration=time.time() - start_time
            )

        duration = time.time() - start_time
        output = stdout.decode('utf-8', errors='replace')

        result = parse_claude_output(output)
        score = result.get('final_evaluation')
        agent_result = result.get('result')  # Agent's own judgment

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
        return TestResult(
            task_id=task.task_id,
            website_name=task.website_name,
            result='ERROR',
            error=str(e),
            duration=time.time() - start_time
        )


def parse_claude_output(output: str) -> Dict[str, Any]:
    """Parse the JSON result from Claude's output."""
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
    port: int,
    model: str,
    timeout: int,
    output_path: str,
    working_dir: str
) -> List[TestResult]:
    """Run all tests with concurrent execution."""
    semaphore = asyncio.Semaphore(concurrent)
    results = []

    jsonl_path = output_path.replace('.json', '.jsonl')
    os.makedirs(os.path.dirname(jsonl_path) or '.', exist_ok=True)

    async def run_with_semaphore(task: TestTask, pass_num: int, index: int) -> TestResult:
        async with semaphore:
            pass_info = f"[P{pass_num}]" if pass_num > 0 else ""
            logger.info(f"[{index + 1}/{len(tasks)}]{pass_info} Testing {task.website_name}/{task.task_id}")
            result = await run_claude_test(task, port, model, timeout, working_dir)
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

    # Calculate average score from final_evaluation
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

    # Calculate avg score per website
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
# Server Management
# ============================================================================

def start_api_server(port: int, headless: bool = True) -> subprocess.Popen:
    """Start the Browser API server."""
    cmd = [
        sys.executable,
        '-m', 'browser_api.server',
        '--port', str(port)
    ]
    if not headless:
        cmd.append('--no-headless')

    logger.info(f"Starting Browser API Server on port {port}")

    src_dir = os.path.dirname(os.path.abspath(__file__))

    process = subprocess.Popen(
        cmd,
        cwd=src_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    time.sleep(3)

    if process.poll() is not None:
        stdout, stderr = process.communicate()
        raise RuntimeError(f"Server failed to start: {stderr.decode()}")

    logger.info("Browser API Server started")
    return process


def stop_api_server(process: subprocess.Popen):
    """Stop the Browser API server."""
    logger.info("Stopping Browser API Server")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Run functional tests on generated websites using Claude Code'
    )
    parser.add_argument('--website-dir', type=str,
                        help='Single website directory to test')
    parser.add_argument('--batch-dir', type=str,
                        help='Batch directory containing multiple websites')
    parser.add_argument('--task-id', type=str,
                        help='Specific task ID to test')
    parser.add_argument('--concurrent', type=int, default=5,
                        help='Number of concurrent Claude Code instances')
    parser.add_argument('--port', type=int, default=5800,
                        help='Browser API server port')
    parser.add_argument('--model', type=str, default='sonnet',
                        help='Claude model (sonnet/opus/haiku)')
    parser.add_argument('--timeout', type=int, default=300,
                        help='Timeout per test in seconds')
    parser.add_argument('--output', type=str,
                        default='results/test_results/test_{timestamp}.json',
                        help='Output file path')
    parser.add_argument('--no-headless', action='store_true',
                        help='Disable headless mode')
    parser.add_argument('--no-server', action='store_true',
                        help='Skip starting API server')
    parser.add_argument('--working-dir', type=str, default='results/',
                        help='Working directory for Claude Code')
    parser.add_argument('--proxy-url', type=str,
                        help='Proxy URL for Claude API (e.g., http://localhost:4143/v1)')
    parser.add_argument('--passes', type=int, default=1,
                        help='Number of test passes to run for stability testing')

    args = parser.parse_args()

    # Set proxy environment variable if specified
    if args.proxy_url:
        os.environ['CLAUDE_PROXY_URL'] = args.proxy_url
        logger.info(f"Using Claude API proxy: {args.proxy_url}")

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

    server_process = None
    if not args.no_server:
        try:
            server_process = start_api_server(
                port=args.port,
                headless=not args.no_headless
            )
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            sys.exit(1)

    try:
        # Build all pass tasks for parallel execution
        all_pass_tasks = []
        for pass_num in range(1, args.passes + 1):
            for task in tasks:
                all_pass_tasks.append((task, pass_num))

        total_tasks = len(all_pass_tasks)
        logger.info(f"Running {total_tasks} total task instances ({len(tasks)} tasks × {args.passes} passes)")

        # Run all tests in parallel
        results = asyncio.run(run_all_tests(
            tasks=all_pass_tasks,
            concurrent=args.concurrent,
            port=args.port,
            model=args.model,
            timeout=args.timeout,
            output_path=output_path,
            working_dir=args.working_dir
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

            # Save per-pass results
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

        # Print stability summary if multiple passes
        if args.passes > 1:
            print(f"\n{'='*50}")
            print("Stability Summary (All Passes)")
            print("=" * 50)

            # Aggregate by task
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

                # Determine stability
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

            # Overall stats
            avg_scores = [p['summary']['avg_score'] for p in all_pass_results]
            success_rates = [p['summary']['success_rate'] for p in all_pass_results]
            print(f"\nAvg Score: {min(avg_scores):.2f} - {max(avg_scores):.2f}")
            print(f"Success Rate: {min(success_rates)*100:.0f}% - {max(success_rates)*100:.0f}%")

    finally:
        if server_process:
            stop_api_server(server_process)


if __name__ == '__main__':
    main()
