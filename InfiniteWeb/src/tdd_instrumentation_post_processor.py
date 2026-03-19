"""
TDD Instrumentation Post-Processor
Independent module for adding instrumentation to generated websites and creating evaluators
"""

import os
import json
import re
import argparse
import asyncio
import subprocess
import tempfile
from typing import Dict, Any, List
from tdd_logger_module import TDDLogger
from tdd_instrumentation_analyzer import TDDInstrumentationAnalyzer
from tdd_instrumentation_generator import TDDInstrumentationGenerator
from tdd_instrumentation_validator import TDDInstrumentationValidator
from tdd_instrumentation_evaluator import TDDInstrumentationEvaluator, TDDEvaluator
from tdd_task_rewriter import TDDTaskRewriter
from llm_caller import call_openai_api_json_async


class TDDInstrumentationPostProcessor:
    """
    独立的instrumentation后处理器
    在已生成的网站基础上添加桩变量并生成evaluators
    """

    def __init__(self, website_dir: str, config: Dict[str, Any] = None):
        """
        Args:
            website_dir: 生成网站的目录（包含business_logic.js等文件）
            config: 可选配置，支持 stage_configs 为各组件独立配置模型
        """
        self.website_dir = website_dir
        self.config = config or self._default_config()

        # 初始化logger
        logs_dir = os.path.join(website_dir, "logs", "instrumentation")
        os.makedirs(logs_dir, exist_ok=True)
        self.logger = TDDLogger(output_dir=logs_dir, log_level="INFO")

        # 获取各组件的配置
        analyzer_config = self._get_component_config("instrumentation_analyzer")
        generator_config = self._get_component_config("instrumentation_generator")
        validator_config = self._get_component_config("instrumentation_validator")
        evaluator_config = self._get_component_config("instrumentation_evaluator")
        task_rewriter_config = self._get_component_config("task_rewriter")

        # 初始化各个组件
        self.analyzer = TDDInstrumentationAnalyzer(
            self.logger,
            reasoning_effort=analyzer_config["reasoning_effort"],
            model=analyzer_config["model"]
        )
        self.generator = TDDInstrumentationGenerator(
            self.logger,
            reasoning_effort=generator_config["reasoning_effort"],
            model=generator_config["model"]
        )
        self.validator = TDDInstrumentationValidator(
            self.logger,
            max_fix_iterations=self.config.get("max_fix_iterations", 3),
            reasoning_effort=validator_config["reasoning_effort"],
            model=validator_config["model"]
        )
        self.evaluator_generator = TDDInstrumentationEvaluator(
            self.logger,
            reasoning_effort=evaluator_config["reasoning_effort"],
            model=evaluator_config["model"]
        )
        self.task_rewriter = TDDTaskRewriter(
            self.logger,
            model=task_rewriter_config["model"],
            reasoning_effort=task_rewriter_config["reasoning_effort"]
        )

    def _default_config(self) -> Dict[str, Any]:
        return {
            "max_tokens": 16000,
            "max_fix_iterations": 3,
            "test_data_limit": 3,  # 使用前3条数据作为测试数据
            "reasoning_effort": "medium",
            "model": None
        }

    def _get_component_config(self, component_name: str) -> Dict[str, Any]:
        """
        获取指定组件的配置（model, reasoning_effort）

        支持两种配置格式（按优先级）：
        1. stage_configs 字典: stage_configs.{component_name}.model / reasoning_effort
        2. 全局配置: config.model / config.reasoning_effort

        Args:
            component_name: 组件名称 (如 "instrumentation_analyzer", "task_rewriter")

        Returns:
            包含 model 和 reasoning_effort 的字典
        """
        # 优先级1: 从 stage_configs 读取
        stage_configs = self.config.get("stage_configs", {})
        if component_name in stage_configs:
            stage_config = stage_configs[component_name]
            return {
                "model": stage_config.get("model") or self.config.get("model"),
                "reasoning_effort": stage_config.get("reasoning_effort") or self.config.get("reasoning_effort", "medium")
            }

        # 优先级2: 回退到全局配置
        return {
            "model": self.config.get("model"),
            "reasoning_effort": self.config.get("reasoning_effort", "medium")
        }

    def _smoke_test_evaluator(self, evaluation_logic: str) -> Dict[str, Any]:
        """Run evaluator code in Node.js with empty localStorage, check it returns a number."""
        test_js = """
const storage = {};
const localStorage = {
    getItem: (k) => storage[k] || null,
    setItem: (k, v) => { storage[k] = v; },
    clear: () => { for (const k in storage) delete storage[k]; },
    removeItem: (k) => { delete storage[k]; },
    get length() { return Object.keys(storage).length; },
    key: (i) => Object.keys(storage)[i] || null
};

try {
    const result = (function() { EVAL_CODE })();
    if (typeof result !== 'number') {
        console.log(JSON.stringify({ok: false, error: 'returned ' + typeof result + ': ' + JSON.stringify(result)}));
    } else {
        console.log(JSON.stringify({ok: true, value: result}));
    }
} catch (err) {
    console.log(JSON.stringify({ok: false, error: err.message}));
}
""".replace("EVAL_CODE", evaluation_logic)

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as tf:
                tf.write(test_js)
                tf_path = tf.name
            result = subprocess.run(['node', tf_path], capture_output=True, text=True, timeout=5)
            os.unlink(tf_path)
            stdout = result.stdout.strip()
            if stdout:
                return json.loads(stdout)
            return {"ok": False, "error": result.stderr.strip()[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _auto_fix_evaluator_logic(self, code: str) -> str:
        """Attempt deterministic fixes for common evaluator bugs."""
        # Fix 1: Variable name typos in reduce/push calls
        code = re.sub(r'\bcheckoints\b', 'checkpoints', code)
        code = re.sub(r'\bchecklists\b', 'checkpoints', code)
        code = re.sub(r'\bcheckponts\b', 'checkpoints', code)
        code = re.sub(r'\bcheckposts\b', 'checkpoints', code)
        code = re.sub(r'\bcheckpoin\b', 'checkpoints', code)
        code = re.sub(r'\bcheckPoints\b', 'checkpoints', code)

        # Fix 2: Placeholder arrow function → proper reduce
        # Pattern: return <anything> => 0; // placeholder
        code = re.sub(
            r'return\s+\w+\s*=>\s*0\s*;?\s*(//.*)?$',
            'return checkpoints.reduce((sum, cp) => sum + (cp.passed ? cp.weight : 0), 0);',
            code,
            flags=re.MULTILINE
        )

        # Fix 3: return true/false → reduce
        if code.rstrip().endswith('return true;') or code.rstrip().endswith('return false;'):
            code = re.sub(
                r'return\s+(true|false)\s*;\s*$',
                'return checkpoints.reduce((sum, cp) => sum + (cp.passed ? cp.weight : 0), 0);',
                code,
                flags=re.MULTILINE
            )

        return code

    async def _llm_fix_evaluator(self, ev, error_message: str) -> str:
        """Use LLM to fix evaluator code based on the smoke test error."""
        prompt = f"""Fix the JavaScript evaluator code below. It must return a NUMBER between 0.0 and 1.0.

ERROR from running the code:
{error_message}

CURRENT CODE:
```javascript
{ev.evaluation_logic}
```

RULES:
1. Use the checkpoint-based scoring pattern
2. The code MUST end with: return checkpoints.reduce((sum, cp) => sum + (cp.passed ? cp.weight : 0), 0);
3. Checkpoint weights must sum to 1.0
4. Do NOT return a boolean, arrow function, or anything other than a number
5. Fix only the bug — keep all business logic unchanged

Return JSON: {{"evaluation_logic": "// fixed JavaScript code"}}"""

        try:
            evaluator_config = self._get_component_config("instrumentation_evaluator")
            result, _ = await call_openai_api_json_async(
                [{"role": "user", "content": prompt}],
                reasoning_effort="low",
                model=evaluator_config["model"]
            )
            if isinstance(result, str):
                result = json.loads(result)
            return result.get("evaluation_logic", ev.evaluation_logic)
        except Exception as e:
            self.logger.log_error(f"  LLM fix failed: {e}")
            return ev.evaluation_logic

    async def _validate_evaluators(self, evaluators, business_logic_code, tasks, test_data):
        """Smoke-test evaluators in Node.js, auto-fix with regex then LLM if needed."""
        regex_fixed = 0
        llm_fixed = 0
        unfixable = []

        for ev in evaluators:
            result = self._smoke_test_evaluator(ev.evaluation_logic)
            if result.get("ok"):
                continue

            error_msg = result.get('error', 'unknown')
            self.logger.log_warning(
                f"Evaluator {ev.task_id} smoke test failed: {error_msg}. Attempting fix..."
            )

            # Step 1: Try deterministic regex fix
            fixed_code = self._auto_fix_evaluator_logic(ev.evaluation_logic)
            if fixed_code != ev.evaluation_logic:
                retest = self._smoke_test_evaluator(fixed_code)
                if retest.get("ok"):
                    ev.evaluation_logic = fixed_code
                    regex_fixed += 1
                    self.logger.log_info(f"  Auto-fixed {ev.task_id} (regex)")
                    continue

            # Step 2: Try LLM incremental fix
            llm_code = await self._llm_fix_evaluator(ev, error_msg)
            if llm_code != ev.evaluation_logic:
                retest = self._smoke_test_evaluator(llm_code)
                if retest.get("ok"):
                    ev.evaluation_logic = llm_code
                    llm_fixed += 1
                    self.logger.log_info(f"  Auto-fixed {ev.task_id} (LLM)")
                    continue

            unfixable.append(ev.task_id)
            self.logger.log_error(f"  Could not fix {ev.task_id}")

        total_fixed = regex_fixed + llm_fixed
        if total_fixed > 0:
            self.logger.log_info(f"Fixed {total_fixed} evaluator(s): {regex_fixed} regex, {llm_fixed} LLM")
        if unfixable:
            self.logger.log_warning(f"{len(unfixable)} evaluator(s) unfixable: {unfixable}")

        return evaluators

    async def process(self) -> Dict[str, Any]:
        """
        主处理流程

        Returns:
            处理结果字典
        """
        self.logger.log_info("=" * 80)
        self.logger.log_info("🚀 Starting TDD Instrumentation Post-Processing")
        self.logger.log_info(f"📁 Website Directory: {self.website_dir}")
        self.logger.log_info("=" * 80)

        try:
            # Step 0: 加载输入文件
            self.logger.log_info("\n📂 Step 0: Loading input files...")
            input_data = self._load_input_files()

            # Step 1: 分析桩变量需求
            self.logger.log_info("\n🔍 Step 1: Analyzing instrumentation requirements...")
            instrumentation_plan = await self.analyzer.analyze_requirements(
                tasks=input_data["tasks"],
                business_logic_code=input_data["business_logic_code"],
                datadict=input_data["datadict"]
            )

            # 保存instrumentation plan（用于调试）
            self._save_instrumentation_plan(instrumentation_plan)
            self.logger.log_info(f"✅ Identified instrumentation needs for {len(instrumentation_plan.requirements)} tasks")

            # 检查是否需要instrumentation
            if not instrumentation_plan.has_instrumentation_needs():
                self.logger.log_info("ℹ️ No instrumentation needed - existing variables sufficient")

                # 即使不需要instrumentation，也要重写任务以匹配数据
                self.logger.log_info("\n🔄 Rewriting tasks to match actual generated data...")

                # 加载完整的website_data用于任务重写
                website_data_path = os.path.join(self.website_dir, "website_data.json")
                with open(website_data_path, 'r', encoding='utf-8') as f:
                    full_website_data = json.load(f)

                # 重写任务
                rewritten_tasks = await self.task_rewriter.rewrite_tasks(
                    original_tasks=input_data["tasks"],
                    website_data=full_website_data,
                    datadict=input_data["datadict"],
                    include_full_data=self.config.get("task_rewriting", {}).get("include_full_data", True)
                )

                # 保存原始和重写后的任务
                self._save_original_tasks(input_data["tasks"])
                self._save_rewritten_tasks(rewritten_tasks)

                # 更新input_data使用重写后的任务
                input_data["tasks"] = rewritten_tasks
                self.logger.log_info(f"✅ Successfully rewrote {len(rewritten_tasks)} tasks")

                # 仍然生成evaluators，但基于现有变量和重写后的任务
                evaluators = await self.evaluator_generator.generate_evaluators(
                    tasks=input_data["tasks"],  # 重写后的任务
                    instrumentation_plan=instrumentation_plan,
                    datadict=input_data["datadict"],
                    static_data_types=input_data["static_data_types"],
                    business_logic_code=input_data["business_logic_code"],
                    test_data=input_data["test_data"],  # 测试数据（前3条）
                    website_data=full_website_data  # 添加完整的website数据
                )
                evaluators = await self._validate_evaluators(
                    evaluators, input_data["business_logic_code"],
                    input_data["tasks"], input_data["test_data"]
                )
                self._save_evaluators(evaluators, input_data["static_data_types"])

                return {
                    "success": True,
                    "instrumentation_plan": instrumentation_plan,
                    "validation_result": {"success": True, "message": "No instrumentation needed"},
                    "evaluators_count": len(evaluators)
                }

            # Step 2: 生成桩代码
            self.logger.log_info("\n🛠️ Step 2: Generating instrumented code...")
            instrumented_code = await self.generator.generate(
                instrumentation_plan=instrumentation_plan,
                original_code=input_data["business_logic_code"],
                test_data=input_data["test_data"]
            )

            # Step 3: 验证桩代码（只验证原始功能未破坏）
            self.logger.log_info("\n✅ Step 3: Validating instrumentation preserves original functionality...")
            validated_code, validation_result = await self.validator.validate_and_fix(
                instrumented_code=instrumented_code,
                original_tests=input_data["original_tests"],
                test_data=input_data["test_data"]
            )

            if validation_result.success:
                self.logger.log_info(f"✅ Instrumentation validated - original functionality preserved")
                # 保存instrumented代码
                self._save_instrumented_code(validated_code)
            else:
                # 验证失败：恢复原状，不保存插桩代码
                self.logger.log_error(f"❌ Instrumentation validation failed: {validation_result.message}")
                self._restore_original_code()

                return {
                    "success": False,
                    "instrumentation_plan": instrumentation_plan,
                    "validation_result": validation_result.to_dict(),
                    "error": f"Validation failed: {validation_result.message}",
                    "evaluators_count": 0
                }

            # Step 3.5: 重写任务以匹配实际数据
            self.logger.log_info("\n🔄 Step 3.5: Rewriting tasks to match actual generated data...")

            # 加载完整的website_data用于任务重写
            website_data_path = os.path.join(self.website_dir, "website_data.json")
            with open(website_data_path, 'r', encoding='utf-8') as f:
                full_website_data = json.load(f)

            # 重写任务
            rewritten_tasks = await self.task_rewriter.rewrite_tasks(
                original_tasks=input_data["tasks"],
                website_data=full_website_data,
                datadict=input_data["datadict"],
                include_full_data=self.config.get("task_rewriting", {}).get("include_full_data", True)
            )

            # 验证重写的任务
            is_valid, issues = self.task_rewriter.validate_rewritten_tasks(
                rewritten_tasks,
                full_website_data
            )

            if not is_valid:
                self.logger.log_warning(f"Task rewriting validation issues: {issues}")

            # 保存原始和重写后的任务
            self._save_original_tasks(input_data["tasks"])
            self._save_rewritten_tasks(rewritten_tasks)

            # 更新input_data使用重写后的任务
            input_data["tasks"] = rewritten_tasks
            self.logger.log_info(f"✅ Successfully rewrote {len(rewritten_tasks)} tasks to match actual data")

            # Step 4: 生成evaluators（使用重写后的任务）
            self.logger.log_info("\n📝 Step 4: Generating evaluators with rewritten tasks...")
            evaluators = await self.evaluator_generator.generate_evaluators(
                tasks=input_data["tasks"],  # 现在是重写后的任务
                instrumentation_plan=instrumentation_plan,
                datadict=input_data["datadict"],
                static_data_types=input_data["static_data_types"],
                business_logic_code=input_data["business_logic_code"],
                test_data=input_data["test_data"],  # 测试数据（前3条）
                website_data=full_website_data  # 添加完整的website数据
            )

            # Step 5: 验证evaluators
            evaluators = await self._validate_evaluators(
                evaluators, validated_code,
                input_data["tasks"], input_data["test_data"]
            )

            # 保存evaluators
            self._save_evaluators(evaluators, input_data["static_data_types"])

            self.logger.log_info("\n" + "=" * 80)
            self.logger.log_info(f"✨ Instrumentation Post-Processing Complete!")
            self.logger.log_info(f"✅ Generated {len(evaluators)} evaluators")
            self.logger.log_info(f"📁 Updated files saved to: {self.website_dir}")
            self.logger.log_info("=" * 80)

            return {
                "success": True,
                "instrumentation_plan": instrumentation_plan,
                "code_validation_result": validation_result.to_dict(),
                "evaluators_count": len(evaluators)
            }

        except Exception as e:
            self.logger.log_exception(e, "Instrumentation Post-Processing")
            return {
                "success": False,
                "error": str(e)
            }

    def _load_input_files(self) -> Dict[str, Any]:
        """加载所有输入文件"""
        # 1. 加载tasks
        tasks_path = os.path.join(self.website_dir, "data", "tasks.json")
        if not os.path.exists(tasks_path):
            raise FileNotFoundError(f"tasks.json not found at {tasks_path}")

        with open(tasks_path, 'r', encoding='utf-8') as f:
            tasks_data = json.load(f)
            tasks = tasks_data["tasks"]

        # 2. 加载datadict (data_models.json)
        datadict_path = os.path.join(self.website_dir, "data", "data_models.json")
        if not os.path.exists(datadict_path):
            raise FileNotFoundError(f"data_models.json not found at {datadict_path}")

        with open(datadict_path, 'r', encoding='utf-8') as f:
            datadict = json.load(f)

        # 3. 加载business_logic.js
        business_logic_path = os.path.join(self.website_dir, "business_logic.js")
        if not os.path.exists(business_logic_path):
            raise FileNotFoundError(f"business_logic.js not found at {business_logic_path}")

        with open(business_logic_path, 'r', encoding='utf-8') as f:
            business_logic_code = f.read()

        # 4. 加载原始测试 (test_flows.js)
        original_tests_path = os.path.join(self.website_dir, "test_flows.js")
        if not os.path.exists(original_tests_path):
            raise FileNotFoundError(f"test_flows.js not found at {original_tests_path}")

        with open(original_tests_path, 'r', encoding='utf-8') as f:
            original_tests = f.read()

        # 5. 加载website_data.json并提取前N条作为测试数据
        website_data_path = os.path.join(self.website_dir, "website_data.json")
        if not os.path.exists(website_data_path):
            raise FileNotFoundError(f"website_data.json not found at {website_data_path}")

        with open(website_data_path, 'r', encoding='utf-8') as f:
            full_data = json.load(f)

        # 提取前N条数据
        test_data = self._extract_limited_test_data(
            full_data,
            limit=self.config.get("test_data_limit", 3)
        )

        # 提取static_data_types
        static_data_types = list(full_data.keys())

        self.logger.log_info(f"✅ Loaded tasks: {len(tasks)}")
        self.logger.log_info(f"✅ Loaded datadict entities: {len(datadict.get('entities', []))}")
        self.logger.log_info(f"✅ Loaded business logic: {len(business_logic_code)} characters")
        self.logger.log_info(f"✅ Loaded original tests: {len(original_tests)} characters")
        self.logger.log_info(f"✅ Prepared test data: {len(test_data)} entity types")

        return {
            "tasks": tasks,
            "datadict": datadict,
            "business_logic_code": business_logic_code,
            "original_tests": original_tests,
            "test_data": test_data,
            "static_data_types": static_data_types
        }

    def _extract_limited_test_data(self, full_data: Dict, limit: int) -> Dict:
        """提取每个entity的前N条数据"""
        limited_data = {}
        for entity_type, items in full_data.items():
            if isinstance(items, list):
                limited_data[entity_type] = items[:limit]
            else:
                limited_data[entity_type] = items
        return limited_data

    def _save_instrumentation_plan(self, plan):
        """保存instrumentation plan（调试用）"""
        plan_path = os.path.join(self.website_dir, "instrumentation_plan.json")
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan.to_dict(), f, indent=2, ensure_ascii=False)
        self.logger.log_info(f"💾 Saved instrumentation plan to instrumentation_plan.json")

    def _save_instrumented_code(self, code: str):
        """保存instrumented代码（覆盖原文件）"""
        # 备份原始文件
        business_logic_path = os.path.join(self.website_dir, "business_logic.js")
        backup_path = os.path.join(self.website_dir, "business_logic.js.backup")

        if os.path.exists(business_logic_path):
            with open(business_logic_path, 'r', encoding='utf-8') as f:
                original = f.read()
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original)
            self.logger.log_info(f"💾 Backed up original to business_logic.js.backup")

        # 保存新代码
        with open(business_logic_path, 'w', encoding='utf-8') as f:
            f.write(code)

        self.logger.log_info(f"💾 Saved instrumented code to business_logic.js")

    def _save_evaluators(self, evaluators, static_data_types):
        """保存evaluators到JSON"""
        evaluators_path = os.path.join(self.website_dir, "evaluators.json")
        evaluators_data = {
            "evaluators": [e.to_dict() for e in evaluators],
            "static_data_types": static_data_types,
            "instrumentation_based": True
        }
        with open(evaluators_path, 'w', encoding='utf-8') as f:
            json.dump(evaluators_data, f, indent=2, ensure_ascii=False)

        self.logger.log_info(f"💾 Saved {len(evaluators)} evaluators to evaluators.json")

    def _restore_original_code(self):
        """
        当验证失败时，恢复原始代码并清理插桩文件
        用于 Max iterations reached 等验证失败场景
        """
        business_logic_path = os.path.join(self.website_dir, "business_logic.js")
        backup_path = os.path.join(self.website_dir, "business_logic.js.backup")

        # 如果存在 backup，从 backup 恢复
        if os.path.exists(backup_path):
            with open(backup_path, 'r', encoding='utf-8') as f:
                original = f.read()
            with open(business_logic_path, 'w', encoding='utf-8') as f:
                f.write(original)
            # 删除 backup 文件
            os.remove(backup_path)
            self.logger.log_info(f"✅ Restored original business_logic.js from backup")

        # 删除 instrumentation plan
        plan_path = os.path.join(self.website_dir, "instrumentation_plan.json")
        if os.path.exists(plan_path):
            os.remove(plan_path)
            self.logger.log_info(f"🗑️  Removed instrumentation_plan.json")

    # ========== 批处理相关方法 ==========

    @staticmethod
    def _discover_websites(batch_dir: str) -> list:
        """
        发现批次文件夹中的所有网站文件夹

        Args:
            batch_dir: 批次文件夹路径

        Returns:
            有效的网站目录列表
        """
        websites = []

        if not os.path.exists(batch_dir):
            print(f"❌ Error: Batch directory not found: {batch_dir}")
            return websites

        # 遍历批次文件夹中的所有子文件夹
        for item in sorted(os.listdir(batch_dir)):
            item_path = os.path.join(batch_dir, item)

            # 跳过文件，只处理文件夹
            if not os.path.isdir(item_path):
                continue

            # 验证是否包含必需文件
            required_files = [
                os.path.join(item_path, "data", "tasks.json"),
                os.path.join(item_path, "business_logic.js"),
                os.path.join(item_path, "test_flows.js"),
                os.path.join(item_path, "website_data.json")
            ]

            if all(os.path.exists(f) for f in required_files):
                websites.append(item_path)
            else:
                print(f"⚠️ Skipping {item} (missing required files)")

        return websites

    async def _process_single_async(
        self,
        website_dir: str,
        semaphore: asyncio.Semaphore,
        status_lock: asyncio.Lock,
        status_dict: Dict,
        idx: int
    ) -> Dict[str, Any]:
        """
        异步处理单个网站

        Args:
            website_dir: 网站目录路径
            semaphore: 并发控制信号量
            status_lock: 状态字典的锁
            status_dict: 共享状态字典
            idx: 网站索引

        Returns:
            处理结果字典
        """
        website_name = os.path.basename(website_dir)

        async with semaphore:
            # 更新状态为"处理中"
            async with status_lock:
                status_dict[website_name] = {"status": "processing", "index": idx}

            try:
                # 创建新的处理器实例（使用相同的配置）
                processor = TDDInstrumentationPostProcessor(website_dir, self.config)

                # 执行处理
                result = await processor.process()

                # 更新状态
                async with status_lock:
                    if result["success"]:
                        status_dict[website_name] = {
                            "status": "success",
                            "index": idx,
                            "evaluators_count": result.get("evaluators_count", 0)
                        }
                    else:
                        status_dict[website_name] = {
                            "status": "failed",
                            "index": idx,
                            "error": result.get("error", "Unknown error")
                        }

                return {
                    "website_name": website_name,
                    "website_dir": website_dir,
                    **result
                }

            except Exception as e:
                # 更新状态为"失败"
                async with status_lock:
                    status_dict[website_name] = {
                        "status": "failed",
                        "index": idx,
                        "error": str(e)
                    }

                return {
                    "website_name": website_name,
                    "website_dir": website_dir,
                    "success": False,
                    "error": str(e)
                }

    async def _print_status(self, status_dict: Dict, status_lock: asyncio.Lock):
        """
        定期打印处理状态

        Args:
            status_dict: 状态字典
            status_lock: 状态字典的锁
        """
        while True:
            await asyncio.sleep(10)  # 每10秒打印一次

            async with status_lock:
                if not status_dict:
                    continue

                success = sum(1 for v in status_dict.values() if v.get("status") == "success")
                failed = sum(1 for v in status_dict.values() if v.get("status") == "failed")
                processing = sum(1 for v in status_dict.values() if v.get("status") == "processing")
                total = len(status_dict)

                print(f"\n{'='*60}")
                print(f"📊 Progress: {success + failed}/{total} completed")
                print(f"   ✅ Success: {success} | ❌ Failed: {failed} | 🔄 Processing: {processing}")
                print(f"{'='*60}\n")

    def _save_original_tasks(self, tasks: list):
        """
        保存原始任务到文件

        Args:
            tasks: 原始任务列表
        """
        try:
            # 创建保存路径
            original_tasks_path = os.path.join(self.website_dir, "original_tasks.json")

            # 保存原始任务
            with open(original_tasks_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "description": "Original tasks before rewriting based on actual data",
                    "tasks": tasks
                }, f, indent=2, ensure_ascii=False)

            self.logger.log_info(f"💾 Saved original tasks to: {original_tasks_path}")

        except Exception as e:
            self.logger.log_error(f"Failed to save original tasks: {str(e)}")

    def _save_rewritten_tasks(self, tasks: list):
        """
        保存重写后的任务到文件

        Args:
            tasks: 重写后的任务列表
        """
        try:
            # 创建保存路径
            rewritten_tasks_path = os.path.join(self.website_dir, "rewritten_tasks.json")

            # 保存重写后的任务
            with open(rewritten_tasks_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "description": "Tasks rewritten to match actual generated data",
                    "tasks": tasks
                }, f, indent=2, ensure_ascii=False)

            self.logger.log_info(f"💾 Saved rewritten tasks to: {rewritten_tasks_path}")

        except Exception as e:
            self.logger.log_error(f"Failed to save rewritten tasks: {str(e)}")

    @staticmethod
    def _save_batch_results(batch_dir: str, results: list):
        """
        保存批次处理结果

        Args:
            batch_dir: 批次文件夹路径
            results: 处理结果列表
        """
        # 统计信息
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        failed = total - success

        # 构建结果数据
        batch_results = {
            "summary": {
                "total": total,
                "success": success,
                "failed": failed,
                "success_rate": f"{success/total*100:.1f}%" if total > 0 else "0%"
            },
            "results": []
        }

        # 添加每个网站的详细结果
        for result in results:
            website_result = {
                "website_name": result.get("website_name"),
                "website_dir": result.get("website_dir"),
                "success": result.get("success"),
            }

            if result.get("success"):
                website_result["evaluators_count"] = result.get("evaluators_count", 0)
            else:
                website_result["error"] = result.get("error", "Unknown error")

            batch_results["results"].append(website_result)

        # 保存到文件
        results_path = os.path.join(batch_dir, "batch_instrumentation_results.json")
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump(batch_results, f, indent=2, ensure_ascii=False)

        print(f"\n💾 Saved batch results to: {results_path}")

    async def process_batch(self, batch_dir: str, max_concurrent: int = 3, limit: int = None) -> Dict[str, Any]:
        """
        批量处理多个网站

        Args:
            batch_dir: 批次文件夹路径（包含多个网站文件夹）
            max_concurrent: 最大并发数
            limit: 限制处理数量（可选）

        Returns:
            批次处理结果
        """
        print("=" * 80)
        print("🚀 Starting Batch Instrumentation Post-Processing")
        print(f"📁 Batch Directory: {batch_dir}")
        print(f"⚙️  Max Concurrent: {max_concurrent}")
        print("=" * 80)

        # 发现所有网站文件夹
        websites = self._discover_websites(batch_dir)

        if not websites:
            print("❌ No valid website folders found in batch directory")
            return {
                "success": False,
                "error": "No valid website folders found"
            }

        # 应用限制
        if limit and limit > 0:
            websites = websites[:limit]
            print(f"ℹ️ Processing limited to first {limit} websites")

        print(f"\n✅ Found {len(websites)} valid website(s) to process\n")

        # 创建并发控制
        semaphore = asyncio.Semaphore(max_concurrent)
        status_lock = asyncio.Lock()
        status_dict = {}

        # 创建状态打印任务
        status_task = asyncio.create_task(self._print_status(status_dict, status_lock))

        # 创建所有处理任务
        tasks = []
        for idx, website_dir in enumerate(websites):
            task = self._process_single_async(
                website_dir, semaphore, status_lock, status_dict, idx
            )
            tasks.append(task)

        # 并发执行所有任务
        results = await asyncio.gather(*tasks)

        # 取消状态打印任务
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass

        # 保存批次结果
        self._save_batch_results(batch_dir, results)

        # 统计结果
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        failed = total - success

        print("\n" + "=" * 80)
        print("✨ Batch Instrumentation Post-Processing Complete!")
        print(f"📊 Total: {total} | ✅ Success: {success} | ❌ Failed: {failed}")
        print(f"📁 Results saved to: {batch_dir}")
        print("=" * 80)

        return {
            "success": True,
            "batch_dir": batch_dir,
            "total": total,
            "success_count": success,
            "failed_count": failed,
            "results": results
        }

    # ========== Resume 相关方法 ==========

    @staticmethod
    def _find_failed_websites(batch_dir: str) -> list:
        """
        从批次结果文件中找到失败的网站

        Args:
            batch_dir: 批次文件夹路径

        Returns:
            失败的网站目录列表
        """
        results_file = os.path.join(batch_dir, "batch_instrumentation_results.json")

        if not os.path.exists(results_file):
            print(f"❌ Error: No batch_instrumentation_results.json found in {batch_dir}")
            print(f"   This directory may not have been processed yet.")
            return []

        try:
            with open(results_file, 'r', encoding='utf-8') as f:
                results = json.load(f)

            # 提取失败的网站
            failed_websites = []
            for result in results.get("results", []):
                if not result.get("success", False):
                    website_dir = result.get("website_dir")
                    if website_dir and os.path.exists(website_dir):
                        failed_websites.append(website_dir)

            return failed_websites

        except Exception as e:
            print(f"❌ Error reading batch results: {e}")
            return []

    def _cleanup_instrumentation_files(self, website_dir: str):
        """
        清理失败网站的插桩相关文件，准备重新处理

        Args:
            website_dir: 网站目录路径
        """
        files_to_remove = [
            "instrumentation_tests.js",
            "instrumentation_plan.json",
            "business_logic.js.backup",
            "evaluators.json"  # 如果存在但失败了，也需要删除
        ]

        for filename in files_to_remove:
            file_path = os.path.join(website_dir, filename)
            if os.path.exists(file_path):
                os.remove(file_path)

    def _update_batch_results(self, batch_dir: str, retry_results: list):
        """
        更新批次结果文件，合并重试结果

        Args:
            batch_dir: 批次文件夹路径
            retry_results: 重试结果列表
        """
        results_file = os.path.join(batch_dir, "batch_instrumentation_results.json")

        # 读取原有结果
        with open(results_file, 'r', encoding='utf-8') as f:
            batch_results = json.load(f)

        # 创建网站目录到重试结果的映射
        retry_map = {
            r["website_dir"]: r for r in retry_results
        }

        # 更新结果
        for i, result in enumerate(batch_results["results"]):
            website_dir = result.get("website_dir")
            if website_dir in retry_map:
                # 更新为新的结果
                retry_result = retry_map[website_dir]
                batch_results["results"][i] = {
                    "website_name": result["website_name"],
                    "website_dir": website_dir,
                    "success": retry_result.get("success"),
                }

                if retry_result.get("success"):
                    batch_results["results"][i]["evaluators_count"] = retry_result.get("evaluators_count", 0)
                else:
                    batch_results["results"][i]["error"] = retry_result.get("error", "Unknown error")

        # 重新计算统计信息
        total = len(batch_results["results"])
        success = sum(1 for r in batch_results["results"] if r.get("success"))
        failed = total - success

        batch_results["summary"] = {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": f"{success/total*100:.1f}%" if total > 0 else "0%"
        }

        # 保存更新后的结果
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(batch_results, f, indent=2, ensure_ascii=False)

        print(f"\n💾 Updated batch results: {results_file}")

    async def process_failed_websites(
        self,
        failed_websites: list,
        batch_dir: str,
        max_concurrent: int = 3
    ) -> Dict[str, Any]:
        """
        重新处理失败的网站（resume 模式）

        Args:
            failed_websites: 失败的网站目录列表
            batch_dir: 批次文件夹路径
            max_concurrent: 最大并发数

        Returns:
            处理结果
        """
        print("=" * 80)
        print("🔄 Retry Processing Failed Websites")
        print(f"📁 Batch Directory: {batch_dir}")
        print(f"⚙️  Max Concurrent: {max_concurrent}")
        print(f"📋 Total Failed: {len(failed_websites)}")
        print("=" * 80)

        # 为每个失败的网站清理插桩相关文件
        print("\n🗑️  Cleaning up instrumentation files from previous attempts...")
        for website_dir in failed_websites:
            self._cleanup_instrumentation_files(website_dir)
        print("✅ Cleanup complete\n")

        # 创建并发控制
        semaphore = asyncio.Semaphore(max_concurrent)
        status_lock = asyncio.Lock()
        status_dict = {}

        # 创建状态打印任务
        status_task = asyncio.create_task(self._print_status(status_dict, status_lock))

        # 创建所有处理任务
        tasks = []
        for idx, website_dir in enumerate(failed_websites):
            task = self._process_single_async(
                website_dir, semaphore, status_lock, status_dict, idx
            )
            tasks.append(task)

        # 并发执行所有任务
        results = await asyncio.gather(*tasks)

        # 取消状态打印任务
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass

        # 更新批次结果文件
        self._update_batch_results(batch_dir, results)

        # 统计结果
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        failed = total - success

        print("\n" + "=" * 80)
        print("✨ Retry Processing Complete!")
        print(f"📊 Total: {total} | ✅ Success: {success} | ❌ Failed: {failed}")
        if failed > 0:
            print(f"💡 Tip: You can run --resume again to retry the {failed} failed website(s)")
        print(f"📁 Updated results in: {batch_dir}")
        print("=" * 80)

        return {
            "success": True,
            "batch_dir": batch_dir,
            "total": total,
            "success_count": success,
            "failed_count": failed,
            "results": results
        }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="TDD Instrumentation Post-Processor - Add instrumentation and generate evaluators"
    )

    # 目录参数（互斥：单个网站 vs 批次处理 vs resume）
    dir_group = parser.add_mutually_exclusive_group(required=True)
    dir_group.add_argument(
        "--website-dir",
        type=str,
        help="Path to single website directory"
    )
    dir_group.add_argument(
        "--batch-dir",
        type=str,
        help="Path to batch directory containing multiple website folders"
    )
    dir_group.add_argument(
        "--resume",
        type=str,
        help="Resume from previous batch by processing only failed websites (specify batch directory path)"
    )

    # 配置参数
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=32000,
        help="Maximum tokens for LLM calls (default: 16000)"
    )
    parser.add_argument(
        "--max-fix-iterations",
        type=int,
        default=5,
        help="Maximum fix iterations for validation (default: 3)"
    )
    parser.add_argument(
        "--test-data-limit",
        type=int,
        default=3,
        help="Number of data items to use for testing (default: 3)"
    )

    # 批处理参数
    parser.add_argument(
        "--concurrent",
        type=int,
        default=3,
        help="Maximum concurrent processing for batch mode (default: 3)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of websites to process in batch mode (optional)"
    )

    # LLM 参数
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default="minimal",
        choices=["minimal", "low", "medium", "high"],
        help="Reasoning effort level for LLM calls (default: medium)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5.1",
        help="Model name to use for LLM calls (default: None, uses default model)"
    )

    args = parser.parse_args()

    # 构建配置
    config = {
        "max_tokens": args.max_tokens,
        "max_fix_iterations": args.max_fix_iterations,
        "test_data_limit": args.test_data_limit,
        "reasoning_effort": args.reasoning_effort,
        "model": args.model
    }

    # 判断是单个网站处理还是批处理
    if args.website_dir:
        # 单个网站处理模式
        if not os.path.exists(args.website_dir):
            print(f"❌ Error: Website directory not found: {args.website_dir}")
            return 1

        # 运行单个网站处理
        processor = TDDInstrumentationPostProcessor(args.website_dir, config)
        result = asyncio.run(processor.process())

        if result["success"]:
            print("\n✅ Instrumentation post-processing completed successfully!")
            return 0
        else:
            print(f"\n❌ Instrumentation post-processing failed: {result.get('error')}")
            return 1

    elif args.batch_dir:
        # 批处理模式
        if not os.path.exists(args.batch_dir):
            print(f"❌ Error: Batch directory not found: {args.batch_dir}")
            return 1

        # 创建临时处理器实例（用于调用批处理方法）
        # 注意：website_dir 在批处理时不使用，仅为满足__init__要求
        temp_processor = TDDInstrumentationPostProcessor(args.batch_dir, config)

        # 运行批处理
        result = asyncio.run(
            temp_processor.process_batch(
                args.batch_dir,
                max_concurrent=args.concurrent,
                limit=args.limit
            )
        )

        if result["success"]:
            return 0
        else:
            print(f"\n❌ Batch processing failed: {result.get('error')}")
            return 1

    elif args.resume:
        # Resume 模式：重新处理失败的网站
        if not os.path.exists(args.resume):
            print(f"❌ Error: Resume directory not found: {args.resume}")
            return 1

        print("=" * 80)
        print("🔄 Resume Mode: Processing Failed Websites")
        print(f"📁 Batch Directory: {args.resume}")
        print("=" * 80)

        # 创建临时处理器实例
        temp_processor = TDDInstrumentationPostProcessor(args.resume, config)

        # 发现失败的网站
        failed_websites = temp_processor._find_failed_websites(args.resume)

        if not failed_websites:
            print("\n✅ No failed websites found. All websites completed successfully!")
            return 0

        print(f"\n📋 Found {len(failed_websites)} failed website(s) to retry:\n")
        for i, website_dir in enumerate(failed_websites, 1):
            print(f"  {i}. {os.path.basename(website_dir)}")

        # 批量重新处理失败的网站
        print("\n" + "=" * 80)
        print(f"Starting retry processing (max {args.concurrent} concurrent)...")
        print("=" * 80 + "\n")

        result = asyncio.run(
            temp_processor.process_failed_websites(
                failed_websites,
                args.resume,
                max_concurrent=args.concurrent
            )
        )

        if result["success"]:
            return 0
        else:
            print(f"\n❌ Resume processing failed: {result.get('error')}")
            return 1

    return 1


if __name__ == "__main__":
    exit(main())
