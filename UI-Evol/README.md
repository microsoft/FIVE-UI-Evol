# UI-Evol

UI-Evol is a Python-based framework that leverages Large Language Models (LLMs) to analyze user interface operation trajectories, identify deviations bewteen original knowledge and agent actions , and generate refined knowledge for future use. The system processes trajectory to understand UI operations and provide intelligent feedback for knowledge improvement.

## Main Experimental Results
<div align="center">
  <img src="./imgs/main_results.png" width=90%/>
</div>


## Architecture

The system consists of several core components:

- **Retrace**: Extracts and analyzes UI operations from screenshot sequences
- **Critic**: Analyzes action lists against original knowledge and provides refined knowledge
- **Pipeline**: Orchestrates the analysis workflow
- **BatchProcessor**: Handles bulk processing of trajectory data

## Installation

1. Clone the repository:
```bash
git clone https://github.com/microsoft/E2I-Synth.git
cd UI-Evol
```

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

3. Configure the system by editing `config/config.yaml`:
   - Set your Azure OpenAI endpoints
   - Configure model selections
   - Set appropriate paths for your trajectory data

## Usage

1. Put your knowledge.json to the same path of your trajectory data

2. Run batch processing directly:

```bash
cd src
python batch_processor.py
```

## Trace Introduction

This section is to introduce the file structure and usage of UI-Evol Trace Files.

### File Structure
- software/ (chrome, gimp, libreoffice ...)
    - task_id/  
        - results.txt : This file contains the overall results of the task. Usually, 1 represents success and others represent different types of failures.
        - step_X_timestamp.png : These files are screenshots taken before each step of the task.
        - traj.jsonl : This file is the main trajectory file that contains the detailed information about the task execution.

### traj.jsonl 

The traj.jsonl usually contains a list of JSON objects, each representing a step in the task execution.
Important fields in each JSON object: 
- `action` : The action taken in this step.
- `step_num` : The step number in the task execution, starting from 1.
- `introduction` : The introduction for OSWorld task.
- `screenshot_file` : The screenshot taken after this step.
- `agent-s-info["goal_plan"]` : The plan for achieving the goal in the rest of the task. For Step 1 in each task, this represents our knowledge given for this specific task.
- `agent-s-info["subtask"]` : The current subtask being executed.
- `agent-s-info["executor_plan"]` : AgentS's thought process for this step.

### Usage Example

Here is a short Python example for accessing these fields in traj.jsonl:

```python
import json

traj_path = "software/<software_name>/<task_id>/traj.jsonl"

with open(traj_path, "r", encoding="utf-8") as f:
        for line in f:
                step = json.loads(line)
                action = step.get("action")
                step_num = step.get("step_num")
                introduction = step.get("introduction")
                screenshot_file_after = step.get("screenshot_file")
                agent_info = step.get("agent-s-info", {})
                goal_plan = agent_info.get("goal_plan")
                subtask = agent_info.get("subtask")
                executor_plan = agent_info.get("executor_plan")
                
                print(f"Step {step_num}:")
                print(f"  Action: {action}")
                print(f"  Introduction: {introduction}")
                print(f"  After Screenshot: {screenshot_file}")
                print(f"  Goal Plan: {goal_plan}")
                print(f"  Subtask: {subtask}")
                print(f"  Executor Plan: {executor_plan}")
```


## License

This project is licensed under the terms specified in the repository.

## Citation

If you feel our paper or code is helpful, please cite our paper:

```
@misc{zhang2025uievolautomaticknowledgeevolving,
      title={UI-Evol: Automatic Knowledge Evolving for Computer Use Agents}, 
      author={Ziyun Zhang and Xinyi Liu and Xiaoyi Zhang and Jun Wang and Gang Chen and Yan Lu},
      year={2025},
      eprint={2505.21964},
      archivePrefix={arXiv},
      primaryClass={cs.HC},
      url={https://arxiv.org/abs/2505.21964}, 
}
```

