"""
TDD Page Generator Module

This module generates HTML pages and CSS styles based on:
- Page designs
- Data dictionary
- SDK interfaces
- Layout designs
- Framework HTML/CSS from previous step
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
from tdd_logger_module import TDDLogger
from llm_caller import call_openai_api_json, call_openai_api_json_async


@dataclass
class GeneratedPage:
    """Generated page with HTML and CSS"""
    filename: str
    html_content: str
    css_content: str


class TDDPageGenerator:
    """
    Generates HTML pages and CSS styles with framework integration
    """

    def __init__(self, logger: TDDLogger = None, max_concurrent: int = 3,
                 model: str = None, reasoning_effort: str = "medium"):
        """
        Initialize the Page Generator

        Args:
            logger: TDDLogger instance
            max_concurrent: Maximum concurrent page generations
            model: Model to use for LLM calls
            reasoning_effort: Reasoning effort level
        """
        self.logger = logger or TDDLogger()
        self.max_concurrent = max_concurrent
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def generate_pages_async(self,
                                  page_designs: List[Dict[str, Any]],
                                  website_type: str,
                                  data_dict: Dict[str, Any],
                                  interfaces: Dict[str, List[Dict[str, Any]]],
                                  page_layouts: Dict[str, Any],
                                  page_framework: Dict[str, Any],
                                  design_analysis: Dict[str, Any] = None,
                                  architecture_pages: Dict[str, Any] = None) -> List[GeneratedPage]:
        """
        Generate all pages asynchronously
        
        Args:
            page_designs: List of page design specifications
            website_type: Type of website
            data_dict: Complete data dictionary/table
            interfaces: Dict mapping page filename to list of interfaces for that page
            page_layouts: Layout designs for each page
            page_framework: Framework HTML and CSS from Step 8
            design_analysis: Visual design analysis results
            
        Returns:
            List of GeneratedPage objects
        """
        self.logger.start_stage("Generate Pages")
        self.logger.log_info(f"📄 Generating {len(page_designs)} pages in parallel...")
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Generate all pages in parallel
        tasks = []
        for page_design in page_designs:
            # Handle both dict and dataclass
            if hasattr(page_design, 'filename'):
                filename = page_design.filename
            else:
                filename = page_design.get('filename', '')
            
            page_layout = page_layouts.get(filename, {})
            # Get page-specific interfaces
            page_interfaces = interfaces.get(filename, [])
            # Get page-specific architecture data (navigation info)
            page_architecture = architecture_pages.get(filename, {}) if architecture_pages else {}
            
            task = self._generate_single_page_async(
                page_design,
                website_type,
                data_dict,
                page_interfaces,  # Pass page-specific interfaces
                page_layout,
                page_framework,
                design_analysis,
                page_architecture,  # Pass page-specific architecture data
                semaphore
            )
            tasks.append(task)
        
        generated_pages = await asyncio.gather(*tasks)
        
        self.logger.log_info(f"✅ Successfully generated {len(generated_pages)} pages")
        self.logger.end_stage("Generate Pages")
        
        return generated_pages
    
    async def _generate_single_page_async(self,
                                         page_design: Any,  # Can be dict or dataclass
                                         website_type: str,
                                         data_dict: Dict[str, Any],
                                         page_interfaces: List[Dict[str, Any]],
                                         page_layout: Dict[str, Any],
                                         page_framework: Dict[str, Any],
                                         design_analysis: Dict[str, Any],
                                         page_architecture: Dict[str, Any],
                                         semaphore: asyncio.Semaphore) -> GeneratedPage:
        """
        Generate a single page with semaphore control
        """
        async with semaphore:
            # Handle both dict and dataclass
            if hasattr(page_design, 'filename'):
                filename = page_design.filename
            else:
                filename = page_design.get('filename', 'page.html')
            self.logger.log_info(f"  Generating page: {filename}")
            
            # Step 1: Generate HTML
            html_content = await self._generate_html_async(
                page_design,
                website_type,
                data_dict,
                page_interfaces,  # Use page-specific interfaces
                page_layout,
                page_framework.get('framework_html', ''),
                page_architecture,  # Pass architecture data with navigation info
                design_analysis  # Pass design analysis for UI patterns
            )
            
            # Step 2: Generate CSS based on HTML
            css_content = await self._generate_css_async(
                page_design,
                page_layout,
                design_analysis,
                page_framework.get('framework_css', ''),
                html_content
            )
            
            css_filename = filename.replace('.html', '.css')
            
            return GeneratedPage(
                filename=filename,
                html_content=html_content,
                css_content=css_content
            )
    
    async def _generate_html_async(self,
                                  page_design: Any,  # Can be dict or dataclass
                                  website_type: str,
                                  data_dict: Dict[str, Any],
                                  page_interfaces: List[Dict[str, Any]],
                                  page_layout: Dict[str, Any],
                                  framework_html: str,
                                  page_architecture: Dict[str, Any] = None,
                                  design_analysis: Dict[str, Any] = None) -> str:
        """
        Generate HTML for a single page
        """
        prompt = self._build_html_prompt(
            page_design,
            website_type,
            data_dict,
            page_interfaces,  # Use page-specific interfaces
            page_layout,
            framework_html,
            page_architecture,  # Pass architecture data with navigation info
            design_analysis  # Pass design analysis for UI patterns
        )
        
        # Get page name for logging
        if hasattr(page_design, 'filename'):
            page_name = page_design.filename
        elif isinstance(page_design, dict):
            page_name = page_design.get('filename', 'unknown_page')
        else:
            page_name = 'unknown_page'
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                f"Generate HTML - {page_name}",
                prompt,
                additional_args={"page": page_name},
                stage="Generate Pages"
            )

        messages = [{"role": "user", "content": prompt}]

        try:
            result, usage_info = await call_openai_api_json_async(
                messages,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    f"Generate HTML - {page_name}",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    stage="Generate Pages",
                    call_id=call_id
                )
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to generate HTML for {page_name}: {str(e)}")
                self.logger.log_api_response(
                    f"Generate HTML - {page_name}",
                    success=False,
                    error=str(e),
                    stage="Generate Pages",
                    call_id=call_id
                )
            raise

        if isinstance(result, str):
            result = json.loads(result)

        result_to_process = result.get("html_content", "")
        
        # replace <link rel="stylesheet" href="framework.css"> to empty string
        result_to_process = result_to_process.replace('<link rel="stylesheet" href="framework.css">', '')

        # replace <link rel="stylesheet" href="styles.css"> to empty string
        result_to_process = result_to_process.replace('<link rel="stylesheet" href="styles.css">', '')

        return result_to_process
    
    async def _generate_css_async(self,
                                 page_design: Any,  # Can be dict or dataclass
                                 page_layout: Dict[str, Any],
                                 design_analysis: Dict[str, Any],
                                 framework_css: str,
                                 html_content: str) -> str:
        """
        Generate CSS for a single page based on its HTML
        """
        prompt = self._build_css_prompt(
            page_design,
            page_layout,
            design_analysis,
            framework_css,
            html_content
        )
        
        # Get page name for logging
        if hasattr(page_design, 'filename'):
            page_name = page_design.filename
        elif isinstance(page_design, dict):
            page_name = page_design.get('filename', 'unknown_page')
        else:
            page_name = 'unknown_page'
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                f"Generate CSS - {page_name}",
                prompt,
                additional_args={"page": page_name},
                stage="Generate Pages"
            )

        messages = [{"role": "user", "content": prompt}]

        try:
            result, usage_info = await call_openai_api_json_async(
                messages,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )

            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    f"Generate CSS - {page_name}",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    stage="Generate Pages",
                    call_id=call_id
                )
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Failed to generate CSS for {page_name}: {str(e)}")
                self.logger.log_api_response(
                    f"Generate CSS - {page_name}",
                    success=False,
                    error=str(e),
                    stage="Generate Pages",
                    call_id=call_id
                )
            raise

        if isinstance(result, str):
            result = json.loads(result)

        return result.get("css_content", "")
    
    def _build_html_prompt(self,
                          page_design: Any,  # Can be dict or dataclass
                          website_type: str,
                          data_dict: Dict[str, Any],
                          page_interfaces: List[Dict[str, Any]],
                          page_layout: Dict[str, Any],
                          framework_html: str,
                          page_architecture: Dict[str, Any] = None,
                          design_analysis: Dict[str, Any] = None) -> str:
        """Build prompt for HTML generation"""

        # Convert dataclass to dict if needed
        from dataclasses import asdict, is_dataclass
        if is_dataclass(page_design):
            page_design_dict = asdict(page_design)
            filename = page_design.filename
        else:
            page_design_dict = page_design
            filename = page_design.get('filename', 'index.html')

        # Get the CSS filename
        css_filename = filename.replace('.html', '.css')

        # Extract UI patterns from design analysis for HTML structure guidance
        ui_patterns_section = ""
        if design_analysis:
            da_dict = asdict(design_analysis) if is_dataclass(design_analysis) else design_analysis
            ui_patterns = da_dict.get('ui_patterns', [])
            visual_style = da_dict.get('visual_features', {}).get('overall_style', 'Modern')

            if ui_patterns:
                ui_patterns_section = f"""

UI Component Patterns (from design mockup - MUST influence HTML structure):
Overall Visual Style: {visual_style}
{json.dumps(ui_patterns, indent=2)}
"""

        prompt = f"""You are a senior web developer. Generate the main content HTML for a {website_type} website page with UI JavaScript.

Page Information:
{json.dumps(page_design_dict, indent=2)}

Navigation Information:
{json.dumps(page_architecture if page_architecture else {
    "incoming_params": [],
    "outgoing_connections": [],
    "access_methods": []
}, indent=2)}

Framework HTML (use this as the base structure):
{framework_html}

Data Dictionary (available data):
{json.dumps(data_dict, indent=2)}

Page-Specific SDK Interfaces:
{json.dumps(page_interfaces, indent=2)}

Page Layout Design:
{json.dumps(asdict(page_layout) if is_dataclass(page_layout) else page_layout, indent=2)}
{ui_patterns_section}
Requirements:
1. The framework HTML already contains header, footer, and basic structure
2. Generate ONLY the content that goes inside the <main id="content"> section
3. Do NOT regenerate the entire HTML structure
4. Call interfaces as WebsiteSDK.functionName() - they are SYNCHRONOUS, return objects directly (no .then())
5. Include CSS link: <link rel="stylesheet" href="{css_filename}"> (for this page: {css_filename})
6. Include script tag: <script src="business_logic.js"></script> for the SDK functions
7. Use URL parameters for navigation based on Navigation Information:
   - Handle incoming_params: Extract and use URL parameters this page expects
   - Implement outgoing_connections: Navigate to other pages with correct parameters
8. **CRITICAL: Follow the Page Layout Design specifications**:
   - Use layout_strategies to determine overall page structure (columns, sidebars, content flow)
   - Use component_layouts for each component's position and spatial behavior
   - The overall_description provides the complete layout picture
9. Ensure semantic HTML5 structure
10. Add appropriate data attributes for JavaScript interaction:
    - data-populate="xxx" for elements that need data
    - data-action="xxx" for interactive elements
    - data-component="xxx" for component identification
    - When filtering, grouping, or comparing data by enum fields (fields with "type": "enum"
      in data models or interface definitions), use the exact values from the enum's "values" list in lowercase_snake_case.
      Do NOT invent synonyms or alternate spellings. Enum fields are stored as plain strings in localStorage.
11. Use the data dictionary structure for any data references
12. Website should provide default response when no expected parameters are provided
13. In JavaScript, render any multi-line HTML/text using ES6 template literals (`...`) or DOM APIs (never multi-line ' or " strings or backslash continuations), escape interpolations, and ensure the script parses without syntax errors.
14. **Apply UI Component Patterns to HTML structure** (if provided above):
    - Follow the visual_description for class naming and element styling decisions
    - Follow the structural_pattern for HTML element choices and nesting
    - Different design styles should result in visibly different HTML structures:
      * Skeuomorphic designs → bordered containers, table-like structures, dense spacing
      * Modern minimalist → shadow-based separation, flexbox/grid layouts, generous spacing
      * Early-web/traditional → simple structures, border separators, compact forms
15. **Page Chrome vs Business Data**:
    - Page chrome = decorative content that does NOT display data model entities: hero banner titles, site taglines, about-us paragraphs, decorative background images. Generate these as **static inline HTML** directly. Do NOT call SDK interfaces for them.
    - Business data = content that displays data model entity instances: product lists, category menus, team members, testimonials, schedules, search results, table data, form submissions. These MUST be fetched via SDK interfaces, even if displayed without user interaction.
    - When including decorative images, use placeholder URLs like "https://picsum.photos/1200/500" — they will be replaced by the resource pipeline later.
16. **Entity Reference Parameters - CRITICAL for User Experience**:
    For interface parameters that have "entityReference" metadata (e.g., {{"entity": "Location", "displayField": "displayName", "valueField": "id"}}):
    a. NEVER use plain text input expecting users to type internal IDs like "loc_1" or "cat_123"
    b. Use <select> dropdown populated with data from the referenced entity:
       ```html
       <select id="fromLocationInput" name="fromLocationId" required>
         <option value="">Select origin city</option>
         <!-- Options populated from Location data in JavaScript -->
       </select>
       ```
    c. In JavaScript, populate options dynamically from localStorage:
       ```javascript
       const locations = JSON.parse(localStorage.getItem('locations') || '[]');
       const select = document.getElementById('fromLocationInput');
       locations.forEach(loc => {{
         const option = document.createElement('option');
         option.value = loc.id;  // Use valueField (id)
         option.textContent = loc.displayName;  // Use displayField (displayName or name)
         select.appendChild(option);
       }});
       ```
    d. For large datasets, consider using <datalist> with autocomplete input instead of <select>
    e. Display the user-friendly field (displayName/name), but submit the internal ID as the value
    f. This applies to ALL parameters with entityReference, such as locationId, categoryId, fromLocationId, toLocationId, etc.

UI JavaScript Requirements:
1. IMPORTANT: Generate UI JavaScript code that connects the HTML with the SDK
2. Add a <script> tag at the end of the body with JavaScript code that:
    a. Initializes the page when DOM is ready
    b. Extracts URL parameters for incoming_params (if any)
    c. Calls SDK methods to fetch data based on data-populate attributes and URL params
    d. Renders the fetched data into the appropriate DOM elements
    e. Sets up event listeners based on data-action attributes
    f. Handles user interactions (clicks, form submissions, etc.)
    g. Implements navigation to other pages with correct parameters (outgoing_connections)
    h. Updates UI state as needed
3. The JavaScript should be generic and driven by data attributes:
    - Find all elements with data-populate and call corresponding SDK methods
    - Find all elements with data-action and bind appropriate event handlers
    - Use WebsiteSDK instance (already available from business_logic.js)
4. Example pattern:
    ```javascript
    document.addEventListener('DOMContentLoaded', function() {{
        // Extract URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const productId = urlParams.get('id'); // For incoming_params

        // Initialize data rendering
        const populateElements = document.querySelectorAll('[data-populate]');
        populateElements.forEach(element => {{
            const dataType = element.dataset.populate;
            // Call SDK method based on dataType and render results
            // Use URL params like productId when needed
        }});

        // Setup event handlers
        const actionElements = document.querySelectorAll('[data-action]');
        actionElements.forEach(element => {{
            const action = element.dataset.action;
            // Bind appropriate event based on action type
            // Navigate with params: window.location.href = 'product.html?id=' + itemId;
        }});
    }});
    ```
5. Ensure the JavaScript handles all the functionality described in the page design
6. Use modern JavaScript (ES6+) but ensure browser compatibility
7. Handle errors gracefully with appropriate user feedback
8. The JavaScript should be self-contained and not require external libraries
9. Always directly call SDK methods as WebsiteSDK.methodName() - do NOT extract methods into separate variables (to avoid losing 'this' context)
10. No method extraction: NOT: const fn = WebsiteSDK.getX; fn(); (forbidden).
11. No destructuring: NOT: const {{ methodName }} = WebsiteSDK; methodName(); (forbidden).
12. Dynamic calls: Use WebsiteSDK[methodName](...) ONLY (never: const f = WebsiteSDK[methodName]; f()).
13. **CRITICAL: Render functions must use the container parameter directly**:
   - When rendering content for data-populate elements, the render function receives the element as a parameter
   - Do NOT call querySelector/getElementById inside the render function to find nested containers
   - The passed container IS the target element - use it directly with container.innerHTML or container.appendChild
   - Example of CORRECT pattern:
     function renderCategories(container, categories) {{
         container.innerHTML = '';  // Clear the passed container directly
         categories.forEach(cat => {{
             const item = document.createElement('li');
             item.textContent = cat.name;
             container.appendChild(item);
         }});
     }}
   - Example of INCORRECT pattern (causes silent failures):
     function renderCategories(container, categories) {{
         const list = container.querySelector('ul');  // WRONG - container might BE the ul
         if (!list) return;  // Silent failure if no nested ul found
         list.innerHTML = '...';
     }}

**CRITICAL SDK USAGE RULE**
- Call Page-Specific SDK Interfaces with positional arguments only (do NOT pass a single object).
- Do NOT call any SDK interfaces not listed in Page-Specific SDK Interfaces.

**CRITICAL URL USAGE**
- Use only relative .html URLs for internal navigation.(e.g., product.html?id=123 instead of /product/123)
- Do not use internal navigation besides the ones specified in outgoing_connections. Use javascript:void(0) instead. (Links already present in the provided framework HTML are not affected by this restriction)

Return JSON format:
{{
    "html_content": "Complete HTML page with framework, content, and UI JavaScript integrated"
}}

The html_content should be the COMPLETE page including:
- The framework structure
- Your generated content in the appropriate areas
- A <script> tag with the UI JavaScript code that makes the page interactive
"""

        return prompt
    
    def _build_css_prompt(self,
                         page_design: Any,  # Can be dict or dataclass
                         page_layout: Dict[str, Any],
                         design_analysis: Dict[str, Any],
                         framework_css: str,
                         html_content: str) -> str:
        """Build prompt for CSS generation"""
        
        # Convert dataclass to dict if needed
        from dataclasses import asdict, is_dataclass
        if is_dataclass(page_design):
            page_design_dict = asdict(page_design)
        else:
            page_design_dict = page_design
        
        prompt = f"""You are a senior web developer. Generate CSS styles for the page based on its HTML structure.

Page Design:
{json.dumps(page_design_dict, indent=2)}

Page Layout:
{json.dumps(asdict(page_layout) if is_dataclass(page_layout) else page_layout, indent=2)}

Design Analysis:
{json.dumps(asdict(design_analysis) if is_dataclass(design_analysis) else design_analysis, indent=2) if design_analysis else "No design analysis available"}

Framework CSS (build upon this):
{framework_css}

Generated HTML (style this content):
{html_content}

Requirements:
1. Include complete framework CSS - no abbreviations or placeholder comments
2. Style the content area and page-specific components
3. Follow the design analysis color scheme and typography
4. Implement the layout specifications (grid, spacing, etc.)
5. Ensure responsive design with proper breakpoints
6. Use CSS variables defined in framework CSS
7. Add hover states and transitions for interactive elements
8. Maintain visual consistency with the framework styles
9. Focus on the unique elements of this page
10. Use modern CSS features (flexbox, grid, custom properties)
11. CRITICAL: Put this at the VERY TOP of css_content exactly:
    [hidden] {{ display: none !important; visibility: hidden !important; }}
12. For any UI that toggles via [hidden] (e.g., #cart-loading, .cart-loading, #cart-toast), set display/visibility only on :not([hidden]) selectors.
    **CRITICAL: NEVER use !important in :not([hidden]) rules** - this allows inline styles like style="display:none" to take precedence for initial hidden state.
    Example:
    #cart-loading:not([hidden]) {{ display: flex; }}  /* NO !important */

Return JSON format:
{{
    "css_content": "Complete CSS including framework styles and new page-specific styles"
}}

The css_content should include both the framework CSS and your additional styles for this specific page.
"""
        
        return prompt
    
    def generate_pages(self,
                      page_designs: List[Dict[str, Any]],
                      website_type: str,
                      data_dict: Dict[str, Any],
                      interfaces: Dict[str, List[Dict[str, Any]]],
                      page_layouts: Dict[str, Any],
                      page_framework: Dict[str, Any],
                      design_analysis: Dict[str, Any] = None,
                      architecture_pages: Dict[str, Any] = None) -> List[GeneratedPage]:
        """
        Synchronous wrapper for page generation
        """
        return asyncio.run(self.generate_pages_async(
            page_designs,
            website_type,
            data_dict,
            interfaces,
            page_layouts,
            page_framework,
            design_analysis,
            architecture_pages
        ))