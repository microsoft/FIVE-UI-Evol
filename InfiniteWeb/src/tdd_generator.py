"""
TDD Generator
Main controller for Task-Driven Development website generation
"""

import os
import sys
import json
import time
from typing import List, Dict, Any, Optional

# Import new modular components
from tdd_logger_module import TDDLogger
from tdd_data_manager import TDDDataManager, TDDTask, TDDGenerationResult
from tdd_config_manager import TDDConfigManager

# Import existing TDD components
from tdd_task_generator import TDDTaskGenerator
from tdd_primary_architecture_designer import TDDPrimaryArchitectureDesigner
from tdd_data_extractor import TDDDataExtractor
from tdd_interface_designer import TDDInterfaceDesigner
from tdd_parallel_generator import TDDParallelGenerator
from tdd_test_validator import TDDTestValidator
from tdd_architecture_designer import TDDArchitectureDesigner
from tdd_page_designer import TDDPageDesigner
from tdd_design_analyzer import TDDDesignAnalyzer
from tdd_layout_designer import TDDLayoutDesigner
from tdd_page_framework_generator import TDDPageFrameworkGenerator
from tdd_page_generator import TDDPageGenerator
from tdd_data_generator import TDDDataGenerator
from tdd_resource_replacer import TDDResourceReplacer
from tdd_data_injector import TDDDataInjector
from tdd_syntax_fixer import TDDSyntaxFixer
from tdd_instrumentation_post_processor import TDDInstrumentationPostProcessor
from tdd_token_tracker import get_token_tracker

# Import LLM caller configuration function
from llm_caller import configure_load_balancing


class TDDGenerator:
    """Main TDD Generator for website business logic"""
    
    def __init__(self, output_dir: Optional[str] = None, config_path: Optional[str] = None):
        """
        Initialize TDD Generator
        
        Args:
            output_dir: Directory to save generated files
            config_path: Optional path to configuration file
        """
        # Initialize configuration manager
        self.config_manager = TDDConfigManager(config_path)
        
        # Override output_dir if provided
        if output_dir:
            self.config_manager.set("output_dir", output_dir)
        
        self.output_dir = self.config_manager.get("output_dir")

        # Configure LLM caller with settings from config
        configure_load_balancing(
            endpoints=self.config_manager.get("endpoints"),
            strategy=self.config_manager.get("load_balance_strategy"),
            deployment=self.config_manager.get("deployment"),
            api_version=self.config_manager.get("api_version", "2025-03-01-preview")
        )
        
        # Initialize logger with config - logs go to logs subdirectory
        logs_dir = os.path.join(self.output_dir, "logs")
        self.logger = TDDLogger(
            output_dir=logs_dir,
            log_level=self.config_manager.get("log_level")
        )
        
        # Initialize data manager
        self.data_manager = TDDDataManager(self.output_dir)
        
        # Initialize components with logger and config
        max_pages = self.config_manager.get("max_pages", 8)

        # Get component-specific configs
        data_extractor_config = self.config_manager.get_component_config("data_extractor")
        parallel_generator_config = self.config_manager.get_component_config("parallel_generator")
        test_validator_config = self.config_manager.get_component_config("test_validator")
        framework_generator_config = self.config_manager.get_component_config("framework_generator")
        page_generator_config = self.config_manager.get_component_config("page_generator")
        data_generator_config = self.config_manager.get_component_config("data_generator")
        resource_replacer_config = self.config_manager.get_component_config("resource_replacer")
        syntax_fixer_config = self.config_manager.get_component_config("syntax_fixer")

        # Get configs for additional components
        task_generator_config = self.config_manager.get_component_config("task_generator")
        primary_architecture_config = self.config_manager.get_component_config("primary_architecture")
        interface_designer_config = self.config_manager.get_component_config("interface_designer")
        architecture_designer_config = self.config_manager.get_component_config("architecture_designer")
        page_designer_config = self.config_manager.get_component_config("page_designer")
        design_analyzer_config = self.config_manager.get_component_config("design_analyzer")
        layout_designer_config = self.config_manager.get_component_config("layout_designer")

        self.task_generator = TDDTaskGenerator(
            self.logger,
            model=task_generator_config["model"],
            reasoning_effort=task_generator_config["reasoning_effort"]
        )
        self.primary_architecture_designer = TDDPrimaryArchitectureDesigner(
            self.logger,
            max_pages=max_pages,
            model=primary_architecture_config["model"],
            reasoning_effort=primary_architecture_config["reasoning_effort"]
        )
        self.data_extractor = TDDDataExtractor(
            self.logger,
            model=data_extractor_config["model"],
            reasoning_effort=data_extractor_config["reasoning_effort"]
        )
        self.interface_designer = TDDInterfaceDesigner(
            self.logger,
            model=interface_designer_config["model"],
            reasoning_effort=interface_designer_config["reasoning_effort"]
        )
        self.parallel_generator = TDDParallelGenerator(
            self.logger,
            model=parallel_generator_config["model"],
            reasoning_effort=parallel_generator_config["reasoning_effort"]
        )
        self.test_validator = TDDTestValidator(
            self.logger,
            max_fix_iterations=self.config_manager.get("max_fix_iterations"),
            model=test_validator_config["model"],
            reasoning_effort=test_validator_config["reasoning_effort"]
        )
        self.architecture_designer = TDDArchitectureDesigner(
            self.logger,
            max_pages=self.config_manager.get("max_pages", 8),
            model=architecture_designer_config["model"],
            reasoning_effort=architecture_designer_config["reasoning_effort"]
        )
        self.page_designer = TDDPageDesigner(
            self.logger,
            max_concurrent=self.config_manager.get("max_concurrent", 3),
            model=page_designer_config["model"],
            reasoning_effort=page_designer_config["reasoning_effort"]
        )
        self.design_analyzer = TDDDesignAnalyzer(
            self.logger,
            model=design_analyzer_config["model"],
            reasoning_effort=design_analyzer_config["reasoning_effort"]
        )
        self.layout_designer = TDDLayoutDesigner(
            self.logger,
            max_concurrent=self.config_manager.get("max_concurrent", 3),
            model=layout_designer_config["model"],
            reasoning_effort=layout_designer_config["reasoning_effort"]
        )
        self.framework_generator = TDDPageFrameworkGenerator(
            self.logger,
            model=framework_generator_config["model"],
            reasoning_effort=framework_generator_config["reasoning_effort"]
        )
        self.page_generator = TDDPageGenerator(
            self.logger,
            max_concurrent=self.config_manager.get("max_concurrent", 3),
            model=page_generator_config["model"],
            reasoning_effort=page_generator_config["reasoning_effort"]
        )
        self.data_generator = TDDDataGenerator(
            self.logger,
            max_items=self.config_manager.get("max_data_items", 20),
            model=data_generator_config["model"],
            reasoning_effort=data_generator_config["reasoning_effort"]
        )
        self.resource_replacer = TDDResourceReplacer(
            self.logger,
            pexels_api_key=self.config_manager.get("pexels_api_key"),
            freesound_api_key=self.config_manager.get("freesound_api_key"),
            youtube_api_key=self.config_manager.get("youtube_api_key"),
            google_api_key=self.config_manager.get("google_api_key"),
            google_cse_cx=self.config_manager.get("google_cse_cx"),
            image_mode=self.config_manager.get("image_mode"),
            output_dir=self.config_manager.get("output_dir", "results/generated"),
            model=resource_replacer_config["model"],
            reasoning_effort=resource_replacer_config["reasoning_effort"],
            local_image_search_url=self.config_manager.get("local_image_search_url"),
            local_image_search_dataset=self.config_manager.get("local_image_search_dataset"),
            local_image_search_min_resolution=self.config_manager.get("local_image_search_min_resolution")
        )
        self.data_injector = TDDDataInjector(self.logger)

        # Syntax fixer with configurable model
        self.syntax_fixer = TDDSyntaxFixer(
            logger=self.logger,
            max_fix_iterations=self.config_manager.get("max_fix_iterations"),
            model=syntax_fixer_config["model"],
            reasoning_effort=syntax_fixer_config["reasoning_effort"]
        )
    
    async def _run_backend_pipeline(self, tasks, data_models, interfaces, website_type, logger):
        """
        Backend pipeline: Data generation, data image replacement, code generation, validation
        
        Args:
            logger: Independent logger instance for this pipeline
        """
        import asyncio
        import json
        
        # Step 4: Generate Website Data
        logger.log_step_start("Generate Website Data", "backend")
        logger.start_stage("Generate Data", "backend")
        logger.log_info("🗂️ Generating website data (before tests for consistency)...")
        
        # Get data models from data manager
        data_models_dict = self.data_manager.get_data_models_dict()

        # Prepare navigation links from primary architecture for ID consistency
        navigation_links = None
        if self.data_manager.primary_architecture:
            primary_arch = self.data_manager.primary_architecture
            navigation_links = {
                'header_links': getattr(primary_arch, 'header_links', []) or [],
                'footer_links': getattr(primary_arch, 'footer_links', []) or []
            }
            if navigation_links['header_links'] or navigation_links['footer_links']:
                logger.log_info(f"  📋 Using navigation links for ID consistency: {len(navigation_links['header_links'])} header, {len(navigation_links['footer_links'])} footer")

        # Generate concrete data
        generated_data = await self.data_generator.generate_data(
            data_models_dict,
            website_type,
            tasks,
            navigation_links=navigation_links
        )
        
        # Save generated data to file
        data_file_path = os.path.join(self.output_dir, "website_data.json")
        with open(data_file_path, 'w', encoding='utf-8') as f:
            json.dump(generated_data.static_data, f, indent=2, ensure_ascii=False)
        
        logger.log_info(f"  ✅ Saved website data to website_data.json")
        logger.log_info(f"✅ Successfully generated data for {len(generated_data.static_data)} entity types")
        logger.end_stage("Generate Data")
        logger.log_step_end("Generate Website Data", "backend")
        
        # Step 11: Replace Data Images
        logger.log_step_start("Replace Data Resources", "backend")
        logger.start_stage("Replace Data Resources", "backend")
        logger.log_info("🎯 Replacing resources in generated data...")
        data_resource_result = await self.resource_replacer.replace_data_resources(
            generated_data.static_data,
            website_type
        )
        
        # Update data with replaced resources
        generated_data.static_data = data_resource_result.updated_data
        
        # Save updated data
        with open(data_file_path, 'w', encoding='utf-8') as f:
            json.dump(generated_data.static_data, f, indent=2, ensure_ascii=False)
        
        logger.log_info(f"  ✅ Replaced {len(data_resource_result.replacements)} data resources")
        logger.end_stage("Replace Data Resources")
        logger.log_step_end("Replace Data Resources", "backend")
        
        # Step 5: Parallel Generation (with generated data)
        logger.log_step_start("Parallel Generation", "backend")
        logger.start_stage("Parallel Generation", "backend")
        logger.log_info("⚡ Generating Implementation and Tests in Parallel...")
        
        # Use interfaces directly (already user-friendly)
        logger.log_info("Using user-facing interfaces for implementation")
        logger.log_info("Using generated data for test consistency")
        
        implementation, tests = await self.parallel_generator.generate_async(
            tasks, data_models, interfaces, website_type, generated_data.static_data
        )
        
        # Store in data manager
        self.data_manager.set_implementation(implementation)
        self.data_manager.set_tests(tests)
        
        logger.log_info("✅ Successfully generated implementation and tests")
        logger.end_stage("Parallel Generation")
        logger.log_step_end("Parallel Generation", "backend")
        
        # Step 6: Validate and Fix (with generated data)
        logger.log_step_start("Validate and Fix", "backend")
        logger.start_stage("Validate and Fix", "backend")

        # Check if TDD validation should be skipped (for ablation study)
        skip_validation = self.config_manager.get("skip_tdd_validation", False)

        if skip_validation:
            # Skip validation but keep logging for timing completeness
            logger.log_info("⏭️  Skipping TDD Validation (ablation study mode)")
            logger.log_info("Using original implementation without testing")

            fixed_implementation = implementation
            test_results = {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": True,
                "message": "Validation skipped for ablation study"
            }

            # Calculate statistics for skipped validation
            total_tests = 0
            passed_tests = 0
            failed_tests = 0
        else:
            # Normal validation flow
            logger.log_info("🧪 Validating Implementation with Tests...")
            fixed_implementation, test_results = await self.test_validator.validate_and_fix(
                implementation, tests, generated_data.static_data
            )

            # Update implementation if fixed
            if fixed_implementation != implementation:
                self.data_manager.set_implementation(fixed_implementation)

            # Calculate statistics
            total_tests = test_results.get('total', 0)
            passed_tests = test_results.get('passed', 0)
            failed_tests = test_results.get('failed', 0)

        # Store test results (whether skipped or not)
        self.data_manager.set_test_results(test_results)

        logger.log_info(f"\n=== Test Results ===")
        logger.log_info(f"Total Tests: {total_tests}")
        logger.log_info(f"Passed: {passed_tests}")
        logger.log_info(f"Failed: {failed_tests}")
        if skip_validation:
            logger.log_info(f"Status: SKIPPED (ablation study)")
        logger.end_stage("Validate and Fix")
        logger.log_step_end("Validate and Fix", "backend")
        
        return {
            'generated_data': generated_data,
            'fixed_implementation': fixed_implementation,
            'tests': tests,
            'test_results': test_results
        }
    
    async def _run_frontend_pipeline(self, tasks, data_models, interfaces, website_type, design_image_path, logger):
        """
        Frontend pipeline: Architecture design, page design, visual analysis, layout, framework, page generation, image replacement, data injection, evaluators
        
        Args:
            logger: Independent logger instance for this pipeline
        """
        import asyncio
        
        # Step 3: Design Complete Architecture
        logger.log_step_start("Design Complete Architecture", "frontend")
        logger.start_stage("Design Architecture", "frontend")
        logger.log_info("🏗️ Designing Complete Website Architecture...")
        
        # Design architecture with interfaces and primary architecture
        architecture = await self.architecture_designer.design_architecture(
            tasks, 
            interfaces,
            data_models,
            website_type,
            self.data_manager.primary_architecture
        )
        
        # Store final architecture
        self.data_manager.set_architecture(architecture)
        
        # Print architecture summary
        arch_summary = self.architecture_designer.generate_architecture_summary(architecture)
        logger.log_info(f"\n{arch_summary}")
        logger.end_stage("Design Architecture")
        logger.log_step_end("Design Complete Architecture", "frontend")
        
        # Step 3.5: Design Page Functionality
        logger.log_step_start("Design Page Functionality", "frontend")
        logger.start_stage("Design Pages", "frontend")
        logger.log_info("🎨 Designing Page Functionality Based on Architecture...")
        
        # Get data from data manager
        data_dict = self.data_manager.get_data_models_dict()
        

        import asyncio
        page_designs = await self.page_designer.design_pages(
            architecture,
            data_dict,
            interfaces,
            website_type
        )
        
        # Store page designs in data manager
        self.data_manager.set_page_designs(page_designs)
        
        # Print page design summary
        page_summary = self.page_designer.generate_design_summary(page_designs)
        logger.log_info(f"\n{page_summary}")
        
        logger.log_info(f"✅ Successfully designed {len(page_designs)} pages")
        logger.end_stage("Design Pages")
        logger.log_step_end("Design Page Functionality", "frontend")
        
        # Step 7: Analyze Design Image
        logger.log_step_start("Analyze Design Image", "frontend")
        logger.start_stage("Analyze Design Image", "frontend")
        logger.log_info(f"🖼️ Analyzing design image for visual characteristics...")
        
        design_analysis = await self.design_analyzer.analyze_design(
            design_image_path,
            website_type
        )
        
        # Store design analysis in data manager
        self.data_manager.set_design_analysis(design_analysis)
        
        # Print analysis summary
        analysis_summary = self.design_analyzer.generate_analysis_summary(design_analysis)
        logger.log_info(f"\n{analysis_summary}")
        logger.log_info("✅ Successfully analyzed design image")
        
        logger.end_stage("Analyze Design Image")
        logger.log_step_end("Analyze Design Image", "frontend")
        
        # Step 8: Design Page Layouts
        logger.log_step_start("Design Page Layouts", "frontend")
        logger.start_stage("Design Page Layouts", "frontend")
        logger.log_info("📐 Designing page layouts based on visual analysis...")
        
        # Design layouts for all pages
        page_designs_with_layouts = await self.layout_designer.design_layouts(
            page_designs,  # Use the PageDesign objects from Step 3.5
            design_analysis,
            data_models,
            website_type
        )
        
        # Update page designs with layout information
        self.data_manager.update_page_designs_with_layouts(page_designs_with_layouts)
        
        # Print layout summary
        layout_summary = self.layout_designer.generate_layout_summary(page_designs_with_layouts)
        logger.log_info(f"\n{layout_summary}")
        
        logger.log_info(f"✅ Successfully designed layouts for {len(page_designs_with_layouts)} pages")
        logger.end_stage("Design Page Layouts")
        logger.log_step_end("Design Page Layouts", "frontend")
        
        # Step 9: Generate Page Framework  
        logger.log_step_start("Generate Page Framework", "frontend")
        logger.start_stage("Generate Page Framework", "frontend")
        logger.log_info("🏗️ Generating page framework with header/footer...")
        
        # Generate framework based on architecture and design
        page_framework = await self.framework_generator.generate_framework(
            architecture,
            design_analysis,
            website_type,
            design_image_path
        )
        
        # Save framework to data manager
        self.data_manager.set_page_framework(page_framework)
        
        logger.log_info("✅ Successfully generated page framework")
        logger.end_stage("Generate Page Framework")
        logger.log_step_end("Generate Page Framework", "frontend")
        
        # Step 10: Generate Pages (HTML and CSS)
        logger.log_step_start("Generate Pages", "frontend")
        logger.start_stage("Generate Pages", "frontend")
        logger.log_info("📄 Generating HTML pages and CSS styles...")
        

        # Use interfaces directly (already user-friendly)
        all_interfaces = interfaces.get('interfaces', [])
        
        # Create page layouts mapping (handle both dict and dataclass)
        page_layouts = {}
        for page_design in page_designs:
            if hasattr(page_design, 'layout') and page_design.layout:
                page_layouts[page_design.filename] = page_design.layout
            elif isinstance(page_design, dict) and 'layout' in page_design:
                page_layouts[page_design['filename']] = page_design['layout']
        
        # Filter interfaces for each page based on assigned_interfaces (handle both dict and dataclass)
        page_interfaces = {}
        for page_design in page_designs:
            if hasattr(page_design, 'assigned_interfaces'):
                assigned_interface_names = page_design.assigned_interfaces or []
                filename = page_design.filename
            elif isinstance(page_design, dict):
                assigned_interface_names = page_design.get('assigned_interfaces', [])
                filename = page_design['filename']
            else:
                assigned_interface_names = []
                filename = 'unknown'
            
            page_interfaces[filename] = [
                interface for interface in all_interfaces
                if interface.get('name') in assigned_interface_names
            ]
        
        # Create architecture pages mapping by filename for navigation data
        architecture_pages = {}
        if hasattr(architecture, 'pages'):
            for page in architecture.pages:
                if isinstance(page, dict):
                    page_filename = page.get('filename', '')
                    architecture_pages[page_filename] = {
                        'incoming_params': page.get('incoming_params', []),
                        'outgoing_connections': page.get('outgoing_connections', []),
                        'access_methods': page.get('access_methods', [])
                    }
        
        # Generate pages with page-specific interfaces and architecture data
        generated_pages = await self.page_generator.generate_pages_async(
            page_designs,
            website_type,
            data_dict,
            page_interfaces,  # Pass page-specific interfaces
            page_layouts,
            self.data_manager.get_page_framework(),
            design_analysis.__dict__ if design_analysis else None,
            architecture_pages  # Pass architecture navigation data
        )
        
        # Save generated pages to output directory
        for page in generated_pages:
            html_path = os.path.join(self.output_dir, page.filename)
            css_filename = page.filename.replace('.html', '.css')
            css_path = os.path.join(self.output_dir, css_filename)
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(page.html_content)
            with open(css_path, 'w', encoding='utf-8') as f:
                f.write(page.css_content)
            
            logger.log_info(f"  ✅ Saved {page.filename} and {css_filename}")
        
        logger.log_info(f"✅ Successfully generated {len(generated_pages)} pages")
        logger.end_stage("Generate Pages")
        logger.log_step_end("Generate Pages", "frontend")
        
        # Step 11b: Replace Page Images
        logger.log_step_start("Replace Page Resources", "frontend")
        logger.log_info("🖼️ Replacing images in HTML pages...")
        
        # Collect all HTML pages
        html_pages = {}
        for page_design in self.data_manager.get_page_designs():
            # Handle both dict and dataclass
            if hasattr(page_design, 'filename'):
                filename = page_design.filename
            else:
                filename = page_design.get('filename', 'page.html')
            
            html_file = os.path.join(self.output_dir, filename)
            if os.path.exists(html_file):
                with open(html_file, 'r', encoding='utf-8') as f:
                    html_pages[filename] = f.read()
        
        # Replace resources in pages
        page_resource_result = await self.resource_replacer.replace_page_resources_async(html_pages, website_type)
        
        # Save updated pages
        for filename, updated_html in page_resource_result.updated_pages.items():
            html_file = os.path.join(self.output_dir, filename)
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(updated_html)
        
        total_page_replacements = sum(len(r) for r in page_resource_result.replacements.values())
        logger.log_info(f"  ✅ Replaced {total_page_replacements} resources across {len(page_resource_result.replacements)} pages")

        logger.log_step_end("Replace Page Resources", "frontend")

        # Step 12: Inject Data into index.html
        logger.log_step_start("Inject Data", "frontend")
        logger.log_info("💉 Injecting data into index.html...")
        
        # Get updated HTML pages from resource replacement
        final_html_pages = page_resource_result.updated_pages
        
        # Get data from file (backend pipeline will have saved it by now)
        import json
        data_file_path = os.path.join(self.output_dir, "website_data.json")
        with open(data_file_path, 'r', encoding='utf-8') as f:
            static_data = json.load(f)
        
        # Inject data initialization script
        final_html_pages = self.data_injector.inject_data_to_index(
            final_html_pages,
            static_data
        )
        
        # Save updated pages with injected data
        for filename, updated_html in final_html_pages.items():
            html_file = os.path.join(self.output_dir, filename)
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(updated_html)
        
        logger.log_info(f"  ✅ Successfully injected data into index.html")
        logger.log_step_end("Inject Data", "frontend")

        # Note: Step 13 (Instrumentation) and Step 14 (Syntax Fix) are now executed
        # after both frontend and backend pipelines complete, since they depend on
        # business_logic.js which is generated by the backend pipeline.

        return {
            'architecture': architecture,
            'page_designs': page_designs,
            'design_analysis': design_analysis,
            'generated_pages': generated_pages
        }
    
    def generate(self, website_type: str = None,
                custom_task_names: List[str] = None,
                design_image_path: str = None) -> TDDGenerationResult:
        """
        Generate business logic from website type using TDD approach
        
        Args:
            website_type: Type of website (if None, reads from config)
            custom_task_names: Optional list of specific task names (if None, reads from config)
            design_image_path: Path to design image (if None, reads from config)
            
        Returns:
            TDDGenerationResult with implementation, tests, and validation results
            
        Raises:
            ValueError: If design_image_path is not provided in params or config
        """
        # Read from config if not provided
        if website_type is None:
            website_type = self.config_manager.get("website_type", "shopping_website")
        if custom_task_names is None:
            custom_task_names = self.config_manager.get("custom_task_names", None)
            # Convert empty list to None
            if custom_task_names == []:
                custom_task_names = None
        if design_image_path is None:
            design_image_path = self.config_manager.get("design_image_path", "")
        
        # Validate design_image_path is provided
        if not design_image_path:
            raise ValueError("design_image_path is required for TDD generation. Please set it in config or pass as parameter.")
        
        start_time = time.time()
        
        # Print configuration summary
        self.config_manager.print_summary()
        
        self.logger.log_info("=" * 60)
        self.logger.log_info("Starting TDD Generation Process")
        self.logger.log_info(f"Website Type: {website_type}")
        self.logger.log_info(f"Design Image: {design_image_path}")
        if custom_task_names:
            self.logger.log_info(f"Custom Task Names: {custom_task_names}")
        self.logger.log_info("=" * 60)
        
        try:
            # Step 0: Generate Tasks
            self.logger.log_step_start("Generate Tasks", "PREPARE")
            self.logger.start_stage("Generate Tasks", "prepare")
            self.logger.log_info("📋 Stage 00: Generating Tasks from Website Type...")
            task_count_range = self.config_manager.get("task_count_range", "3-5")
            tasks = self.task_generator.generate_tasks(
                website_type,
                task_count_range,
                custom_task_names
            )
            
            # Store tasks in data manager
            self.data_manager.set_tasks(tasks, website_type)
            
            # Print task summary
            task_summary = self.task_generator.generate_task_summary(tasks)
            self.logger.log_info(f"\n{task_summary}")
            self.logger.end_stage("Generate Tasks")
            self.logger.log_step_end("Generate Tasks", "PREPARE")

            # Step 0.5: Design Primary Architecture
            self.logger.log_step_start("Design Primary Architecture", "PREPARE")
            self.logger.start_stage("Design Primary Architecture", "prepare")
            self.logger.log_info("🏗️ Designing primary website architecture...")
            primary_architecture = self.primary_architecture_designer.design_primary_architecture(
                tasks, website_type
            )
            
            # Store primary architecture in data manager
            self.data_manager.primary_architecture = primary_architecture
            
            # Print primary architecture summary
            primary_arch_summary = self.primary_architecture_designer.generate_architecture_summary(primary_architecture)
            self.logger.log_info(f"\n{primary_arch_summary}")
            self.logger.end_stage("Design Primary Architecture")
            self.logger.log_step_end("Design Primary Architecture", "PREPARE")

            # Step 1: Extract Data Models
            self.logger.log_step_start("Extract Data Models", "PREPARE")
            self.logger.start_stage("Extract Data Models", "prepare")
            self.logger.log_info("📊 Extracting Data Models from Tasks...")
            data_models = self.data_extractor.extract_data_models(tasks, website_type, primary_architecture)
            
            # Store in data manager
            self.data_manager.set_data_models(data_models)
            
            # Save debug data
            self.data_manager.save_debug_data("debug_step1_data_models.json")
            self.logger.log_info(f"Debug data saved for Step 1")
            
            # Always validate data models
            validation_result = self.data_manager.validate_data_models()
            if not validation_result["valid"]:
                self.logger.log_error(f"Data models validation failed: {validation_result['errors']}")
                raise ValueError("Invalid data models extracted")
            
            # Print summary
            schema_summary = self.data_extractor.generate_schema_summary(data_models)
            self.logger.log_info(f"\n{schema_summary}")
            self.logger.end_stage("Extract Data Models")
            self.logger.log_step_end("Extract Data Models", "PREPARE")

            # Step 2: Design Interfaces
            self.logger.log_step_start("Design Interfaces", "PREPARE")
            self.logger.start_stage("Design Interfaces", "prepare")
            self.logger.log_info("🔧 Designing Interfaces from Data Models + Tasks...")
            interfaces = self.interface_designer.design_interfaces(
                tasks, data_models, website_type, primary_architecture
            )

            # Store in data manager
            self.data_manager.set_interfaces(interfaces)
            
            # Print interface contract
            contract = self.interface_designer.generate_interface_contract(interfaces)
            self.logger.log_info(f"\n=== Interface Contract ===\n{contract}")
            
            # Validate interface coverage
            validation = self.interface_designer.validate_interfaces(interfaces, tasks)
            if not validation['valid']:
                warnings_str = "; ".join(validation['warnings']) if validation['warnings'] else "No specific warnings"
                self.logger.log_warning(f"Interface validation warnings: {warnings_str}")

            # Lint interface specs for deterministic quality checks
            lint_result = self.interface_designer.lint_interfaces(interfaces)
            if not lint_result['passed']:
                errors_str = "; ".join(lint_result['errors'])
                raise ValueError(f"Interface lint failed: {errors_str}")

            self.logger.end_stage("Design Interfaces")
            self.logger.log_step_end("Design Interfaces", "PREPARE")

            # Step 3-13: Parallel Execution - Backend and Frontend Pipelines
            self.logger.log_info("🚀 Starting parallel execution of backend and frontend pipelines...")
            
            # Create independent logger instances for each pipeline
            backend_logger = TDDLogger(
                output_dir=os.path.join(self.output_dir, "logs"),
                log_level=self.logger.log_level.value
            )
            frontend_logger = TDDLogger(
                output_dir=os.path.join(self.output_dir, "logs"),
                log_level=self.logger.log_level.value
            )
            
            # Share the main logger's timing file for unified time recording
            backend_logger.timing_file = self.logger.timing_file
            frontend_logger.timing_file = self.logger.timing_file
            
            import asyncio
            
            async def run_parallel_pipelines():
                # Run backend pipeline with independent logger
                backend_task = asyncio.create_task(
                    self._run_backend_pipeline(tasks, data_models, interfaces, website_type, backend_logger)
                )
                
                # Start frontend pipeline with independent logger
                frontend_task = asyncio.create_task(
                    self._run_frontend_pipeline(tasks, data_models, interfaces, website_type, design_image_path, frontend_logger)
                )
                
                # Wait for both to complete
                backend_result, frontend_result = await asyncio.gather(backend_task, frontend_task)
                return backend_result, frontend_result
            
            backend_result, frontend_result = asyncio.run(run_parallel_pipelines())

            self.logger.log_info("✅ Parallel execution completed successfully")

            # Step 13: Instrumentation Post-Processing (after both pipelines complete)
            # This step requires business_logic.js which is generated by the backend pipeline
            self.logger.log_step_start("Instrumentation", "frontend")
            self.logger.start_stage("Instrumentation", "frontend")
            self.logger.log_info("🔧 Running instrumentation post-processing...")

            instrumentation_config = self.config_manager.get_component_config("instrumentation")

            post_config = {
                "reasoning_effort": instrumentation_config["reasoning_effort"],
                "model": instrumentation_config["model"],
                "task_rewriting": {
                    "include_full_data": True
                }
            }

            processor = TDDInstrumentationPostProcessor(self.output_dir, post_config)
            post_result = asyncio.run(processor.process())

            if post_result["success"]:
                evaluators = post_result.get("evaluators", [])
                self.logger.log_info(f"  ✅ Generated {len(evaluators)} evaluators")
            else:
                self.logger.log_warning(f"Post-processing issue: {post_result.get('error')}")
                evaluators = []

            self.data_manager.evaluators = evaluators

            self.logger.end_stage("Instrumentation")
            self.logger.log_step_end("Instrumentation", "frontend")

            # Step 14: Syntax Fix
            self.logger.log_step_start("Fix Syntax", "frontend")
            self.logger.start_stage("Fix Syntax", "frontend")
            self.logger.log_info("🔧 Fixing HTML/JavaScript syntax errors...")

            fix_results = asyncio.run(self.syntax_fixer.fix_directory(self.output_dir))

            self.logger.log_info(f"  ✅ Fixed {fix_results['files_fixed']} files, "
                                f"{fix_results['files_failed']} failed")
            self.logger.end_stage("Fix Syntax")
            self.logger.log_step_end("Fix Syntax", "frontend")

            # Extract results for backward compatibility
            generated_data = backend_result['generated_data']
            fixed_implementation = backend_result['fixed_implementation']
            tests = backend_result['tests']
            test_results = backend_result['test_results']
            
            # Calculate statistics for result processing
            total_tests = test_results.get('total', 0)
            passed_tests = test_results.get('passed', 0)
            failed_tests = test_results.get('failed', 0)
            iterations_used = self.config_manager.get("max_fix_iterations")  # Get from config
            
            # Save results
            self.logger.start_stage("Save Results", "prepare")
            self.logger.log_info(f"💾 Saving generated files to {self.output_dir}...")
            
            # Use test validator to save code files
            self.test_validator.save_results(
                fixed_implementation, tests, test_results, self.output_dir
            )
            
            # Calculate generation time
            generation_time = time.time() - start_time
            
            # Create and store generation result
            result = self.data_manager.create_generation_result(
                success=(failed_tests == 0),
                generation_time=generation_time,
                iterations_used=iterations_used
            )
            
            # Save logger summary
            self.logger.save_summary()
            
            # Print data summary
            self.data_manager.print_summary()
            
            # Generate and save token usage report
            try:
                tracker = get_token_tracker()
                # Save report to output directory
                text_file, json_file = tracker.save_report(self.output_dir, "token_usage_report")
                self.logger.log_info(f"Token usage reports saved successfully")
                
                # Print summary to console
                print("\n" + "=" * 80)
                print("TOKEN USAGE SUMMARY")
                print("=" * 80)
                stats = tracker.get_stats()
                total = stats["total_stats"]
                print(f"Total API Calls: {total['api_calls']:,}")
                print(f"Total Input Tokens: {total['input_tokens']:,}")
                print(f"Total Output Tokens: {total['output_tokens']:,}")
                print(f"Total Tokens: {total['total_tokens']:,}")
                
                if stats["model_stats"]:
                    print("\nTokens by Model:")
                    for model, model_stat in stats["model_stats"].items():
                        percentage = (model_stat['total_tokens'] / total['total_tokens']) * 100 if total['total_tokens'] > 0 else 0
                        print(f"  {model}: {model_stat['total_tokens']:,} tokens ({percentage:.1f}%)")
                print("=" * 80)
                
            except Exception as e:
                self.logger.log_warning(f"Failed to generate token usage report: {e}")
            
            self.logger.end_stage("Save Results")
            
            self.logger.log_info(f"\n✨ TDD Generation Complete!")
            self.logger.log_info(f"Time taken: {generation_time:.2f} seconds")
            self.logger.log_info(f"Success: {result.success}")
            
            return result
            
        except Exception as e:
            self.logger.log_exception(e, "TDD Generation")
            
            # Create failure result
            result = self.data_manager.create_generation_result(
                success=False,
                generation_time=time.time() - start_time,
                iterations_used=0
            )
            result.test_results = {"error": str(e)}
            
            # Save whatever data we have for debugging
            self.data_manager.save_debug_data("debug_error_state.json")
            
            return result
    
    def generate_from_config(self, config_path: str) -> TDDGenerationResult:
        """
        Generate from a JSON configuration file
        
        Args:
            config_path: Path to JSON config file
            
        Returns:
            TDDGenerationResult
        """
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Update config manager with file contents
        for key, value in config.items():
            self.config_manager.set(key, value)
        
        # Generate using config values
        return self.generate()


if __name__ == "__main__":
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="TDD Website Generator")
    parser.add_argument("--config", type=str, help="Path to configuration file")
    parser.add_argument("--website-type", type=str, help="Type of website to generate")
    parser.add_argument("--design-image", type=str, help="Path to design image")
    parser.add_argument("--output-dir", type=str, help="Output directory")
    parser.add_argument("--custom-tasks", type=str, help="JSON string of custom task names")

    args = parser.parse_args()
    
    print("Testing TDD Generator with automatic task generation...")
    
    # Initialize generator with config file if provided
    generator = TDDGenerator(
        output_dir=args.output_dir,
        config_path=args.config
    )
    
    # Determine website type (from args or config)
    website_type = args.website_type or generator.config_manager.get("website_type", "shopping_website")

    # Set design image if provided
    if args.design_image:
        generator.config_manager.set("design_image_path", args.design_image)

    # Parse custom tasks if provided
    custom_task_names = None
    if args.custom_tasks:
        try:
            custom_task_names = json.loads(args.custom_tasks)
        except json.JSONDecodeError:
            print(f"Error: Invalid JSON for custom tasks: {args.custom_tasks}")
            custom_task_names = None

    # Test with automatic task generation or custom tasks
    result = generator.generate(website_type, custom_task_names=custom_task_names)
    
    if result.success:
        print("\n✅ TDD Generation successful!")
        print(f"You can run the tests with: node {generator.output_dir}/run_tests.js")
        
        # Display final token usage summary
        try:
            tracker = get_token_tracker()
            print(f"\nToken usage reports saved to:")
            print(f"  - {generator.output_dir}/token_usage_report.txt")
            print(f"  - {generator.output_dir}/token_usage_report.json")
        except Exception as e:
            print(f"Warning: Could not display token usage: {e}")
    else:
        print("\n❌ TDD Generation failed!")
        print(f"Error: {result.test_results.get('error', 'Unknown error')}")
        sys.exit(1)