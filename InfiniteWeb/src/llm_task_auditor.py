#!/usr/bin/env python3
"""
LLM-based task auditor: uses GPT-5.1 to detect instruction-evaluator mismatches.

Unlike the regex-based scanner, this understands:
- Semantic equivalence (8:00 PM ≈ 20:00)
- What's discoverable by browsing vs what must be told
- Whether user-created content is sufficiently implied by instruction
- Ground truth correctness against website data

Usage:
    # Audit a single website
    python src/llm_task_auditor.py --website-dir /path/to/website

    # Audit from blob storage (batch)
    python src/llm_task_auditor.py \
        --blob-prefix osworld_code/website_archives/ \
        --limit 50 --report audit_report.json

    # Audit with ground truth validation (Issue 2)
    python src/llm_task_auditor.py --website-dir /path/to/website --check-ground-truth
"""

import argparse
import asyncio
import json
import os
import re
import sys
import tarfile
import subprocess
import shutil
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from openai import AsyncOpenAI

# ─── Azure OpenAI config ────────────────────────────────────────────────────
DEFAULT_MODEL = "gpt-5.1"
DEFAULT_API_BASE = "https://msra-im-openai-se.openai.azure.com/openai/v1"
DEFAULT_API_KEY = os.environ.get("OPENAI_API_KEY") or "6ec3c022ce5942d48da8fa4a22ed2fe6"

AUDIT_CONCURRENCY = 10  # max parallel LLM calls


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class ValueAudit:
    value: str
    evaluator_context: str
    verdict: str          # "IMPOSSIBLE", "PROBLEMATIC", "OK"
    category: str         # "form_input", "user_created_content", "discovery_value", "config", "structural"
    reason: str

@dataclass
class TaskAudit:
    task_id: str
    instruction: str
    issues: List[ValueAudit] = field(default_factory=list)
    ground_truth_issues: List[str] = field(default_factory=list)
    overall_verdict: str = "OK"  # "IMPOSSIBLE", "PROBLEMATIC", "OK"

@dataclass
class WebsiteAudit:
    website_name: str
    total_tasks: int = 0
    impossible_tasks: int = 0
    problematic_tasks: int = 0
    task_audits: List[TaskAudit] = field(default_factory=list)
    error: str = ""


# ─── LLM client ─────────────────────────────────────────────────────────────

def get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=DEFAULT_API_KEY,
        base_url=DEFAULT_API_BASE,
        default_headers={"api-key": DEFAULT_API_KEY},
    )


AUDIT_PROMPT = """You are auditing a generated RL agent task for correctness.

An RL agent will see ONLY the `instruction` text below. It will interact with a website through a browser.
The `evaluator` is JavaScript code that runs after the agent finishes. It reads browser localStorage and returns a score 0.0-1.0.

Your job: identify values in the evaluator that the agent CANNOT know from the instruction alone.

## INSTRUCTION (what the agent sees)
{instruction}

## EVALUATOR CODE (JavaScript)
```javascript
{evaluator_code}
```

## TASK GROUND TRUTH (used to generate evaluator)
```json
{ground_truth}
```

{website_data_section}

## ANALYSIS RULES

For each hardcoded string/number comparison in the evaluator (=== 'value', === number), classify:

1. **IMPOSSIBLE** — The agent CANNOT know this value. It's not in the instruction, not discoverable from the website UI, and not computable from visible data. Examples:
   - A person name like 'Jordan Lee' that the instruction never mentions
   - An email like 'alex@example.com' that the instruction never provides
   - A password, phone number, or ZIP code not in the instruction
   - An exact text string (bio, comment, description) the agent must type but instruction doesn't specify

2. **PROBLEMATIC** — The value is technically derivable but fragile. Examples:
   - Time format mismatch: instruction says "8:00 PM" but evaluator checks '20:00'
   - A user-created title that the instruction implies but doesn't specify exactly (e.g., instruction says "create a checklist" but evaluator checks title === 'My Safety Checklist')
   - A ground_truth value that doesn't match the website data (wrong target)
   - Criteria that match multiple items but evaluator hardcodes one specific target

3. **OK** — The value is fine. Examples:
   - Structural values (content types, list types, status enums)
   - Values that appear verbatim in the instruction
   - Values discoverable by browsing the website (product names, category labels visible in UI)
   - Dynamic computations (evaluator computes "cheapest" from data, not hardcoded)
   - Date/time range boundaries used for filtering

Only report IMPOSSIBLE and PROBLEMATIC values. Skip OK values.

## OUTPUT FORMAT (JSON)
{{
  "issues": [
    {{
      "value": "the hardcoded value",
      "evaluator_context": "brief JS snippet showing the comparison",
      "verdict": "IMPOSSIBLE" or "PROBLEMATIC",
      "category": "form_input" | "user_created_content" | "config" | "discovery_value" | "ground_truth_error",
      "reason": "one sentence explaining why the agent can't know this"
    }}
  ],
  "overall_verdict": "IMPOSSIBLE" | "PROBLEMATIC" | "OK",
  "summary": "one sentence overall assessment"
}}

If there are no issues, return {{"issues": [], "overall_verdict": "OK", "summary": "Task is well-formed."}}.
"""

GT_CHECK_PROMPT = """You are validating that ground_truth values are correct against website data.

## TASK INSTRUCTION
{instruction}

## GROUND TRUTH
```json
{ground_truth}
```

## WEBSITE DATA (the actual data in the website)
```json
{website_data_snippet}
```

Check:
1. Do target_ids in ground_truth actually exist in website_data?
2. Do target_names match the actual names/titles in website_data for those IDs?
3. Are expected_values (prices, ratings, dates) consistent with actual data?
4. If ground_truth says "highest rated" or "cheapest", is the selected target actually the correct one?
5. Are there any invented values (IDs, names, fields) not traceable to website_data?

Return JSON:
{{
  "ground_truth_valid": true/false,
  "issues": [
    "description of each inconsistency found"
  ]
}}
"""


async def audit_single_task(
    client: AsyncOpenAI,
    task: Dict[str, Any],
    evaluator: Dict[str, Any],
    website_data: Optional[Dict[str, Any]] = None,
    check_ground_truth: bool = False,
    semaphore: asyncio.Semaphore = None,
) -> TaskAudit:
    """Audit a single task using GPT-5.1."""
    task_id = task.get("id", "unknown")
    instruction = task.get("instruction", "")
    ground_truth = task.get("ground_truth", {})
    evaluator_code = evaluator.get("evaluation_logic", "")

    result = TaskAudit(task_id=task_id, instruction=instruction)

    # Build website data section (truncated for token efficiency)
    website_data_section = ""
    if website_data:
        # Only include entity types referenced in evaluator or ground_truth
        relevant_data = {}
        eval_text = evaluator_code + json.dumps(ground_truth)
        for key, value in website_data.items():
            if key.startswith("_"):
                continue
            if key.lower() in eval_text.lower() or any(
                key_part in eval_text.lower()
                for key_part in key.lower().split("_")
                if len(key_part) > 3
            ):
                if isinstance(value, list) and len(value) > 5:
                    relevant_data[key] = value[:5]
                    relevant_data[f"_{key}_total"] = len(value)
                else:
                    relevant_data[key] = value

        if relevant_data:
            website_data_section = f"""
## WEBSITE DATA (relevant entities from the site's database)
```json
{json.dumps(relevant_data, indent=2, ensure_ascii=False)[:6000]}
```
"""

    # ── Main audit ──
    prompt = AUDIT_PROMPT.format(
        instruction=instruction,
        evaluator_code=evaluator_code,
        ground_truth=json.dumps(ground_truth, indent=2, ensure_ascii=False),
        website_data_section=website_data_section,
    )

    async def call_llm(prompt_text: str) -> dict:
        if semaphore:
            async with semaphore:
                resp = await client.chat.completions.create(
                    model=DEFAULT_MODEL,
                    messages=[{"role": "user", "content": prompt_text}],
                    response_format={"type": "json_object"},
                )
        else:
            resp = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[{"role": "user", "content": prompt_text}],
                response_format={"type": "json_object"},
            )
        text = resp.choices[0].message.content
        return json.loads(text)

    try:
        audit_result = await call_llm(prompt)

        for issue in audit_result.get("issues", []):
            result.issues.append(ValueAudit(
                value=issue.get("value", ""),
                evaluator_context=issue.get("evaluator_context", ""),
                verdict=issue.get("verdict", "PROBLEMATIC"),
                category=issue.get("category", "unknown"),
                reason=issue.get("reason", ""),
            ))

        result.overall_verdict = audit_result.get("overall_verdict", "OK")

    except Exception as e:
        result.overall_verdict = "ERROR"
        result.issues.append(ValueAudit(
            value="", evaluator_context="", verdict="ERROR",
            category="error", reason=str(e),
        ))

    # ── Ground truth validation (optional) ──
    if check_ground_truth and website_data and ground_truth:
        try:
            # Build a snippet of relevant website data
            relevant_entities = {}
            gt_text = json.dumps(ground_truth)
            for key, value in website_data.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, list):
                    # Check if any target_ids reference this entity
                    discovery = ground_truth.get("discovery_targets", {})
                    target_ids = discovery.get("target_ids", ground_truth.get("target_ids", []))
                    matching = [
                        item for item in value
                        if isinstance(item, dict) and item.get("id") in target_ids
                    ]
                    if matching:
                        relevant_entities[key] = value  # include full list for comparison
                    elif key.lower() in gt_text.lower():
                        relevant_entities[key] = value[:3]  # sample

            if relevant_entities:
                gt_prompt = GT_CHECK_PROMPT.format(
                    instruction=instruction,
                    ground_truth=json.dumps(ground_truth, indent=2, ensure_ascii=False),
                    website_data_snippet=json.dumps(relevant_entities, indent=2, ensure_ascii=False)[:8000],
                )
                gt_result = await call_llm(gt_prompt)
                if not gt_result.get("ground_truth_valid", True):
                    result.ground_truth_issues = gt_result.get("issues", [])
                    if result.overall_verdict == "OK":
                        result.overall_verdict = "PROBLEMATIC"

        except Exception as e:
            result.ground_truth_issues.append(f"GT validation error: {e}")

    return result


async def audit_website(
    website_dir: str,
    check_ground_truth: bool = False,
    client: AsyncOpenAI = None,
    semaphore: asyncio.Semaphore = None,
) -> WebsiteAudit:
    """Audit all tasks in a website directory."""
    website_name = os.path.basename(os.path.normpath(website_dir))
    result = WebsiteAudit(website_name=website_name)

    # Load files
    tasks_path = os.path.join(website_dir, "rewritten_tasks.json")
    evaluators_path = os.path.join(website_dir, "evaluators.json")
    data_path = os.path.join(website_dir, "website_data.json")

    for path, name in [(tasks_path, "rewritten_tasks.json"), (evaluators_path, "evaluators.json")]:
        if not os.path.exists(path):
            result.error = f"Missing {name}"
            return result

    try:
        with open(tasks_path, 'r', encoding='utf-8') as f:
            tasks_data = json.load(f)
        with open(evaluators_path, 'r', encoding='utf-8') as f:
            evaluators_data = json.load(f)
        website_data = None
        if os.path.exists(data_path):
            with open(data_path, 'r', encoding='utf-8') as f:
                website_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        result.error = f"JSON parse error: {e}"
        return result

    tasks = tasks_data.get("tasks", [])
    evaluators = evaluators_data.get("evaluators", [])
    evaluator_map = {ev.get("task_id"): ev for ev in evaluators}

    result.total_tasks = len(tasks)

    if client is None:
        client = get_client()

    # Audit all tasks concurrently
    coros = []
    for task in tasks:
        ev = evaluator_map.get(task.get("id"))
        if not ev:
            continue
        coros.append(audit_single_task(
            client, task, ev, website_data, check_ground_truth, semaphore
        ))

    task_results = await asyncio.gather(*coros)

    for ta in task_results:
        result.task_audits.append(ta)
        if ta.overall_verdict == "IMPOSSIBLE":
            result.impossible_tasks += 1
        elif ta.overall_verdict == "PROBLEMATIC":
            result.problematic_tasks += 1

    return result


def generate_report(results: List[WebsiteAudit]) -> Dict[str, Any]:
    """Generate summary report."""
    total_websites = len(results)
    total_tasks = sum(r.total_tasks for r in results)
    impossible_tasks = sum(r.impossible_tasks for r in results)
    problematic_tasks = sum(r.problematic_tasks for r in results)
    error_websites = sum(1 for r in results if r.error)
    affected_websites = sum(
        1 for r in results if r.impossible_tasks > 0 or r.problematic_tasks > 0
    )

    # Collect category stats
    category_counts = {}
    all_issues = []
    for r in results:
        for ta in r.task_audits:
            for issue in ta.issues:
                cat = issue.category
                category_counts[cat] = category_counts.get(cat, 0) + 1
                all_issues.append({
                    "website": r.website_name,
                    "task_id": ta.task_id,
                    "instruction": ta.instruction[:120],
                    "value": issue.value,
                    "verdict": issue.verdict,
                    "category": issue.category,
                    "reason": issue.reason,
                })

    # Ground truth issues
    gt_issues = []
    for r in results:
        for ta in r.task_audits:
            if ta.ground_truth_issues:
                gt_issues.append({
                    "website": r.website_name,
                    "task_id": ta.task_id,
                    "issues": ta.ground_truth_issues,
                })

    return {
        "summary": {
            "total_websites": total_websites,
            "affected_websites": affected_websites,
            "error_websites": error_websites,
            "total_tasks": total_tasks,
            "impossible_tasks": impossible_tasks,
            "problematic_tasks": problematic_tasks,
            "impossible_rate": f"{impossible_tasks / total_tasks * 100:.1f}%" if total_tasks else "N/A",
        },
        "by_category": dict(sorted(category_counts.items(), key=lambda x: -x[1])),
        "issues": all_issues,
        "ground_truth_issues": gt_issues,
    }


# ─── Blob helpers ────────────────────────────────────────────────────────────

def list_blob_archives(account_name, container_name, prefix):
    result = subprocess.run(
        ["az", "storage", "blob", "list",
         "--account-name", account_name, "--container-name", container_name,
         "--prefix", prefix, "--auth-mode", "login",
         "--query", "[].name", "--output", "json"],
        capture_output=True, text=True, check=True,
    )
    return [n for n in json.loads(result.stdout) if n.endswith(".tar.gz")]


def download_and_extract(blob_name, account_name, container_name, output_dir):
    local_tar = os.path.join(output_dir, os.path.basename(blob_name))
    subprocess.run(
        ["az", "storage", "blob", "download",
         "--account-name", account_name, "--container-name", container_name,
         "--name", blob_name, "--file", local_tar,
         "--auth-mode", "login", "--no-progress"],
        capture_output=True, text=True, check=True,
    )
    extract_dir = os.path.join(
        output_dir, "extracted",
        os.path.basename(blob_name).replace(".tar.gz", "")
    )
    os.makedirs(extract_dir, exist_ok=True)
    with tarfile.open(local_tar, "r:gz") as tar:
        tar.extractall(extract_dir, filter='data')
    os.remove(local_tar)
    return extract_dir


def find_website_dirs(base_dir):
    dirs = []
    for root, _, files in os.walk(base_dir):
        if "rewritten_tasks.json" in files and "evaluators.json" in files:
            dirs.append(root)
    return sorted(dirs)


# ─── Main ────────────────────────────────────────────────────────────────────

async def main_async(args):
    client = get_client()
    semaphore = asyncio.Semaphore(AUDIT_CONCURRENCY)
    results: List[WebsiteAudit] = []

    if args.website_dir:
        # Single or local batch mode
        if args.single:
            print(f"Auditing: {args.website_dir}")
            r = await audit_website(args.website_dir, args.check_ground_truth, client, semaphore)
            results.append(r)
        else:
            dirs = find_website_dirs(args.website_dir)
            if args.limit:
                dirs = dirs[:args.limit]
            print(f"Found {len(dirs)} websites to audit")
            for i, d in enumerate(dirs, 1):
                r = await audit_website(d, args.check_ground_truth, client, semaphore)
                results.append(r)
                status = f"IMP={r.impossible_tasks} PROB={r.problematic_tasks}" if (r.impossible_tasks or r.problematic_tasks) else "OK"
                print(f"[{i}/{len(dirs)}] {r.website_name}: {status}")
    else:
        # Blob mode
        os.makedirs(args.output_dir, exist_ok=True)
        archives = list_blob_archives(args.account_name, args.container_name, args.blob_prefix)
        if args.limit:
            archives = archives[:args.limit]
        print(f"Found {len(archives)} archives")

        for i, blob in enumerate(archives, 1):
            try:
                extract_dir = download_and_extract(
                    blob, args.account_name, args.container_name, args.output_dir
                )
                dirs = find_website_dirs(extract_dir)
                if dirs:
                    r = await audit_website(dirs[0], args.check_ground_truth, client, semaphore)
                else:
                    r = WebsiteAudit(website_name=os.path.basename(blob), error="No tasks found")
                results.append(r)
                shutil.rmtree(extract_dir, ignore_errors=True)
                status = f"IMP={r.impossible_tasks} PROB={r.problematic_tasks}" if (r.impossible_tasks or r.problematic_tasks) else ("ERR" if r.error else "OK")
                if r.impossible_tasks or r.problematic_tasks or r.error:
                    print(f"[{i}/{len(archives)}] {r.website_name}: {status}")
            except Exception as e:
                results.append(WebsiteAudit(website_name=os.path.basename(blob), error=str(e)))

    # Report
    report = generate_report(results)
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE")
    print(f"{'='*60}")
    print(f"Websites:    {s['total_websites']} ({s['affected_websites']} with issues)")
    print(f"Tasks:       {s['total_tasks']}")
    print(f"IMPOSSIBLE:  {s['impossible_tasks']} ({s['impossible_rate']})")
    print(f"PROBLEMATIC: {s['problematic_tasks']}")
    print(f"\nBy category:")
    for cat, count in report["by_category"].items():
        print(f"  {count:4d}  {cat}")

    if report["ground_truth_issues"]:
        print(f"\nGround truth issues: {len(report['ground_truth_issues'])} tasks")

    with open(args.report, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport: {args.report}")


def main():
    parser = argparse.ArgumentParser(description="LLM-based task auditor")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--website-dir")
    source.add_argument("--blob-prefix")

    parser.add_argument("--single", action="store_true")
    parser.add_argument("--check-ground-truth", action="store_true",
                        help="Also validate ground_truth against website_data (Issue 2)")
    parser.add_argument("--report", default="llm_audit_report.json")
    parser.add_argument("--output-dir", default="/tmp/llm_audit")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--account-name", default="msraimwsscus0899462143")
    parser.add_argument("--container-name",
                        default="azureml-blobstore-0ac19c22-79e2-43e1-82c7-f2f8cd851bab")

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
