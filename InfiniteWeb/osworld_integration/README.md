# OSWorld Integration Guide

This guide explains how to deploy InfiniteWeb-generated websites in [OSWorld](https://github.com/xlang-ai/OSWorld) for GUI agent evaluation and training.

## Overview

InfiniteWeb generates fully functional websites with user tasks and evaluation logic. These can be converted into OSWorld-compatible task JSONs and deployed inside OSWorld's virtual machine environment, where GUI agents interact with the websites through a browser.

**Pipeline:**

```
InfiniteWeb Website Generation
        |
        v
rewritten_tasks.json + evaluators.json
        |
        v
generate_task_jsons.py  (+ task_template.json)
        |
        v
OSWorld-Compatible Task JSONs  (one per task + test_all.json)
        |
        v
Package websites as tar.gz
        |
        v
Deploy in OSWorld (VM + Chrome + evaluation)
```

## Prerequisites

- A working [OSWorld](https://github.com/xlang-ai/OSWorld) environment (Docker or VMware)
- A VM snapshot named `chrome` with Google Chrome installed
- Generated websites from InfiniteWeb (with `rewritten_tasks.json` and `evaluators.json` in each website folder)

## Step 1: Generate Task JSONs

Convert InfiniteWeb output into OSWorld-compatible task JSON files:

```bash
# Batch mode (recommended)
python src/generate_task_jsons.py \
    --batch-dir results/batch_generated/20260202_115426 \
    --template osworld_integration/task_template.json

# Single website mode
python src/generate_task_jsons.py \
    --website-dir results/generated/my_website \
    --template osworld_integration/task_template.json
```

**Input files** (from each generated website):
| File | Description |
|------|-------------|
| `rewritten_tasks.json` | Task definitions with human-readable instructions and optional config (e.g., system time) |
| `evaluators.json` | JavaScript evaluation logic for each task |

**Output** (in `task_jsons/` subfolder):
| File | Description |
|------|-------------|
| `{website_name}_{task_number}.json` | One OSWorld task JSON per task |
| `test_all.json` | Index file listing all task IDs |

## Step 2: Replace OSWorld Files

InfiniteWeb requires modifications to several OSWorld files to support localStorage-based evaluation and time synchronization. Copy the files from `osworld_integration/desktop_env/` into your OSWorld installation:

```bash
cp -r osworld_integration/desktop_env/* /path/to/your/OSWorld/desktop_env/
```

**Files replaced:**

| File | Description |
|------|-------------|
| `controllers/setup.py` | Adds `_set_system_time_setup` for freezing VM time to data generation date |
| `controllers/__init__.py` | Registers the new setup controller |
| `evaluators/getters/website.py` | **New** — localStorage evaluation via Playwright (container + CDP modes) |
| `evaluators/getters/__init__.py` | Registers `get_website_localStorage_evaluation` |
| `evaluators/metrics/website.py` | **New** — `check_website_localStorage_evaluation` scoring function |
| `evaluators/metrics/__init__.py` | Registers the website metric |
| `evaluators/__init__.py` | Updated evaluator framework |

## Step 3: Package Websites

Package the generated website folders into a tar.gz archive for upload to the OSWorld VM:

```bash
cd results/batch_generated/20260202_115426
tar -czf website_examples.tar.gz */
```

Inside the VM, websites will be extracted to `/home/user/{website_name}/`, e.g.:

```
/home/user/100_social_media___conte/
├── index.html
├── *.html / *.css
├── business_logic.js
├── website_data.json
└── ...
```

## Step 4: Deploy to OSWorld

1. Place the `website_examples.tar.gz` file where OSWorld can access it (typically alongside the task JSONs).
2. Copy the generated task JSON files into OSWorld's `evaluation_examples/examples/` directory.
3. Add task IDs to your test collection JSON (or use the generated `test_all.json`).

Each task JSON defines a setup sequence that OSWorld executes automatically:

| Step | Config Type | What It Does |
|------|-------------|--------------|
| 0 | `set_system_time` | Sets VM clock to the data generation date (for time-sensitive websites) |
| 1 | `upload_file` | Uploads `website_examples.tar.gz` to `/tmp/` in the VM |
| 2 | `execute` | Extracts the archive to `/home/user/` |
| 3 | `launch` | Starts Chrome with `--remote-debugging-port=1337` |
| 4 | `launch` | Starts `socat tcp-listen:9222,fork tcp:localhost:1337` for CDP forwarding |
| 5 | `chrome_open_tabs` | Opens `file:///home/user/{website_name}/index.html` |
| 6 | `activate_window` | Focuses the Chrome window |

After setup, the GUI agent interacts with the website to complete the task.

## Task JSON Schema

See [`task_template.json`](task_template.json) for the full template. Key fields:

| Field | Description |
|-------|-------------|
| `id` | Unique task identifier, format: `{website_name}_{task_number}` |
| `snapshot` | VM snapshot to revert to before task (default: `chrome`) |
| `instruction` | Natural language task description for the agent |
| `source` | Task source category (e.g., `website_examples`) |
| `config` | Array of setup commands (see table above) |
| `evaluator.func` | Evaluation function name: `check_website_localStorage_evaluation` |
| `evaluator.result.type` | Evaluation type: `website_localStorage_evaluation` |
| `evaluator.result.evaluation_logic` | JavaScript code that checks task completion |
| `related_apps` | Apps involved (always `["chrome"]` for web tasks) |

## Evaluation Mechanism

InfiniteWeb uses **localStorage-based dense reward evaluation**. The evaluation logic is JavaScript code that runs in the browser context after the agent finishes:

1. The evaluator reads relevant data from `localStorage` (where all website data is stored)
2. It checks multiple conditions (checkpoints), each with a weight
3. It returns a weighted score between 0.0 and 1.0

**Example evaluation logic:**

```javascript
const checkpoints = [];

// Checkpoint 1 (weight 0.4): Check if a post was created
const posts = JSON.parse(localStorage.getItem('posts') || '[]');
const newPost = posts.some(p => p.contentText.toLowerCase().includes('coffee'));
checkpoints.push({ passed: newPost, weight: 0.4 });

// Checkpoint 2 (weight: 0.3): Check if it was scheduled
const scheduled = JSON.parse(localStorage.getItem('scheduledposts') || '[]');
const isScheduled = scheduled.some(s => s.postId === newPost?.id);
checkpoints.push({ passed: isScheduled, weight: 0.3 });

// Checkpoint 3 (weight: 0.3): Check the scheduled time
const correctTime = scheduled.some(s => new Date(s.scheduledAt).getUTCHours() === 9);
checkpoints.push({ passed: correctTime, weight: 0.3 });

// Return weighted score (0.0 - 1.0)
return checkpoints.reduce((sum, cp) => sum + (cp.passed ? cp.weight : 0), 0);
```

The evaluation is executed inside the VM via Playwright (connecting to Chrome through CDP), ensuring it runs in the same browser context where the agent operated.

## Environment Reset

OSWorld **reverts the VM to a clean snapshot** before each task. This means:

- Chrome starts fresh (no browsing history, no cached data)
- `localStorage` is empty (no stale data from previous websites)
- The file system is clean (websites are re-uploaded and extracted each time)

This is critical because all InfiniteWeb websites use `localStorage` for data storage. Since `localStorage` is shared across pages served from the same `file://` origin, running multiple websites without cleanup would cause data conflicts.

## Time Synchronization

Many generated websites contain time-sensitive data (e.g., flight schedules, hotel availability, event dates). The `set_system_time` config step sets the VM's clock to the date when the data was generated, ensuring that:

- "Upcoming" events are still in the future
- "Recent" items are still recent
- Date-based filters and sorting work correctly

This config is automatically added by InfiniteWeb's task rewriter based on the data generation date.
