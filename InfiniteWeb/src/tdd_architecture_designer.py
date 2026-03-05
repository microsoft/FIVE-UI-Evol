"""
TDD Architecture Designer Module

This module designs website architecture based on tasks and interfaces,
including page structure, navigation, and interface assignment.
"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from llm_caller import call_openai_api_json_async
from tdd_logger_module import TDDLogger


@dataclass
class PageArchitecture:
    """Complete page architecture specification"""
    name: str
    filename: str
    description: str
    primary_functions: List[str]
    assigned_interfaces: List[str]
    incoming_params: List[Dict[str, Any]]
    outgoing_connections: List[Dict[str, Any]]
    access_methods: List[Dict[str, Any]]


@dataclass
class WebsiteArchitecture:
    """Complete website architecture"""
    all_pages: List[Dict[str, str]]
    pages: List[Dict[str, Any]]
    header_links: List[Dict[str, str]]
    footer_links: List[Dict[str, str]]


class TDDArchitectureDesigner:
    """
    Designs website architecture based on tasks and interfaces
    """
    
    def __init__(self, logger: Optional[TDDLogger] = None, max_pages: int = 8, model=None, reasoning_effort=None):
        """
        Initialize the TDD Architecture Designer

        Args:
            logger: Optional TDDLogger instance
            max_pages: Maximum number of pages to generate
            model: Model to use (e.g., "gpt-4.1", "gpt-5", None for default)
            reasoning_effort: Reasoning effort level (e.g., "low", "medium", "high")
        """
        self.logger = logger or TDDLogger()
        self.max_pages = max_pages
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def design_architecture(self, tasks: List[Dict[str, Any]], 
                                 interfaces: Dict[str, Any], 
                                 data_models: Dict[str, Any],
                                 website_type: str,
                                 primary_architecture: Any = None) -> WebsiteArchitecture:
        """
        Design website architecture based on tasks and interfaces
        
        Args:
            tasks: List of user tasks
            interfaces: List of interface definitions
            data_models: List of data model definitions
            website_type: Type of website
            primary_architecture: Primary architecture design (optional)
            
        Returns:
            WebsiteArchitecture object
        """
        self.logger.start_stage("Design Architecture")
        self.logger.log_info(f"🏗️ Designing complete website architecture for {website_type}...")
        
        # Prepare task summary
        task_summary = self._prepare_task_summary(tasks)
        
        # Prepare interface summary
        interface_summary = self._prepare_interface_summary(interfaces)
        
        # Prepare data model summary
        data_summary = self._prepare_data_summary(data_models)
        
        # Prepare primary architecture context if provided
        primary_arch_context = ""
        predefined_links_context = ""
        if primary_architecture:
            if hasattr(primary_architecture, 'to_dict'):
                primary_arch_dict = primary_architecture.to_dict()
            elif hasattr(primary_architecture, '__dict__'):
                primary_arch_dict = primary_architecture.__dict__
            else:
                primary_arch_dict = primary_architecture if isinstance(primary_architecture, dict) else {}

            if primary_arch_dict:
                primary_arch_context = f"""
Primary Architecture (initial design):
{json.dumps(primary_arch_dict, indent=2)}

IMPORTANT: Build upon this primary architecture to create the complete detailed architecture.
Maintain consistency with the page structure and functions defined in the primary architecture.
CRITICAL: Use EXACTLY the same pages - do not add or remove any pages.
"""
                # Extract predefined navigation links if available
                header_links = primary_arch_dict.get('header_links', [])
                footer_links = primary_arch_dict.get('footer_links', [])
                if header_links or footer_links:
                    predefined_links_context = f"""
PREDEFINED NAVIGATION LINKS (MUST USE EXACTLY):
The following navigation links are predefined and MUST be used exactly as specified to ensure consistency with generated data:

Header Links:
{json.dumps(header_links, indent=2)}

Footer Links:
{json.dumps(footer_links, indent=2)}

You MUST copy these exact links to your header_links and footer_links output.
Do NOT modify the URLs or parameters - they are synchronized with the data generation.
"""
        
        prompt = f"""
You are a web architect. Design complete website architecture based on user tasks and interfaces.

Website Type: {website_type}
Maximum Pages: {self.max_pages}

User Tasks:
{json.dumps(task_summary, indent=2)}
{primary_arch_context}{predefined_links_context}
Available Interfaces (direct user-facing interfaces):
{json.dumps(interface_summary, indent=2)}

Data Models:
{json.dumps(data_summary, indent=2)}

IMPORTANT: 
- This is for SINGLE-USER agent training - NO authentication/login pages needed
- The interfaces provided are USER-FACING interfaces (no userId/sessionId parameters)
- System state is managed automatically through localStorage

Design Requirements:
1. Use EXACTLY the pages from primary architecture - do not add or remove pages
2. Assign appropriate interfaces to each page based on functionality
3. Use URL parameters for navigation (NOT localStorage for page data)
4. Define incoming parameters (what parameters the page accepts from other pages)
5. Define outgoing connections (what pages this page navigates to with parameters)
6. Specify access methods for each page
7. Design header and footer navigation links

Page Design Guidelines:
- Include {self.max_pages} pages maximum
- Homepage (index.html) should always be included
- Assign interfaces to pages where they are most relevant
- Consider task flow when assigning interfaces
- Remember: interfaces handle system state automatically through localStorage

URL Parameter Guidelines:
- Use query parameters like: product.html?id=123
- incoming_params: Parameters this page accepts from URL
- outgoing_connections: Navigation to other pages with parameters

Access Method Guidelines:
- "navigation": Accessible through header/footer navigation
- "url_param": Accessible through URL parameters from other pages
- "direct_link": Accessible through direct links in content
- "form_submission": Accessible after form submission

Interface Assignment Guidelines:
- Assign each interface to the most appropriate page(s)
- Consider the task flow and user journey
- Group related interfaces on the same page
- If an interface is optional for a page, still assign it if relevant
- Example: getProductDetails and addToCart on product.html
- Assign "Get" interfaces before "Add/Update" interfaces on the same page to ensure data is loaded first(e.g. getPlayList before addToPlayList)

Header and Footer Guidelines:
- If predefined navigation links are provided above, use them EXACTLY as specified
- Otherwise, design appropriate navigation links for the website

Return JSON format:
{{
    "all_pages": [
        {{
            "name": "Home Page",
            "filename": "index.html"
        }},
        {{
            "name": "Product Details",
            "filename": "product.html"
        }}
    ],
    "pages": [
        {{
            "name": "Home Page",
            "filename": "index.html",
            "description": "Main landing page with product listings",
            "primary_functions": [
                "Display featured products",
                "Provide search functionality",
                "Navigate to product details"
            ],
            "assigned_interfaces": [
                "searchProducts",
                "browseCategory"
            ],
            "incoming_params": [],
            "outgoing_connections": [
                {{
                    "target": "product.html",
                    "params": {{"id": "productId"}},
                    "trigger": "Click on product card"
                }},
                {{
                    "target": "search.html",
                    "params": {{"query": "searchTerm"}},
                    "trigger": "Submit search form"
                }}
            ],
            "access_methods": [
                {{
                    "type": "navigation",
                    "location": "header",
                    "description": "Main navigation entry"
                }}
            ]
        }},
        {{
            "name": "Product Details",
            "filename": "product.html",
            "description": "Detailed product view with purchase options",
            "primary_functions": [
                "Display product information",
                "Show product options",
                "Add to cart functionality"
            ],
            "assigned_interfaces": [
                "getProductDetails",
                "addToCart"
            ],
            "incoming_params": [
                {{
                    "param_name": "id",
                    "param_type": "string",
                    "source_pages": ["index.html", "search.html"],
                    "description": "Product ID to display"
                }}
            ],
            "outgoing_connections": [
                {{
                    "target": "cart.html",
                    "params": {{}},
                    "trigger": "View cart after adding item"
                }}
            ],
            "access_methods": [
                {{
                    "type": "url_param",
                    "location": "content",
                    "description": "Accessed via product ID parameter"
                }}
            ]
        }}
    ],
    "header_links": [
        {{
            "text": "Home",
            "url": "index.html",
            "description": "Homepage"
        }},
        {{
            "text": "Products",
            "url": "products.html",
            "description": "All products"
        }},
        {{
            "text": "Cart",
            "url": "cart.html",
            "description": "Shopping cart"
        }}
    ],
    "footer_links": [
        {{
            "text": "About",
            "url": "about.html",
            "description": "About us"
        }},
        {{
            "text": "Contact",
            "url": "contact.html",
            "description": "Contact information"
        }},
        {{
            "text": "Privacy",
            "url": "privacy.html",
            "description": "Privacy policy"
        }}
    ]
}}

IMPORTANT:
- Ensure all interfaces are assigned to appropriate pages
- Use URL parameters for navigation, not localStorage for page data
- All pages in header_links and footer_links must exist in the pages list
- Consider the complete user journey through the tasks
- System state (cart, session, etc.) is managed automatically through localStorage
- CRITICAL: You MUST preserve the exact primary_functions from the primary architecture
- DO NOT add, remove, or modify any primary_functions - keep them EXACTLY as provided
- You can elaborate on the description but primary_functions must remain unchanged
"""
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Design Website Architecture",
                prompt,
                additional_args={
                    "model": "gpt-4",
                    "temperature": 0.7
                }
            )

        try:
            # Call LLM to generate architecture
            messages = [{"role": "user", "content": prompt}]
            response, usage_info = await call_openai_api_json_async(
                messages,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    "Design Website Architecture",
                    success=True,
                    response=response,
                    usage_info=usage_info,
                    stage="Design Architecture",
                    call_id=call_id
                )
            
            # Parse response
            if isinstance(response, str):
                architecture_data = json.loads(response)
            else:
                architecture_data = response
            
            # Validate and create architecture object
            architecture = self._validate_architecture(architecture_data)
            
            # Log summary
            page_count = len(architecture.pages)
            interface_count = sum(len(p.get("assigned_interfaces", [])) for p in architecture.pages)
            self.logger.log_info(f"✅ Designed {page_count} pages with {interface_count} interface assignments")
            
            self.logger.end_stage("Design Architecture")
            
            return architecture
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to design architecture: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
            # Log failed API response
            if self.logger:
                self.logger.log_api_response(
                    "Design Website Architecture",
                    success=False,
                    error=str(e),
                    stage="Design Architecture",
                    call_id=call_id
                )
            self.logger.end_stage("Design Architecture")
            raise
    
    def _prepare_task_summary(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare a summary of tasks for the prompt"""
        summary = []
        for task in tasks:
            # Steps are already strings, not dicts with 'description' field
            task_info = {
                "name": task.get("name", ""),
                "description": task.get("description", ""),
                "steps": task.get("steps", [])  # steps are already strings
            }
            summary.append(task_info)
        return summary
    
    def _prepare_interface_summary(self, interfaces: Any) -> List[Dict[str, Any]]:
        """Prepare a summary of interfaces for the prompt"""
        # Handle both dict with 'interfaces' key and direct list
        if isinstance(interfaces, dict) and "interfaces" in interfaces:
            interface_list = interfaces["interfaces"]
        elif isinstance(interfaces, list):
            interface_list = interfaces
        else:
            interface_list = []
        
        summary = []
        for interface in interface_list:
            interface_info = {
                "name": interface.get("name", ""),
                "description": interface.get("description", ""),
                "parameters": [p.get("name", "") for p in interface.get("parameters", [])],
                "returns": interface.get("returns", {}),  # Include returns field
                "relatedTasks": interface.get("relatedTasks", [])
            }
            summary.append(interface_info)
        return summary
    
    def _prepare_data_summary(self, data_models: Any) -> List[Dict[str, Any]]:
        """Prepare a complete summary of data models for the prompt"""
        # Handle both dict with 'entities' key and direct list
        if isinstance(data_models, dict) and "entities" in data_models:
            model_list = data_models["entities"]
        elif isinstance(data_models, list):
            model_list = data_models
        else:
            model_list = []
        
        # Return complete data model structures instead of just names
        summary = []
        for model in model_list:
            model_info = {
                "name": model.get("name", ""),
                "fields": model.get("fields", [])
            }
            summary.append(model_info)
        return summary
    
    def _validate_architecture(self, architecture_data: Dict[str, Any]) -> WebsiteArchitecture:
        """Validate and create architecture object"""
        # Ensure required fields exist
        if "all_pages" not in architecture_data:
            architecture_data["all_pages"] = []
        if "pages" not in architecture_data:
            architecture_data["pages"] = []
        if "header_links" not in architecture_data:
            architecture_data["header_links"] = []
        if "footer_links" not in architecture_data:
            architecture_data["footer_links"] = []
        
        # Validate page count
        if len(architecture_data["pages"]) > self.max_pages:
            self.logger.log_warning(f"Architecture has {len(architecture_data['pages'])} pages, exceeding max {self.max_pages}")
        
        # Ensure all required fields in pages
        for page in architecture_data["pages"]:
            if "incoming_params" not in page:
                page["incoming_params"] = []
            if "outgoing_connections" not in page:
                page["outgoing_connections"] = []
            if "assigned_interfaces" not in page:
                page["assigned_interfaces"] = []
            if "primary_functions" not in page:
                page["primary_functions"] = []
            if "access_methods" not in page:
                page["access_methods"] = []
        
        return WebsiteArchitecture(**architecture_data)
    
    def generate_architecture_summary(self, architecture: WebsiteArchitecture) -> str:
        """Generate a human-readable summary of the architecture"""
        lines = []
        lines.append("=== Website Architecture Summary ===\n")
        
        # Page summary
        lines.append(f"Total Pages: {len(architecture.pages)}")
        lines.append("\nPages:")
        for page in architecture.pages:
            lines.append(f"  - {page['name']} ({page['filename']})")
            if page.get('assigned_interfaces'):
                lines.append(f"    Interfaces: {', '.join(page['assigned_interfaces'])}")
            if page.get('incoming_params'):
                params = [p['param_name'] for p in page['incoming_params']]
                lines.append(f"    Incoming params: {', '.join(params)}")
        
        # Navigation summary
        lines.append(f"\nHeader Links: {len(architecture.header_links)}")
        for link in architecture.header_links:
            lines.append(f"  - {link['text']} -> {link['url']}")
        
        lines.append(f"\nFooter Links: {len(architecture.footer_links)}")
        for link in architecture.footer_links:
            lines.append(f"  - {link['text']} -> {link['url']}")
        
        return "\n".join(lines)


if __name__ == "__main__":
    # Test the architecture designer
    print("Testing TDD Architecture Designer...")
    
    # Sample data for testing
    sample_tasks = [
        {
            "name": "Search for a Product and Add to Cart",
            "description": "User searches for a product and adds it to cart",
            "steps": [
                {"description": "Search for product"},
                {"description": "View product details"},
                {"description": "Add to cart"}
            ]
        }
    ]
    
    sample_interfaces = [
        {
            "name": "searchProducts",
            "description": "Search for products",
            "parameters": [{"name": "query"}],
            "relatedTasks": ["task_1"]
        },
        {
            "name": "getProductDetails",
            "description": "Get product details",
            "parameters": [{"name": "productId"}],
            "relatedTasks": ["task_1"]
        },
        {
            "name": "addToCart",
            "description": "Add item to cart",
            "parameters": [{"name": "productId"}, {"name": "quantity"}],
            "relatedTasks": ["task_1"]
        }
    ]
    
    sample_data_models = [
        {"name": "Product"},
        {"name": "Cart"},
        {"name": "User"}
    ]
    
    designer = TDDArchitectureDesigner()
    architecture = designer.design_architecture(
        sample_tasks,
        sample_interfaces,
        sample_data_models,
        "shopping_website"
    )
    
    # Print summary
    summary = designer.generate_architecture_summary(architecture)
    print(summary)