import os
from PIL import Image
import llm as llm
from natsort import natsorted
import json

class Retrace:
    def __init__(self, model):
        self.planner = llm.Llm(model=model)

    def extract_process(self, image_path: str) -> str:
        traj_file_path = os.path.join(image_path, "traj.jsonl")
        
        codes = []
        for line in open(traj_file_path, 'r'):
            line_json = json.loads(line.strip())
            action  = line_json["action"]
            codes.append(action)

        image_files = [f for f in os.listdir(image_path) if f.endswith(('.png', '.jpg', '.jpeg'))]
        image_files = natsorted(image_files)
        results = []
        for i in range(len(image_files) - 1):
            image1_path = os.path.join(image_path, image_files[i])
            image2_path = os.path.join(image_path, image_files[i + 1])

            code = codes[i]

            result = self.planner.process_request(  
                system_prompt = """  
                    You are a senior QA assistant.    
                    You receive:    
                    • BEFORE screenshot <image0>    
                    • AFTER  screenshot <image1>    
                    • A snippet of Python automation code.    
                    
                    Your task:    
                    
                    PART A - BEFORE DESCRIPTION    
                    Describe concisely and objectively what is visible in the BEFORE screenshot only.    
                    • ≤ 80 words, declarative sentences.    
                    • No speculation, no mention of AFTER, no hidden reasoning.    
                    
                    PART B - UI OPERATION LIST    
                    List, in chronological order, every visible UI step (mouse-click, key-stroke, drag, menu selection…) that converted the BEFORE state into the AFTER state.    
                    
                    OUTPUT FORMAT (STRICT)    
                    [A] BEFORE    
                    <one-to-three short sentences that satisfy PART A>    
                    
                    [B] OPERATIONS    
                    - <action>, <visible consequence>    
                    - …    
                    
                    RULES FOR PART B (inherited)    
                    1. Bullet list; every line begins with "- ".    
                    2. Each bullet MUST pair the action with its visible consequence, e.g.    
                    - Clicked the "Replace All" button in VS Code's Search sidebar, replacing all 12 occurrences of "text" with "test" in the open file    
                    3. Do not add headings, explanations or blank lines beyond the specified format.    
                    4. If the ONLY difference is the system clock, Part B must contain exactly one bullet:    
                    - No operations performed.    
                    5. If the screenshots cannot be compared, Part B must contain exactly one bullet:    
                    - Unable to determine operations.    
                    
                    Think step-by-step internally but reveal ONLY the two required sections.    
                    
                    FEW-SHOT EXAMPLES    
                    
                    <BEGIN_EXAMPLE>    
                    # Normal change with visible result    
                    BEFORE: VS Code shows 3 occurrences of "foo"    
                    AFTER : All occurrences now read "bar"    
                    CODE  : editor.replace_all("foo", "bar")    
                    OUTPUT:    
                    [A] BEFORE    
                    VS Code editor window is open; the Find/Replace panel indicates 3 matches for the word "foo".    
                    
                    [B] OPERATIONS    
                    - Pressed Ctrl+H in the VS Code editor, opening the Find/Replace panel    
                    - Typed "foo" into the Find box, highlighting 3 matches in the file    
                    - Typed "bar" into the Replace box    
                    - Clicked the "Replace All" button in the Find/Replace panel, replacing all 3 occurrences of "foo" with "bar" in the document    
                    <END_EXAMPLE>    
                    
                    <BEGIN_EXAMPLE>    
                    # Only the clock changed    
                    BEFORE: Desktop 10:01    
                    AFTER : Desktop 10:02    
                    OUTPUT:    
                    [A] BEFORE    
                    Desktop environment showing wallpaper and system clock reading 10:01.    
                    
                    [B] OPERATIONS    
                    - No operations performed.    
                    <END_EXAMPLE>    
                    
                    <BEGIN_EXAMPLE>    
                    # Incomparable    
                    BEFORE: Corrupted screenshot    
                    AFTER : Corrupted screenshot    
                    OUTPUT:    
                    [A] BEFORE    
                    Screenshot is corrupted; no discernible UI elements are visible.    
                    
                    [B] OPERATIONS    
                    - Unable to determine operations.    
                    <END_EXAMPLE>    
                """.strip(), 
                question = f"""  
                The FIRST image (<image0>) shows the screen BEFORE the Agent acted.  
                The SECOND image (<image1>) shows the screen AFTER the Agent acted.  
                
                The Agent executed the following Python code:  
                
                ```python  
                {code}  
                List the UI operations (action + visible result).
                """.strip(),
                images=[image1_path, image2_path]  
            )  
            results.append(f"Step {i+1}: {result}")

        return results 