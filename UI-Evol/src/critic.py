import llm as llm
import os

class Critic:
    def __init__(self, model):
        self.planner = llm.Llm(model=model)

    def catch_crime(self, action_list: str, plan: str, task_instruction: str) -> str:
        question="""
            INPUT  
              Task Instruction: …  
              Action List: …  
              Original Plan: …  
  
            REQUIREMENTS  
                • Follow the FIVE SECTION HEADERS below exactly.  
                • SECTION E output style:  
                      1. **<Subtask>**:  
                         - <Concrete UI / CLI action(s) only>  
                         - Purpose: <≤ 10-word reason>  
                • If a field is not applicable, write "None" or "No deviation".  
                • If SECTION C judges an Alternative better, the final NEW PLAN must adopt it (or its key advantages).  
                • Every Root Cause from SECTION B must have a mitigation explained in SECTION D and be implicitly addressed (not as a standalone step) in SECTION E.  
                • Exclude passive "Confirm / Verify / Check / Make sure …" kinds of steps.  
                • Visual inspections are assumed; do not list them.
                • If the Action List shows a dialog / branch / extra option that the Original Plan did not anticipate:
                - Treat it as a Deviation (Root Cause usually f) Invalid assumption).
                - If the Agent picked the wrong option, SECTION D must state the correct option and SECTION E must insert that corrected step.
                - If the Agent picked the right option, still add that step to SECTION E (it is an "added step").
                - Any action shown to be unnecessary in the trajectory must be omitted from SECTION E (this is a "removed step").
  
            SECTION A. Task Completion  
              Did the Agent achieve the task goal? (Yes / No)  
              Reason.
              Did the Agent execute more than the instruction required? (Yes / No)
              Reason.
  
            SECTION B. Deviation Analysis  
              For every mismatch between an Original-Plan assumption and the actual screen/CLI output in Action List, record a Deviation row. Fill in ALL items, even if "No deviation".  
              • Deviation Step: <# or "None">  
              • Expected Action : …  
              • Actual Action    : …  
              • Root Cause (letters, commas allowed):  
                    a) Output/screen misunderstanding  
                    b) Knowledge gap  
                    c) Command / code / syntax error  
                    d) Environment or permission issue  
                    e) Other  
                    f) Invalid assumption  
                    g) External transient failure
                    h) Step order issue
                    i) Missing precondition
  
            SECTION C. Alternative Approaches  
              Did the Agent attempt any approach beyond the Original Plan? (Yes / No)  
              If Yes:  
                  • Describe each approach briefly.  
                  • Which is better (Original / Alternative)? Why?  
              If No: "No alternative approach tried."  
  
            SECTION D. Mitigation & Rationale  
              For every Root Cause from SECTION B, describe the preventive or corrective idea and mention which forthcoming step embodies it.  
              Example:  
                  c) Syntax error → Add "lint before run" check (handled in Step 2).  
                  d) Permission → Verify sudo rights before executing installer (Step 5).
                  f) Invalid assumption → Choose "Typical" in installer dialog (Step 2).  
  
            SECTION E. REFINED PLAN:  
              REFINED PLAN:  
                  1. **<Subtask>**:  
                     - <Concrete action(s)>  
                     - Purpose: <Why this step?>  
                  2. **<Subtask>**:  
                     - <Concrete action(s)>  
                     - Purpose: …  
                  …  
                  up to 15 steps total.  
              • No shell prompts (#, $).  
              • Safeguards are implicit per SECTION D; do not list them as separate lines.
              • Newly added corrective steps must appear in the proper sequence among Steps 1-15; actions deemed unnecessary must not appear here.   
            """
        question+= "Task Instruction:\n"
        question+= task_instruction + "\n"

        question+= "Action List:\n"
        question+=action_list

        question+= "Original Plan:\n"
        question+=plan
        
        
        result = self.planner.process_request(
            system_prompt="You are an AI assistant who must analyze an execution trajectory of a Linux Agent and propose improvements.",
            question=question,
            images=None
        )

        return result
    