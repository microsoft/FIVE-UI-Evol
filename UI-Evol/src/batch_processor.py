import json
import os
import time
import threading
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from pipeline import Pipeline
from config import config


class BatchProcessor:
    def __init__(self):
        self.lock = Lock()
        self.lock2 = Lock()
        self.completed_tasks = 0
        self.total_tasks = 0
        self.error_tasks = []
        self.start_time = None

    def process_directory(self, dir_path, history_path):
        traj_path = os.path.join(dir_path, "traj.jsonl")
        instruction = None
        try:
            with open(traj_path, 'r') as traj_file:
                first_line = traj_file.readline()
                traj_data = json.loads(first_line)
                instruction = traj_data.get("instruction", None)
        except Exception as e:
            print(f"Error reading traj.jsonl in {dir_path}: {e}")
            raise e

        log_learner = Pipeline(path=dir_path)
        result , record_log = log_learner.analyze()

        json_path = os.path.join(history_path, "result.jsonl")
        result_to_save = {instruction: record_log}
        with self.lock2:
            with open(json_path, 'a', encoding='utf-8') as json_file:
                json.dump(result_to_save, json_file, indent=4, ensure_ascii=False)
                json_file.write("\n")

        start_index = result.find("REFINED PLAN:")
        if start_index == -1:
            start_index = result.find("REFINED PLAN")
            if start_index != -1:
                result = result[start_index + len("REFINED PLAN"):].strip()
            else:
                print(f"Error: Unable to find 'REFINED PLAN' in the result for {dir_path}.")
                raise ValueError("Unexpected result format")
        else:
            result = result[start_index + len("REFINED PLAN:"):].strip()

        knowledge_path = os.path.join(history_path, "knowledge.json")
        with self.lock:
            try:
                with open(knowledge_path, 'r') as knowledge_file:
                    knowledge_data = json.load(knowledge_file)
                knowledge_data[instruction] = result
                with open(knowledge_path, 'w') as knowledge_file:
                    json.dump(knowledge_data, knowledge_file, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"Error updating knowledge file for {dir_path}: {e}")
                raise e

    def History_to_Lesson(self, history_path: str, domains: list):
        tasks = []
        for domain in domains:
            domain_path = os.path.join(history_path, domain)
            print(f"Processing domain: {domain} at path: {domain_path}")
            for root, dirs, files in os.walk(domain_path):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    tasks.append((dir_path, history_path))

        self.total_tasks = len(tasks)
        self.start_time = time.time()

        max_workers = config.max_workers
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for dir_path, history_path in tasks:
                future = executor.submit(self.process_directory, dir_path, history_path)
                futures[future] = (dir_path, threading.current_thread().name)

            for future in as_completed(futures):
                dir_path, thread_name = futures[future]
                try:
                    print(f"Task started for {dir_path} on thread {thread_name}")
                    future.result()
                    print(f"Task completed for {dir_path} on thread {thread_name}")
                    self.completed_tasks += 1
                except Exception as e:
                    print(f"Error processing {dir_path} on thread {thread_name}: {e}")
                    self.error_tasks.append(dir_path)
                finally:
                    elapsed_time = time.time() - self.start_time
                    avg_time_per_task = elapsed_time / self.completed_tasks if self.completed_tasks > 0 else 0
                    remaining_time = avg_time_per_task * (self.total_tasks - self.completed_tasks)

                    with open("progress.txt", "w") as progress_file:
                        progress_file.write(f"Completed: {self.completed_tasks}/{self.total_tasks}\n")
                        progress_file.write(f"Remaining: {self.total_tasks - self.completed_tasks}\n")
                        progress_file.write(f"Estimated time remaining: {remaining_time:.2f} seconds\n")

        with open("errors.txt", "w") as error_file:
            for error_task in self.error_tasks:
                error_file.write(f"{error_task}\n")

    def retry_failed_tasks(self, history_path: str):
        errors_file_path = "errors.txt"
        if not os.path.exists(errors_file_path):
            print("No errors.txt file found. No tasks to retry.")
            return

        retry_tasks = []
        with open(errors_file_path, "r") as error_file:
            for line in error_file:
                dir_path = line.strip()
                if dir_path:
                    retry_tasks.append((dir_path, history_path))

        if not retry_tasks:
            print("No tasks found in errors.txt to retry.")
            return

        print(f"Retrying {len(retry_tasks)} failed tasks...")

        self.error_tasks = []
        self.completed_tasks = 0
        self.total_tasks = len(retry_tasks)
        self.start_time = time.time()

        max_workers = config.max_workers
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for dir_path, history_path in retry_tasks:
                future = executor.submit(self.process_directory, dir_path, history_path)
                futures[future] = dir_path

            for future in as_completed(futures):
                dir_path = futures[future]
                try:
                    print(f"Retrying task for {dir_path}")
                    future.result()
                    print(f"Task completed for {dir_path}")
                    self.completed_tasks += 1
                except Exception as e:
                    print(f"Error retrying {dir_path}: {e}")
                    self.error_tasks.append(dir_path)
                finally:
                    elapsed_time = time.time() - self.start_time
                    avg_time_per_task = elapsed_time / self.completed_tasks if self.completed_tasks > 0 else 0
                    remaining_time = avg_time_per_task * (self.total_tasks - self.completed_tasks)

                    with open("progress.txt", "w") as progress_file:
                        progress_file.write(f"Completed: {self.completed_tasks}/{self.total_tasks}\n")
                        progress_file.write(f"Remaining: {self.total_tasks - self.completed_tasks}\n")
                        progress_file.write(f"Estimated time remaining: {remaining_time:.2f} seconds\n")

        with open(errors_file_path, "w") as error_file:
            for error_task in self.error_tasks:
                error_file.write(f"{error_task}\n")


if __name__ == '__main__':
    
    
    controller = BatchProcessor()
    history_path = config.history_path
    domains = config.domains
    
    if not os.path.exists("errors.txt"):
        print("No errors.txt file found. Processing all tasks...")
        controller.History_to_Lesson(history_path, domains)
        print("All domains processed.")
    else:   
        print("errors.txt file found. Processing tasks with retry...")
        controller.retry_failed_tasks(history_path)
        print("Retry of failed tasks completed.")
    