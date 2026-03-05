"""
TDD Primary Architecture Designer
Creates initial high-level website structure for guiding subsequent design phases
"""

import json
from typing import List, Dict, Any
from dataclasses import dataclass, asdict, field
from tdd_logger_module import TDDLogger
from llm_caller import call_openai_api_json

@dataclass
class PrimaryArchitecture:
    """Primary architecture structure for early planning"""
    all_pages: List[Dict[str, str]]  # List of {name, filename}
    pages: List[Dict[str, Any]]  # Detailed page descriptions with primary functions
    header_links: List[Dict[str, str]] = field(default_factory=list)  # Navigation links in header
    footer_links: List[Dict[str, str]] = field(default_factory=list)  # Navigation links in footer

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


class TDDPrimaryArchitectureDesigner:
    """Designs initial website architecture for early guidance"""
    
    def __init__(self, logger: TDDLogger = None, max_pages: int = 8, model=None, reasoning_effort=None):
        """
        Initialize the primary architecture designer

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
    
    def design_primary_architecture(self, tasks: List[Dict[str, Any]], 
                                   website_type: str) -> PrimaryArchitecture:
        """
        Design primary architecture based on tasks
        
        Args:
            tasks: List of user tasks
            website_type: Type of website
            
        Returns:
            PrimaryArchitecture object
        """
        self.logger.start_stage("Design Primary Architecture")
        self.logger.log_info("🏗️ Designing primary website architecture...")
        
        # Prepare task descriptions for prompt
        task_descriptions = []
        for task in tasks:
            if isinstance(task, dict):
                task_name = task.get('name', 'Unknown Task')
                task_steps = task.get('steps', [])
            else:
                task_name = task.name if hasattr(task, 'name') else 'Unknown Task'
                task_steps = task.steps if hasattr(task, 'steps') else []
            
            steps_text = "\n   ".join([f"- {step}" for step in task_steps])
            task_descriptions.append(f"Task: {task_name}\n   Steps:\n   {steps_text}")
        
        tasks_text = "\n\n".join(task_descriptions)
        
        prompt = f"""Design a complete website architecture for a {website_type}.

User Tasks that the website must support:
{tasks_text}

Based on these tasks, design a COMPLETE architecture with ALL pages needed:
1. All pages needed for the website (maximum {self.max_pages} pages)
2. Primary functions each page should provide
3. Header navigation links (main navigation in header)
4. Footer navigation links (secondary navigation in footer)
5. Keep it simple and focused on user needs
6. DO NOT include authentication/login pages
7. DO NOT consider multi-user scenarios
8. This is for single-user use only

Return JSON format:
{{
    "all_pages": [
        {{ "name": "Home", "filename": "index.html" }},
        {{ "name": "Category", "filename": "category.html" }},
        {{ "name": "Product Detail", "filename": "product.html" }},
        {{ "name": "About", "filename": "about.html" }}
    ],
    "pages": [
        {{
            "name": "Page Display Name",
            "filename": "page.html",
            "description": "Brief description of page purpose",
            "primary_functions": [
                "Function 1 this page provides",
                "Function 2 this page provides"
            ]
        }}
    ],
    "header_links": [
        {{ "text": "Home", "url": "index.html", "description": "Homepage" }},
        {{ "text": "Business", "url": "category.html?categoryId=business", "description": "Business category" }},
        {{ "text": "Home & Garden", "url": "category.html?categoryId=home_garden", "description": "Home and garden category" }}
    ],
    "footer_links": [
        {{ "text": "About", "url": "about.html", "description": "About us page" }}
    ]
}}

Requirements:
- Include all pages needed to complete the user tasks (up to {self.max_pages} pages maximum)
- Each page should have clear, focused responsibilities
- Use descriptive filenames (e.g., index.html, products.html, cart.html)
- Primary functions should be high-level user actions, not technical details
- Ensure all task steps can be completed with the designed pages

Header/Footer Link Guidelines:
- header_links: Primary navigation visible on all pages (main sections, categories)
- footer_links: Secondary navigation (about, contact, policies, etc.)
- For category/filter pages, use simple IDs without prefixes: categoryId=business (NOT cat_business)
- For entity detail pages, use simple placeholders: productId=123, articleId=456
- Keep parameter values simple and lowercase when representing categories or types
- ALL URL parameter values MUST use lowercase_snake_case format: categoryId=security_antivirus (NOT security-antivirus), careType=in_home_care (NOT in-home-care)

**CRITICAL**
- index.html must be contained and as the homepage
- filename MUST be a valid filesystem name - NO query parameters ("?", "=") in filename field
- For dynamic pages (like categories), use ONE filename in all_pages (e.g., "category.html"),
  but multiple URLs with query parameters in header_links (e.g., "category.html?categoryId=movies")
- All links in header_links and footer_links must use filenames defined in all_pages
  (the base filename before "?" must exist in all_pages)
"""
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Design Primary Architecture",
                prompt,
                additional_args={"website_type": website_type}
            )

        # Call LLM to design architecture
        try:
            response, usage = call_openai_api_json(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    "Design Primary Architecture",
                    success=True,
                    response=response,
                    usage_info=usage,
                    call_id=call_id
                )
            
            # Parse response
            # Extract JSON from response
            if isinstance(response, str):
                json_str = response
            else:
                json_str = json.dumps(response)
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            
            architecture_data = json.loads(json_str.strip())
            
            # Validate structure
            if 'all_pages' not in architecture_data or 'pages' not in architecture_data:
                raise ValueError("Missing required fields in architecture response")
            
            # Create PrimaryArchitecture object
            primary_architecture = PrimaryArchitecture(
                all_pages=architecture_data['all_pages'],
                pages=architecture_data['pages'],
                header_links=architecture_data.get('header_links', []),
                footer_links=architecture_data.get('footer_links', [])
            )

            self.logger.log_info(f"✅ Designed primary architecture with {len(primary_architecture.all_pages)} pages")
            self.logger.log_info(f"   Header links: {len(primary_architecture.header_links)}, Footer links: {len(primary_architecture.footer_links)}")
            
            # Log page summary
            for page in primary_architecture.pages:
                functions_count = len(page.get('primary_functions', []))
                self.logger.log_info(f"  - {page['name']} ({page['filename']}): {functions_count} primary functions")
            
            self.logger.end_stage("Design Primary Architecture")
            return primary_architecture
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.log_error(f"Failed to parse primary architecture response: {e}")
            self.logger.log_debug(f"Response was: {response}")
            # Log failed API response
            if self.logger:
                self.logger.log_api_response(
                    "Design Primary Architecture",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            
            # Return a minimal default architecture
            default_architecture = PrimaryArchitecture(
                all_pages=[
                    {"name": "Home Page", "filename": "index.html"},
                    {"name": "Products", "filename": "products.html"}
                ],
                pages=[
                    {
                        "name": "Home Page",
                        "filename": "index.html",
                        "description": "Main landing page",
                        "primary_functions": ["Display website content", "Navigate to other pages"]
                    },
                    {
                        "name": "Products",
                        "filename": "products.html",
                        "description": "Product listing page",
                        "primary_functions": ["Show products", "Allow product interaction"]
                    }
                ],
                header_links=[
                    {"text": "Home", "url": "index.html", "description": "Homepage"},
                    {"text": "Products", "url": "products.html", "description": "Product listing"}
                ],
                footer_links=[]
            )
            
            self.logger.log_warning("Using default primary architecture due to parsing error")
            self.logger.end_stage("Design Primary Architecture")
            return default_architecture
    
    def generate_architecture_summary(self, architecture: PrimaryArchitecture) -> str:
        """
        Generate a summary of the primary architecture

        Args:
            architecture: PrimaryArchitecture object

        Returns:
            Summary string
        """
        lines = ["=== Primary Architecture Summary ==="]
        lines.append(f"Total Pages: {len(architecture.all_pages)}")
        lines.append(f"Header Links: {len(architecture.header_links)}")
        lines.append(f"Footer Links: {len(architecture.footer_links)}")
        lines.append("")

        for page in architecture.pages:
            lines.append(f"📄 {page['name']} ({page['filename']})")
            lines.append(f"   {page.get('description', 'No description')}")

            if 'primary_functions' in page and page['primary_functions']:
                lines.append("   Primary Functions:")
                for func in page['primary_functions']:
                    lines.append(f"   - {func}")
            lines.append("")

        if architecture.header_links:
            lines.append("🔗 Header Links:")
            for link in architecture.header_links:
                lines.append(f"   - {link.get('text', 'Unknown')}: {link.get('url', '')}")
            lines.append("")

        return "\n".join(lines)