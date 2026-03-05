#!/usr/bin/env python3
"""
Navigation Contract Tester
Tests navigation link consistency across generated websites using two strategies:
  C-Lite: Static data cross-reference (no LLM)
  C-Full: LLM-based analysis of HTML + SDK + data
"""

import json
import os
import re
import sys
import asyncio
import argparse
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from pathlib import Path

# Add src to path for llm_caller import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_caller import configure_load_balancing, call_openai_api_json_async


# ============================================================================
# Utility Functions
# ============================================================================

def extract_nav_params(architecture: dict) -> List[dict]:
    """Extract URL parameters from header_links and footer_links.

    Returns list of dicts: {text, url, page, params: {name: value}, source: header|footer}
    """
    results = []
    for source in ("header_links", "footer_links"):
        for link in architecture.get(source, []):
            url = link.get("url", "")
            if "?" not in url:
                continue
            page, query = url.split("?", 1)
            parsed = parse_qs(query, keep_blank_values=True)
            # parse_qs returns lists; flatten single values
            params = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            results.append({
                "text": link.get("text", ""),
                "url": url,
                "page": page,
                "params": params,
                "source": source,
            })
    return results


def find_page_metadata(architecture: dict, page_filename: str) -> Optional[dict]:
    """Find page metadata (incoming_params, assigned_interfaces) from architecture."""
    for page in architecture.get("pages", []):
        if page.get("filename") == page_filename:
            return page
    return None


def find_interface_signature(interfaces: dict, func_name: str) -> Optional[dict]:
    """Find interface definition by function name."""
    for iface in interfaces.get("interfaces", []):
        if iface.get("name") == func_name:
            return iface
    # Also check helperFunctions
    for helper in interfaces.get("helperFunctions", []):
        if helper.get("name") == func_name:
            return helper
    return None


def extract_function_from_js(js_code: str, func_name: str) -> Optional[str]:
    """Extract a function body from business_logic.js by name."""
    # Match patterns like: functionName(params) { or functionName = function(params) {
    patterns = [
        rf'(?:async\s+)?{re.escape(func_name)}\s*\([^)]*\)\s*\{{',
        rf'{re.escape(func_name)}\s*=\s*(?:async\s+)?function\s*\([^)]*\)\s*\{{',
    ]

    for pattern in patterns:
        match = re.search(pattern, js_code)
        if not match:
            continue
        start = match.start()
        # Track brace depth to find matching close
        depth = 0
        i = match.end() - 1  # start at the opening brace
        while i < len(js_code):
            if js_code[i] == '{':
                depth += 1
            elif js_code[i] == '}':
                depth -= 1
                if depth == 0:
                    return js_code[start:i+1]
            i += 1
    return None


def collect_data_field_values(data: dict, field_name: str) -> set:
    """Collect all values for a given field name across all entities in website_data.json."""
    values = set()
    for entity_name, entity_list in data.items():
        if not isinstance(entity_list, list):
            continue
        for item in entity_list:
            if not isinstance(item, dict):
                continue
            if field_name in item:
                val = item[field_name]
                if isinstance(val, str):
                    values.add(val)
                elif isinstance(val, (int, float, bool)):
                    values.add(str(val))
    return values


def collect_entity_ids(data: dict, entity_hint: str) -> set:
    """Collect all 'id' values from entities whose name matches the hint.

    entity_hint is derived from param name, e.g., 'categoryId' -> 'category'
    """
    ids = set()
    hint_lower = entity_hint.lower()
    for entity_name, entity_list in data.items():
        if not isinstance(entity_list, list):
            continue
        name_lower = entity_name.lower().replace("_", "").replace("-", "")
        # Match: categories, category, Category, etc.
        if hint_lower in name_lower or name_lower in hint_lower:
            for item in entity_list:
                if isinstance(item, dict):
                    for id_field in ("id", "Id", "ID", f"{entity_hint}"):
                        if id_field in item:
                            val = item[id_field]
                            if isinstance(val, str):
                                ids.add(val)
                            break
    return ids


def truncate_data_sample(data: dict, max_items: int = 5) -> dict:
    """Truncate each entity list to max_items for LLM prompt."""
    truncated = {}
    for k, v in data.items():
        if isinstance(v, list):
            truncated[k] = v[:max_items]
        else:
            truncated[k] = v
    return truncated


def extract_html_js_relevant(html_path: str, max_chars: int = 10000) -> str:
    """Extract navigation-relevant inline JavaScript from an HTML page.

    Extracts <script> blocks (without src attribute) and filters to those
    containing URL param reading or SDK calls.
    """
    try:
        html = open(html_path, encoding="utf-8").read()
    except Exception:
        return ""

    # Extract inline <script> blocks (no src attribute)
    scripts = []
    for m in re.finditer(r'<script([^>]*)>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        attrs, body = m.group(1), m.group(2).strip()
        if 'src=' in attrs or not body:
            continue
        scripts.append(body)

    if not scripts:
        return ""

    full_js = "\n\n// --- next script block ---\n\n".join(scripts)

    # If short enough, return everything
    if len(full_js) <= max_chars:
        return full_js

    # Otherwise, extract only relevant portions:
    # Lines/blocks containing URLSearchParams, params.get, WebsiteSDK, location.search
    keywords = ['URLSearchParams', 'params.get', 'urlParams.get', 'WebsiteSDK',
                'location.search', 'searchParams', '.get(\'', '.get("']
    relevant_lines = []
    for script in scripts:
        lines = script.split('\n')
        for i, line in enumerate(lines):
            if any(kw in line for kw in keywords):
                # Include surrounding context (5 lines before, 10 after)
                start = max(0, i - 5)
                end = min(len(lines), i + 11)
                chunk = '\n'.join(lines[start:end])
                if chunk not in '\n'.join(relevant_lines):
                    relevant_lines.append(f"// ... (line ~{start+1})")
                    relevant_lines.append(chunk)
                    relevant_lines.append("")

    result = '\n'.join(relevant_lines)

    # If still too long, truncate
    if len(result) > max_chars:
        result = result[:max_chars] + "\n// ... (truncated)"

    return result if result.strip() else full_js[:max_chars]


# ============================================================================
# C-Lite: Static Navigation Contract Test
# ============================================================================

def run_c_lite(website_dir: str) -> dict:
    """Run C-Lite navigation contract test on a single website.

    Checks:
    1. Nav param values exist in data (field value match)
    2. Nav param values exist as entity IDs
    3. Nav link target page exists as HTML file
    4. Param name matches page's incoming_params

    Returns dict with test results.
    """
    website_name = os.path.basename(website_dir)
    result = {
        "website": website_name,
        "nav_links_with_params": 0,
        "issues": [],
        "checks_passed": 0,
        "checks_total": 0,
    }

    # Load files
    arch_path = os.path.join(website_dir, "data", "architecture.json")
    data_path = os.path.join(website_dir, "website_data.json")
    interfaces_path = os.path.join(website_dir, "data", "interfaces.json")

    if not os.path.exists(arch_path):
        result["error"] = "architecture.json not found"
        return result

    try:
        architecture = json.load(open(arch_path, encoding="utf-8"))
    except Exception as e:
        result["error"] = f"Failed to load architecture.json: {e}"
        return result

    # Extract nav links with params
    nav_links = extract_nav_params(architecture)
    result["nav_links_with_params"] = len(nav_links)

    if not nav_links:
        return result  # No params to test

    # Load data
    website_data = {}
    if os.path.exists(data_path):
        try:
            website_data = json.load(open(data_path, encoding="utf-8"))
        except:
            pass

    interfaces = {}
    if os.path.exists(interfaces_path):
        try:
            interfaces = json.load(open(interfaces_path, encoding="utf-8"))
        except:
            pass

    # Run checks for each nav link
    for link in nav_links:
        page = link["page"]
        params = link["params"]

        # Check 1: Target page exists
        result["checks_total"] += 1
        page_path = os.path.join(website_dir, page)
        if not os.path.exists(page_path):
            result["issues"].append({
                "type": "missing_page",
                "severity": "critical",
                "nav_link": link["text"],
                "url": link["url"],
                "description": f"Target page '{page}' does not exist",
            })
        else:
            result["checks_passed"] += 1

        # Check 2: Param name in page's incoming_params
        page_meta = find_page_metadata(architecture, page)
        if page_meta:
            incoming = {p.get("param_name", p.get("name", ""))
                       for p in page_meta.get("incoming_params", [])}
            for param_name in params:
                result["checks_total"] += 1
                if param_name not in incoming:
                    result["issues"].append({
                        "type": "param_not_declared",
                        "severity": "major",
                        "nav_link": link["text"],
                        "url": link["url"],
                        "param": param_name,
                        "description": f"Parameter '{param_name}' not in page's incoming_params",
                        "available_params": sorted(incoming),
                    })
                else:
                    result["checks_passed"] += 1

        # Check 3: Param value exists in data
        if website_data:
            for param_name, param_value in params.items():
                if isinstance(param_value, list):
                    continue  # Skip multi-value params

                result["checks_total"] += 1

                # Strategy A: Check if param value exists as a field value
                field_values = collect_data_field_values(website_data, param_name)

                # Strategy B: Check if param value exists as an entity ID
                # Derive entity hint: categoryId -> category, serviceType -> service
                entity_hint = re.sub(r'Id$|_id$', '', param_name)
                entity_ids = collect_entity_ids(website_data, entity_hint)

                # Combine both checks
                all_known_values = field_values | entity_ids

                if param_value in all_known_values:
                    result["checks_passed"] += 1
                else:
                    # Check for partial match (parent of hierarchical value)
                    is_parent = any(v.startswith(param_value + "-") or
                                   v.startswith(param_value + "_")
                                   for v in all_known_values)

                    result["issues"].append({
                        "type": "value_not_in_data",
                        "severity": "critical" if not is_parent else "major",
                        "nav_link": link["text"],
                        "url": link["url"],
                        "param": param_name,
                        "param_value": param_value,
                        "is_parent_of_existing": is_parent,
                        "description": (
                            f"Nav param {param_name}='{param_value}' not found as exact match in data. "
                            + (f"It IS a parent prefix of existing values (hierarchical mismatch)."
                               if is_parent
                               else f"No matching values found at all.")
                        ),
                        "sample_data_values": sorted(list(all_known_values))[:15],
                    })

        # Check 4: Assigned interface has matching parameter
        if page_meta and interfaces:
            assigned = page_meta.get("assigned_interfaces", [])
            for param_name in params:
                result["checks_total"] += 1
                found_match = False
                for func_name in assigned:
                    iface = find_interface_signature(interfaces, func_name)
                    if iface:
                        iface_params = [p.get("name", "") for p in iface.get("parameters", [])]
                        if param_name in iface_params:
                            found_match = True
                            break
                if found_match:
                    result["checks_passed"] += 1
                else:
                    result["issues"].append({
                        "type": "no_interface_match",
                        "severity": "minor",
                        "nav_link": link["text"],
                        "url": link["url"],
                        "param": param_name,
                        "description": f"No assigned interface function accepts parameter '{param_name}'",
                        "assigned_interfaces": assigned,
                    })

    return result


# ============================================================================
# C-Full v2: LLM-Based Navigation Contract Test with HTML Parsing
# ============================================================================

C_FULL_V2_PROMPT = """You are verifying whether navigation links on a generated website actually work.

When a user clicks a nav link, the browser opens the target page with URL parameters.
The page's JavaScript reads those params, possibly transforms them, and calls SDK functions to load data.

## 1. Target Page JavaScript (how the page reads URL params and calls SDK)
```javascript
{html_js_code}
```

## 2. Navigation Links to Verify
{nav_links_json}

## 3. SDK Function Implementations (from business_logic.js)
```javascript
{sdk_functions_code}
```

## 4. Actual Data (ALL items for small entities, sample for large ones)
```json
{data_sample_json}
```

## 5. Unique field values summary (ALL distinct values per field across full dataset)
{field_values_summary}

## Instructions

For EACH navigation link, trace the **actual runtime path** through the code:

1. The page JS reads URL params via `params.get(...)` or `urlParams.get(...)`.
   - Note any renaming (e.g., `categoryId` URL param stored as `sectionSlug` variable)
   - Note any value mapping (e.g., `categoryMap[paramValue]` converting plurals to singulars)
   - **Note any wrapping into filter/options objects** (e.g., the page builds `filters.content_types = ['movie']` from a `contentType=movies` URL param, then passes the `filters` object to the SDK — this is NOT a bug, it's a valid indirect pass-through)

2. The page calls `WebsiteSDK.someFunction(...)`.
   - Identify WHICH function is called and which argument carries the (possibly transformed) param value.
   - The param may reach the SDK **indirectly** through a filter/options object — trace through object properties.

3. The SDK function filters/queries the data.
   - What field does it compare against? What comparison does it use?

4. Check if the data actually contains matching values.
   - Does the final (transformed) param value exist in the relevant data field?
   - **If the data sample is truncated and you cannot confirm the value exists or not, check the "Unique field values" summary below the data sample — it lists ALL distinct values for key fields.**

Only report a bug if you have **concrete proof** that the end-to-end path produces wrong results.
Do NOT report a bug if:
- The page JS correctly transforms the URL param before passing it to the SDK
- The param is wrapped in a filter object that the SDK correctly unpacks
- You cannot verify the data because the sample is incomplete

Return ONLY valid JSON:
{{
  "bugs": [
    {{
      "severity": "critical|major|minor",
      "type": "value_mismatch|hierarchical_mismatch|field_mismatch|type_coercion|null_handling|empty_result|other",
      "nav_link_text": "link text",
      "nav_link_url": "full URL",
      "affected_function": "SDK function name",
      "description": "One-sentence description of what goes wrong",
      "evidence": "Show the specific code path: URL value -> JS transform -> SDK call -> data lookup -> result"
    }}
  ],
  "summary": "One paragraph summary"
}}

If all links work correctly (including after JS transforms), return {{"bugs": [], "summary": "All navigation links work correctly."}}.
Be strict: only report bugs with concrete end-to-end evidence."""


async def run_c_full_v2_for_page(
    website_dir: str,
    page_filename: str,
    nav_links: List[dict],
    architecture: dict,
    interfaces: dict,
    website_data: dict,
    business_logic_js: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Run C-Full v2 analysis for a single target page using HTML JS parsing."""
    async with semaphore:
        page_meta = find_page_metadata(architecture, page_filename)
        assigned = page_meta.get("assigned_interfaces", []) if page_meta else []

        # Change 1: Extract HTML page's inline JavaScript
        html_path = os.path.join(website_dir, page_filename)
        html_js_code = extract_html_js_relevant(html_path) if os.path.exists(html_path) else ""

        # Change 2: Extract ALL assigned interface functions (no param-name filtering)
        sdk_code_parts = []
        for func_name in assigned:
            code = extract_function_from_js(business_logic_js, func_name)
            if code:
                sdk_code_parts.append(code)

        # Also extract helper functions referenced by the main functions
        combined_sdk = "\n\n".join(sdk_code_parts)
        helper_names = set(re.findall(r'this\.(_{1,2}[a-zA-Z]\w*)\s*\(', combined_sdk))
        for helper_name in helper_names:
            helper_code = extract_function_from_js(business_logic_js, helper_name)
            if helper_code and helper_code not in combined_sdk:
                sdk_code_parts.append(helper_code)

        combined_sdk = "\n\n".join(sdk_code_parts) if sdk_code_parts else "(No SDK functions found in business_logic.js)"

        # Change 3: Smart data sampling
        # Small entities (categories, sections, tags, etc.) get ALL items
        # Large entities (products, articles, etc.) get first 5
        relevant_data = {}
        for entity_name, entity_list in website_data.items():
            if isinstance(entity_list, list) and entity_list:
                if len(entity_list) <= 30:
                    relevant_data[entity_name] = entity_list  # Include ALL
                else:
                    relevant_data[entity_name] = entity_list[:5]

        # Build field values summary: collect unique values for fields that
        # might be used as filter/match targets (IDs, slugs, types, categories, tags)
        field_summary_lines = []
        interesting_suffixes = ('id', 'Id', '_id', 'slug', 'type', 'category', 'categoryId',
                                'section', 'tag', 'tags', 'status', 'genre', 'key')
        for entity_name, entity_list in website_data.items():
            if not isinstance(entity_list, list) or not entity_list:
                continue
            if not isinstance(entity_list[0], dict):
                continue
            for field in entity_list[0]:
                if not any(field.endswith(s) or field == s for s in interesting_suffixes):
                    if field not in ('id', 'name', 'slug'):
                        continue
                vals = set()
                for item in entity_list:
                    v = item.get(field)
                    if isinstance(v, str):
                        vals.add(v)
                    elif isinstance(v, list):
                        for vi in v:
                            if isinstance(vi, str):
                                vals.add(vi)
                if vals and len(vals) <= 50:
                    field_summary_lines.append(f"{entity_name}.{field}: {sorted(vals)}")
        field_values_summary = "\n".join(field_summary_lines[:40]) if field_summary_lines else "(no summary available)"

        # Build prompt
        nav_links_json = json.dumps([{
            "text": l["text"], "url": l["url"], "params": l["params"]
        } for l in nav_links], indent=2, ensure_ascii=False)

        prompt = C_FULL_V2_PROMPT.format(
            html_js_code=html_js_code[:10000] or "(HTML page not found or no inline JS)",
            nav_links_json=nav_links_json,
            sdk_functions_code=combined_sdk[:15000],
            data_sample_json=json.dumps(relevant_data, indent=2, ensure_ascii=False)[:10000],
            field_values_summary=field_values_summary[:4000],
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            reply, usage = await call_openai_api_json_async(
                messages, max_tokens=4096, max_retries=3,
                reasoning_effort="medium", stage="nav_contract_test_v2"
            )
            if reply:
                result = json.loads(reply)
                result["page"] = page_filename
                result["nav_links_tested"] = len(nav_links)
                return result
        except Exception as e:
            return {
                "page": page_filename,
                "error": str(e),
                "bugs": [],
                "summary": f"LLM analysis failed: {e}",
            }

    return {"page": page_filename, "bugs": [], "summary": "Analysis skipped"}


async def run_c_full_v2(website_dir: str, semaphore: asyncio.Semaphore) -> dict:
    """Run C-Full v2 navigation contract test with HTML parsing."""
    website_name = os.path.basename(website_dir)
    result = {
        "website": website_name,
        "pages_tested": 0,
        "total_bugs": 0,
        "page_results": [],
        "all_bugs": [],
    }

    arch_path = os.path.join(website_dir, "data", "architecture.json")
    data_path = os.path.join(website_dir, "website_data.json")
    interfaces_path = os.path.join(website_dir, "data", "interfaces.json")
    js_path = os.path.join(website_dir, "business_logic.js")

    if not os.path.exists(arch_path):
        result["error"] = "architecture.json not found"
        return result

    try:
        architecture = json.load(open(arch_path, encoding="utf-8"))
        website_data = json.load(open(data_path, encoding="utf-8")) if os.path.exists(data_path) else {}
        interfaces = json.load(open(interfaces_path, encoding="utf-8")) if os.path.exists(interfaces_path) else {}
        business_logic_js = open(js_path, encoding="utf-8").read() if os.path.exists(js_path) else ""
    except Exception as e:
        result["error"] = f"Failed to load files: {e}"
        return result

    nav_links = extract_nav_params(architecture)
    if not nav_links:
        return result

    page_groups = {}
    for link in nav_links:
        page = link["page"]
        page_groups.setdefault(page, []).append(link)

    tasks = [
        run_c_full_v2_for_page(
            website_dir, page_filename, links,
            architecture, interfaces, website_data,
            business_logic_js, semaphore,
        )
        for page_filename, links in page_groups.items()
    ]

    page_results = await asyncio.gather(*tasks)

    for pr in page_results:
        result["pages_tested"] += 1
        bugs = pr.get("bugs", [])
        result["total_bugs"] += len(bugs)
        result["page_results"].append(pr)
        for bug in bugs:
            bug["website"] = website_name
            bug["page"] = pr.get("page", "")
            result["all_bugs"].append(bug)

    return result


# ============================================================================
# Batch Runner
# ============================================================================

async def run_batch(batch_dir: str, concurrency: int = 64, config_path: str = None):
    """Run both C-Lite and C-Full tests on all websites in a batch directory."""

    # Configure LLM if config provided
    if config_path:
        config = json.load(open(config_path, encoding="utf-8"))
        configure_load_balancing(
            endpoints=config.get("endpoints"),
            strategy=config.get("load_balance_strategy", "round_robin"),
            deployment=config.get("deployment", "gpt-5.1"),
        )

    # Find all website directories
    website_dirs = sorted([
        os.path.join(batch_dir, d) for d in os.listdir(batch_dir)
        if os.path.isdir(os.path.join(batch_dir, d))
    ])

    print(f"Found {len(website_dirs)} websites in {batch_dir}")

    # Phase 1: Run C-Lite on all (fast, no API calls)
    print("\n" + "="*60)
    print("Phase 1: C-Lite (Static Data Cross-Reference)")
    print("="*60)

    c_lite_results = []
    c_lite_issues_total = 0
    for wd in website_dirs:
        r = run_c_lite(wd)
        c_lite_results.append(r)
        n_issues = len(r.get("issues", []))
        if n_issues > 0:
            c_lite_issues_total += n_issues
            print(f"  [FAIL] {r['website']}: {n_issues} issues")

    c_lite_with_issues = [r for r in c_lite_results if r.get("issues")]
    c_lite_with_params = [r for r in c_lite_results if r.get("nav_links_with_params", 0) > 0]

    print(f"\nC-Lite Summary:")
    print(f"  Websites with nav params: {len(c_lite_with_params)}/{len(website_dirs)}")
    print(f"  Websites with issues: {len(c_lite_with_issues)}")
    print(f"  Total issues found: {c_lite_issues_total}")

    # Phase 2: Run C-Full on websites with nav params
    print("\n" + "="*60)
    print(f"Phase 2: C-Full (LLM Analysis, concurrency={concurrency})")
    print("="*60)

    semaphore = asyncio.Semaphore(concurrency)

    # Only run C-Full on websites that have nav params
    c_full_candidates = [
        wd for wd in website_dirs
        if any(r["website"] == os.path.basename(wd) and r.get("nav_links_with_params", 0) > 0
               for r in c_lite_results)
    ]

    print(f"Running C-Full on {len(c_full_candidates)} websites with nav params...")

    c_full_tasks = [run_c_full_v2(wd, semaphore) for wd in c_full_candidates]

    completed = 0
    c_full_results = []

    # Process in chunks for progress reporting
    chunk_size = 20
    for i in range(0, len(c_full_tasks), chunk_size):
        chunk = c_full_tasks[i:i+chunk_size]
        chunk_results = await asyncio.gather(*chunk)
        c_full_results.extend(chunk_results)
        completed += len(chunk)
        bugs_so_far = sum(r.get("total_bugs", 0) for r in c_full_results)
        print(f"  Progress: {completed}/{len(c_full_candidates)} websites, {bugs_so_far} bugs found so far")

    c_full_with_bugs = [r for r in c_full_results if r.get("total_bugs", 0) > 0]
    c_full_bugs_total = sum(r.get("total_bugs", 0) for r in c_full_results)

    print(f"\nC-Full Summary:")
    print(f"  Websites analyzed: {len(c_full_results)}")
    print(f"  Websites with bugs: {len(c_full_with_bugs)}")
    print(f"  Total bugs found: {c_full_bugs_total}")

    return c_lite_results, c_full_results


# ============================================================================
# Report Generation
# ============================================================================

def generate_report(c_lite_results: list, c_full_results: list, output_path: str):
    """Generate a combined markdown report."""

    total_websites = len(c_lite_results)

    # C-Lite stats
    c_lite_with_params = [r for r in c_lite_results if r.get("nav_links_with_params", 0) > 0]
    c_lite_with_issues = [r for r in c_lite_results if r.get("issues")]
    c_lite_issues_total = sum(len(r.get("issues", [])) for r in c_lite_results)

    # C-Full stats
    c_full_with_bugs = [r for r in c_full_results if r.get("total_bugs", 0) > 0]
    c_full_bugs_total = sum(r.get("total_bugs", 0) for r in c_full_results)

    # Categorize C-Lite issues by type
    c_lite_by_type = {}
    for r in c_lite_results:
        for issue in r.get("issues", []):
            t = issue.get("type", "unknown")
            c_lite_by_type.setdefault(t, []).append({**issue, "website": r["website"]})

    # Categorize C-Full bugs by type
    c_full_by_type = {}
    for r in c_full_results:
        for bug in r.get("all_bugs", []):
            t = bug.get("type", "unknown")
            c_full_by_type.setdefault(t, []).append(bug)

    lines = []
    lines.append("# Navigation Contract Test Report")
    lines.append(f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total websites**: {total_websites}")
    lines.append(f"**Websites with nav params**: {len(c_lite_with_params)}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | C-Lite (Static) | C-Full (LLM) |")
    lines.append("|--------|-----------------|--------------|")
    lines.append(f"| Websites tested | {len(c_lite_with_params)} | {len(c_full_results)} |")
    lines.append(f"| Websites with bugs | {len(c_lite_with_issues)} | {len(c_full_with_bugs)} |")
    lines.append(f"| Total bugs found | {c_lite_issues_total} | {c_full_bugs_total} |")
    lines.append("")

    # C-Lite Results
    lines.append("## C-Lite: Static Data Cross-Reference")
    lines.append("")
    lines.append("C-Lite checks whether navigation link parameter values exist in the actual website data.")
    lines.append("No LLM is used — this is pure static analysis.")
    lines.append("")

    if c_lite_by_type:
        lines.append("### Issues by Type")
        lines.append("")
        for issue_type, issues in sorted(c_lite_by_type.items(), key=lambda x: -len(x[1])):
            lines.append(f"#### `{issue_type}` ({len(issues)} issues)")
            lines.append("")

            if issue_type == "value_not_in_data":
                # Group by website for readability
                by_website = {}
                for issue in issues:
                    ws = issue.get("website", "unknown")
                    by_website.setdefault(ws, []).append(issue)

                for ws, ws_issues in sorted(by_website.items()):
                    lines.append(f"**{ws}**")
                    for iss in ws_issues:
                        hier = " *(hierarchical mismatch)*" if iss.get("is_parent_of_existing") else ""
                        lines.append(f"- `{iss.get('param', '')}={iss.get('param_value', '')}` "
                                   f"in link \"{iss.get('nav_link', '')}\"{hier}")
                        sample = iss.get("sample_data_values", [])[:8]
                        if sample:
                            lines.append(f"  - Data values: `{sample}`")
                    lines.append("")
            else:
                for issue in issues[:20]:
                    lines.append(f"- **{issue.get('website', '')}**: "
                               f"\"{issue.get('nav_link', '')}\" → {issue.get('description', '')}")
                if len(issues) > 20:
                    lines.append(f"- ... and {len(issues) - 20} more")
                lines.append("")
    else:
        lines.append("No issues found by C-Lite.")
        lines.append("")

    # C-Full Results
    lines.append("## C-Full: LLM-Based Analysis")
    lines.append("")
    lines.append("C-Full uses an LLM to analyze navigation links, SDK function code, data models,")
    lines.append("and actual data together to find deeper bugs that static analysis cannot catch.")
    lines.append("")

    if c_full_by_type:
        lines.append("### Bugs by Type")
        lines.append("")
        for bug_type, bugs in sorted(c_full_by_type.items(), key=lambda x: -len(x[1])):
            lines.append(f"#### `{bug_type}` ({len(bugs)} bugs)")
            lines.append("")

            # Group by website
            by_website = {}
            for bug in bugs:
                ws = bug.get("website", "unknown")
                by_website.setdefault(ws, []).append(bug)

            for ws, ws_bugs in sorted(by_website.items()):
                lines.append(f"**{ws}**")
                for bug in ws_bugs:
                    sev = bug.get("severity", "?")
                    lines.append(f"- [{sev.upper()}] {bug.get('description', '')}")
                    if bug.get("evidence"):
                        lines.append(f"  - Evidence: {bug['evidence'][:200]}")
                    if bug.get("affected_function"):
                        lines.append(f"  - Function: `{bug['affected_function']}`")
                lines.append("")
    else:
        lines.append("No bugs found by C-Full.")
        lines.append("")

    # C-Full only bugs (found by C-Full but not C-Lite)
    c_lite_websites_with_issues = {r["website"] for r in c_lite_with_issues}
    c_full_only = [r for r in c_full_with_bugs
                   if r["website"] not in c_lite_websites_with_issues]

    if c_full_only:
        lines.append("### Bugs Found Only by C-Full (Not by C-Lite)")
        lines.append("")
        lines.append(f"{len(c_full_only)} websites had bugs detected only by LLM analysis:")
        lines.append("")
        for r in c_full_only:
            lines.append(f"- **{r['website']}**: {r['total_bugs']} bugs")
            for bug in r.get("all_bugs", [])[:3]:
                lines.append(f"  - [{bug.get('severity', '?').upper()}] {bug.get('description', '')}")
        lines.append("")

    # Detailed per-website results
    lines.append("## Detailed Results by Website")
    lines.append("")

    # Combine C-Lite and C-Full results per website
    c_full_by_website = {r["website"]: r for r in c_full_results}

    for r in sorted(c_lite_results, key=lambda x: -len(x.get("issues", []))):
        ws = r["website"]
        c_lite_issues = r.get("issues", [])
        c_full_r = c_full_by_website.get(ws, {})
        c_full_bugs = c_full_r.get("all_bugs", [])

        if not c_lite_issues and not c_full_bugs:
            continue

        lines.append(f"### {ws}")
        lines.append("")
        lines.append(f"- Nav links with params: {r.get('nav_links_with_params', 0)}")
        lines.append(f"- C-Lite issues: {len(c_lite_issues)}")
        lines.append(f"- C-Full bugs: {len(c_full_bugs)}")
        lines.append("")

        if c_lite_issues:
            lines.append("**C-Lite Issues:**")
            for iss in c_lite_issues:
                lines.append(f"- `{iss.get('type', '')}`: {iss.get('description', '')}")
            lines.append("")

        if c_full_bugs:
            lines.append("**C-Full Bugs:**")
            for bug in c_full_bugs:
                lines.append(f"- [{bug.get('severity', '?').upper()}] `{bug.get('type', '')}`: {bug.get('description', '')}")
                if bug.get("evidence"):
                    evidence = bug["evidence"][:300].replace("\n", " ")
                    lines.append(f"  - Evidence: {evidence}")
            lines.append("")

        if c_full_r.get("page_results"):
            for pr in c_full_r["page_results"]:
                if pr.get("summary") and pr.get("bugs"):
                    lines.append(f"  *LLM Summary for {pr.get('page', '?')}*: {pr['summary']}")
            lines.append("")

    report = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nReport saved to: {output_path}")
    return report


# ============================================================================
# Main
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Navigation Contract Tester")
    parser.add_argument("--batch-dir", required=True, help="Batch directory with generated websites")
    parser.add_argument("--config", required=True, help="API config JSON file")
    parser.add_argument("--concurrency", type=int, default=64, help="Max concurrent LLM calls")
    parser.add_argument("--output", default=None, help="Output report path (markdown)")
    parser.add_argument("--output-json", default=None, help="Output raw results as JSON")
    args = parser.parse_args()

    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"nav_contract_test_report_{timestamp}.md"

    # Run tests
    c_lite_results, c_full_results = await run_batch(
        args.batch_dir, args.concurrency, args.config
    )

    # Save raw JSON results
    if args.output_json:
        raw = {
            "c_lite": c_lite_results,
            "c_full": c_full_results,
            "timestamp": datetime.now().isoformat(),
        }
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        print(f"Raw results saved to: {args.output_json}")

    # Generate report
    generate_report(c_lite_results, c_full_results, args.output)


if __name__ == "__main__":
    asyncio.run(main())
