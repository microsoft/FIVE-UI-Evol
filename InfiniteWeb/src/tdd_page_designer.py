"""
TDD Page Designer Module

This module designs detailed page functionality based on architecture and interfaces,
including page title, description, functionality, and components.
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from llm_caller import call_openai_api_json
from tdd_logger_module import TDDLogger


@dataclass
class ComponentSpec:
    """Component specification for functional design"""
    id: str
    type: str  # "search-form", "product-grid", "filter-sidebar", etc.
    functionality: str
    data_binding: List[str] = field(default_factory=list)  # Data types this component uses
    event_handlers: List[str] = field(default_factory=list)  # User interactions it handles


@dataclass
class PageFunctionality:
    """Consolidated page functionality design"""
    core_features: List[str]
    user_workflows: List[str]
    interactions: List[str]
    state_logic: str


@dataclass
class PageLayout:
    """Page layout specification"""
    grid_system: str  # "12-column", "custom-grid", etc.
    spacing_rules: Dict[str, str]  # {"padding": "24px", "gap": "16px"}
    layout_pattern: str  # "sidebar-content", "centered", "full-width"
    visual_hierarchy: List[str]  # ["header", "main-content", "sidebar", "footer"]
    responsive_breakpoints: Dict[str, str]  # {"mobile": "768px", "tablet": "1024px"}
    layout_strategies: Optional[Dict] = None  # Strategy choices and reasoning
    overall_description: Optional[str] = None  # Overall layout description
    component_layouts: Optional[List[Dict]] = None  # Detailed component layouts


@dataclass
class PageDesign:
    """Complete page design specification"""
    name: str
    filename: str
    title: str
    description: str
    page_functionality: PageFunctionality
    components: List[ComponentSpec]
    assigned_interfaces: List[str] = field(default_factory=list)  # Interfaces assigned to this page
    layout: PageLayout = None  # Layout information


class TDDPageDesigner:
    """
    Designs detailed page functionality based on architecture and interfaces
    """
    
    def __init__(self, logger: Optional[TDDLogger] = None,
                 max_concurrent: int = 3, model=None, reasoning_effort=None):
        """
        Initialize the TDD Page Designer

        Args:
            logger: Optional TDDLogger instance
            max_concurrent: Maximum concurrent page designs
            model: Model to use (e.g., "gpt-4.1", "gpt-5", None for default)
            reasoning_effort: Reasoning effort level (e.g., "low", "medium", "high")
        """
        self.logger = logger or TDDLogger()
        self.max_concurrent = max_concurrent
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def design_pages(self, 
                          architecture: Any,
                          data_dict: Dict[str, Any],
                          interfaces: Dict[str, Any],
                          website_type: str) -> List[PageDesign]:
        """
        Design all pages in parallel based on architecture
        
        Args:
            architecture: Website architecture object or dict with page definitions
            data_dict: Enhanced data models
            interfaces: Complete interface definitions
            website_type: Type of website
            
        Returns:
            List of PageDesign objects
        """
        self.logger.start_stage("Design Pages")
        self.logger.log_info(f"🎨 Designing page functionality for {website_type}...")
        
        # Convert architecture object to dict if needed
        if hasattr(architecture, 'pages'):
            # It's a WebsiteArchitecture object
            pages = architecture.pages
        elif isinstance(architecture, dict):
            # It's already a dict
            pages = architecture.get("pages", [])
        else:
            pages = []
        if not pages:
            self.logger.log_warning("No pages found in architecture")
            self.logger.end_stage("Design Pages")
            return []
        
        self.logger.log_info(f"Designing {len(pages)} pages in parallel (max concurrent: {self.max_concurrent})...")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Create tasks for parallel design
        tasks = []
        for page_spec in pages:
            task = self._design_single_page_async(
                page_spec, 
                data_dict, 
                interfaces,
                website_type,
                semaphore
            )
            tasks.append(task)
        
        # Execute all tasks
        results = await asyncio.gather(*tasks)
        
        # Convert results to PageDesign objects
        page_designs = []
        for result in results:
            if result:
                page_designs.append(result)
        
        self.logger.log_info(f"✅ Successfully designed {len(page_designs)} pages")
        self.logger.end_stage("Design Pages")
        
        return page_designs
    
    async def _design_single_page_async(self,
                                       page_spec: Dict[str, Any],
                                       data_dict: Dict[str, Any],
                                       interfaces: Dict[str, Any],
                                       website_type: str,
                                       semaphore: asyncio.Semaphore) -> Optional[PageDesign]:
        """
        Async wrapper for single page design with concurrency control
        
        Args:
            page_spec: Page specification from architecture
            data_dict: Enhanced data models
            interfaces: Complete interface definitions
            website_type: Type of website
            semaphore: Concurrency control
            
        Returns:
            PageDesign object or None if failed
        """
        async with semaphore:
            return await asyncio.to_thread(
                self._design_single_page,
                page_spec,
                data_dict,
                interfaces,
                website_type
            )
    
    def _design_single_page(self,
                           page_spec: Dict[str, Any],
                           data_dict: Dict[str, Any],
                           interfaces: Dict[str, Any],
                           website_type: str) -> Optional[PageDesign]:
        """
        Design a single page's functionality
        
        Args:
            page_spec: Page specification from architecture
            data_dict: Enhanced data models
            interfaces: Complete interface definitions
            website_type: Type of website
            
        Returns:
            PageDesign object or None if failed
        """
        filename = page_spec.get("filename", "unknown.html")
        page_name = page_spec.get("name", "Unknown Page")
        
        self.logger.log_info(f"  Designing page: {filename}")
        
        # Prepare interface information for this page
        assigned_interfaces = page_spec.get("assigned_interfaces", [])
        interface_details = self._get_interface_details(assigned_interfaces, interfaces)

        
        # Prepare navigation information
        navigation_info = self._prepare_navigation_info(page_spec)
        
        prompt = f"""
You are a senior web functional designer. Design the functional aspects and workflows of a webpage.

Website Type: {website_type}

Page Architecture:
{json.dumps(page_spec, indent=2)}

Available Data Models:
{json.dumps(data_dict, indent=2)}

Assigned Interfaces for This Page:
{json.dumps(interface_details, indent=2)}

Navigation Information:
{navigation_info}

DESIGN REQUIREMENTS:
1. Create a functional, descriptive page title that matches the page purpose
2. Write a clear description of the page functionality
3. Design core features based on the assigned interfaces

IMPORTANT: Do NOT add hero sections, welcome banners, marketing taglines, or promotional headlines unless they are explicitly required by the page's core functionality. The page title should be simple and functional (e.g., "Products", "Search Results", "User Profile"), not marketing copy.
4. Define user workflows that utilize the interfaces
5. Specify user interactions (clicks, forms, navigation)
6. Describe state logic using URL parameters (NOT localStorage)
7. Create functional components that use the interfaces

IMPORTANT GUIDELINES:
- Use ONLY the assigned interfaces for this page
- Navigation uses URL parameters (e.g., product.html?id=123)
- Focus on functionality, not visual appearance
- Components should be functional, not presentational
- Each component should have clear data binding and event handlers

** CRITICAL REQUIREMENTS **
- Your output should not involve any static data or hardcoded values, because they will conflict with dynamic data from APIs.

Return JSON format:
{{
    "title": "Simple functional title for {page_name}",
    "description": "Clear description of page functionality",
    "page_functionality": {{
        "core_features": [
            "List of core features using the assigned interfaces"
        ],
        "user_workflows": [
            "Step-by-step user workflows"
        ],
        "interactions": [
            "User interaction descriptions"
        ],
        "state_logic": "How URL parameters and page state affect functionality"
    }},
    "components": [
        {{
            "id": "unique-component-id",
            "type": "functional-component-type",
            "functionality": "What this component does",
            "data_binding": ["DataModel1", "DataModel2"],
            "event_handlers": ["onClick", "onSubmit"]
        }}
    ]
}}

COMPONENT EXAMPLES:
- "search-form": Handles product search
- "product-grid": Displays product listings
- "filter-sidebar": Manages attribute filtering
- "add-to-cart-form": Handles cart operations
- "review-list": Shows product reviews
- "comparison-selector": Manages product comparison
- "checkout-form": Handles checkout process
"""
        
        # Log API call and get call_id
        call_id = self.logger.log_api_call(
            f"Design Page {filename}",
            prompt,
            additional_args={
                "model": "gpt-4",
                "temperature": 0.7
            },
            stage="Design Pages"
        )

        try:
            # Call LLM to generate page design
            messages = [{"role": "user", "content": prompt}]
            response, usage_info = call_openai_api_json(
                messages,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log API response
            self.logger.log_api_response(
                f"Design Page {filename}",
                True,
                response,
                usage_info=usage_info,
                stage="Design Pages",
                call_id=call_id
            )
            
            # Parse response
            if isinstance(response, str):
                design_data = json.loads(response)
            else:
                design_data = response
            
            # Create PageDesign object with assigned interfaces
            page_design = self._create_page_design(
                page_name,
                filename,
                design_data,
                assigned_interfaces
            )
            
            self.logger.log_info(f"    ✅ Successfully designed {filename}")
            return page_design
            
        except Exception as e:
            error_msg = f"Failed to design page {filename}: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.log_api_response(
                f"Design Page {filename}",
                False,
                error=str(e),
                stage="Design Pages",
                call_id=call_id
            )
            return None
    
    def _get_interface_details(self, 
                              interface_names: List[str], 
                              interfaces: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get detailed information for assigned interfaces
        
        Args:
            interface_names: List of interface names assigned to the page
            interfaces: Complete interface definitions
            
        Returns:
            List of interface details
        """
        interface_list = interfaces.get("interfaces", [])
        details = []
        
        for name in interface_names:
            # Find the interface in the list
            for interface in interface_list:
                if interface.get("name") == name:
                    # Extract key information
                    detail = {
                        "name": name,
                        "description": interface.get("description", ""),
                        "parameters": [p.get("name", "") for p in interface.get("parameters", [])],
                        "returns": interface.get("returns", {})
                    }
                    details.append(detail)
                    break
        
        return details
    
    def _prepare_navigation_info(self, page_spec: Dict[str, Any]) -> str:
        """
        Prepare navigation information for the page
        
        Args:
            page_spec: Page specification from architecture
            
        Returns:
            Navigation information string
        """
        incoming = page_spec.get("incoming_params", [])
        outgoing = page_spec.get("outgoing_connections", [])
        
        info_parts = []
        
        if incoming:
            info_parts.append("Incoming URL Parameters:")
            for param in incoming:
                param_name = param.get("param_name", "")
                param_type = param.get("param_type", "")
                sources = param.get("source_pages", [])
                desc = param.get("description", "")
                info_parts.append(f"  - {param_name} ({param_type}): {desc}")
                if sources:
                    info_parts.append(f"    From: {', '.join(sources)}")
        
        if outgoing:
            info_parts.append("\nOutgoing Navigation:")
            for conn in outgoing:
                target = conn.get("target", "")
                params = conn.get("params", {})
                trigger = conn.get("trigger", "")
                info_parts.append(f"  - To {target}: {trigger}")
                if params:
                    info_parts.append(f"    Parameters: {json.dumps(params)}")
        
        return "\n".join(info_parts) if info_parts else "No specific navigation requirements"
    
    def _create_page_design(self, 
                          page_name: str,
                          filename: str,
                          design_data: Dict[str, Any],
                          assigned_interfaces: List[str] = None) -> PageDesign:
        """
        Create PageDesign object from LLM response
        
        Args:
            page_name: Name of the page
            filename: Filename of the page
            design_data: Design data from LLM
            
        Returns:
            PageDesign object
        """
        # Parse page functionality
        func_data = design_data.get("page_functionality", {})
        page_functionality = PageFunctionality(
            core_features=func_data.get("core_features", []),
            user_workflows=func_data.get("user_workflows", []),
            interactions=func_data.get("interactions", []),
            state_logic=func_data.get("state_logic", "")
        )
        
        # Parse components
        components = []
        for comp_data in design_data.get("components", []):
            component = ComponentSpec(
                id=comp_data.get("id", ""),
                type=comp_data.get("type", ""),
                functionality=comp_data.get("functionality", ""),
                data_binding=comp_data.get("data_binding", []),
                event_handlers=comp_data.get("event_handlers", [])
            )
            components.append(component)
        
        # Create PageDesign
        return PageDesign(
            name=page_name,
            filename=filename,
            title=design_data.get("title", ""),
            description=design_data.get("description", ""),
            page_functionality=page_functionality,
            components=components,
            assigned_interfaces=assigned_interfaces or []
        )
    
    def generate_design_summary(self, page_designs: List[PageDesign]) -> str:
        """
        Generate a human-readable summary of page designs
        
        Args:
            page_designs: List of PageDesign objects
            
        Returns:
            Summary string
        """
        lines = []
        lines.append("=== Page Design Summary ===\n")
        lines.append(f"Total Pages Designed: {len(page_designs)}")
        
        for design in page_designs:
            lines.append(f"\n📄 {design.name} ({design.filename})")
            lines.append(f"   Title: {design.title}")
            lines.append(f"   Components: {len(design.components)}")
            
            # List core features
            if design.page_functionality.core_features:
                lines.append("   Core Features:")
                for feature in design.page_functionality.core_features[:3]:  # Show first 3
                    lines.append(f"     - {feature[:60]}...")  # Truncate long features
            
            # List component types
            if design.components:
                component_types = [c.type for c in design.components]
                lines.append(f"   Component Types: {', '.join(component_types[:5])}")
        
        return "\n".join(lines)


if __name__ == "__main__":
    import asyncio
    
    # Test the page designer
    print("Testing TDD Page Designer...")
    
    # Sample architecture
    sample_architecture = {
        "pages": [
            {
                "name": "Home Page",
                "filename": "index.html",
                "description": "Main landing page",
                "primary_functions": ["Display featured products", "Search"],
                "assigned_interfaces": ["getFeaturedProducts", "searchProducts"],
                "incoming_params": [],
                "outgoing_connections": [
                    {"target": "product.html", "params": {"id": "productId"}}
                ]
            }
        ]
    }
    
    # Sample data models
    sample_data_models = {
        "Product": {
            "fields": {"id": "string", "name": "string", "price": "number"}
        }
    }
    
    # Sample interfaces
    sample_interfaces = {
        "interfaces": [
            {
                "name": "getFeaturedProducts",
                "description": "Get featured products",
                "parameters": [],
                "returns": {"type": "array"}
            }
        ]
    }
    
    designer = TDDPageDesigner()
    
    # Run async design
    async def test_design():
        designs = await designer.design_pages(
            sample_architecture,
            sample_data_models,
            sample_interfaces,
            "shopping_website"
        )
        return designs
    
    designs = asyncio.run(test_design())
    
    # Print summary
    if designs:
        summary = designer.generate_design_summary(designs)
        print(summary)