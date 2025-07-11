import os
import json
from critic import Critic
from retrace import Retrace
from config import config

class Pipeline:
    def __init__(self, path, critic_model=None, retrace_model=None):
        self.path = path
        if critic_model is None:
            critic_model = config.critic_model
        if retrace_model is None:
            retrace_model = config.retrace_model
            
        self.critic = Critic(model=critic_model)
        self.original_plan = ""
        self.instruction = ""
        self.retrace = Retrace(model=retrace_model)

    def load_traj(self):
        traj_path = os.path.join(self.path, "traj.jsonl")
        with open(traj_path, "r") as f:
            lines = f.readline()
            line_json = json.loads(lines.strip())
            self.original_plan = line_json["agent-s-info"]["goal_plan"]
            self.instruction = line_json["instruction"]

    def process_actions(self):
        action_list = self.retrace.extract_process(self.path)
        return "\n".join(action_list)

    def analyze(self):
        self.load_traj()
        action_list_str = self.process_actions()
        print("actionlist:", action_list_str)
        result = self.critic.catch_crime(
            action_list=action_list_str,
            plan=self.original_plan,
            task_instruction=self.instruction
        )
        print("result:", result)
        record_log = action_list_str+"\n" + result
        return result, record_log