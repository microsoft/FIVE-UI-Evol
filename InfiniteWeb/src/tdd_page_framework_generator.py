"""
TDD Page Framework Generator Module

This module generates a unified HTML framework with header/footer
and corresponding CSS based on architecture and design analysis.
"""

import os
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from llm_caller import call_openai_api_json_async, call_openai_with_image_json_async
from tdd_logger_module import TDDLogger


@dataclass
class PageFramework:
    """Page framework with header/footer"""
    framework_html: str  # Complete HTML framework with header/footer
    framework_css: str   # CSS styles for the framework


class TDDPageFrameworkGenerator:
    """
    Generates page framework with header/footer based on architecture and design
    """

    def __init__(self, logger: Optional[TDDLogger] = None,
                 model: str = None, reasoning_effort: str = "medium"):
        """
        Initialize the Page Framework Generator

        Args:
            logger: Optional TDDLogger instance
            model: Model to use for LLM calls
            reasoning_effort: Reasoning effort level
        """
        self.logger = logger or TDDLogger()
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def generate_framework(self,
                                architecture: Any,
                                design_analysis: Dict[str, Any],
                                website_type: str,
                                design_image_path: str) -> PageFramework:
        """
        Generate HTML framework with header/footer and CSS
        
        Args:
            architecture: Website architecture with header_links and footer_links
            design_analysis: Visual design analysis results
            website_type: Type of website
            design_image_path: Path to design image for visual reference (REQUIRED)
            
        Returns:
            PageFramework object with HTML and CSS
            
        Raises:
            ValueError: If design_image_path is not provided or file doesn't exist
        """
        self.logger.start_stage("Generate Page Framework")
        self.logger.log_info(f"🏗️ Generating page framework for {website_type}...")
        
        # Validate design image path
        if not design_image_path:
            error_msg = "Design image path is required for framework generation"
            self.logger.log_error(error_msg)
            raise ValueError(error_msg)
        
        if not os.path.exists(design_image_path):
            error_msg = f"Design image not found at: {design_image_path}"
            self.logger.log_error(error_msg)
            raise ValueError(error_msg)
        
        # Extract navigation links
        header_links = self._extract_links(architecture, 'header_links')
        footer_links = self._extract_links(architecture, 'footer_links')

        # Extract access_methods for pages with special navigation (avatar, user menu, etc.)
        special_access_pages = self._extract_special_access_pages(architecture)

        # Prepare design context
        design_context = self._prepare_design_context(design_analysis)
        
        self.logger.log_info(f"📸 Using design image for framework generation: {design_image_path}")
        
        # Build prompt for vision-based generation
        prompt = self._build_framework_prompt_with_vision(
            website_type,
            header_links,
            footer_links,
            design_context,
            special_access_pages
        )
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Generate Page Framework (Vision)",
                prompt,
                additional_args={"with_image": True},
                stage="Generate Page Framework"
            )

        result, usage_info = await call_openai_with_image_json_async(
            prompt,
            design_image_path,  # Pass the file path directly
            model=self.model,
            reasoning_effort=self.reasoning_effort
        )
        
        # Log successful API response  
        if self.logger:
            self.logger.log_api_response(
                "Generate Page Framework (Vision)",
                success=True,
                response=result,
                usage_info=usage_info,
                stage="Generate Page Framework",
                call_id=call_id
            )
        
        try:
            # Parse JSON result if it's a string
            if isinstance(result, str):
                result = json.loads(result)
            
            # Create PageFramework object
            framework = PageFramework(
                framework_html=result.get("framework_html", ""),
                framework_css=result.get("framework_css", "")
            )
            
            self.logger.log_info("✅ Successfully generated page framework")
            self.logger.end_stage("Generate Page Framework")
            
            return framework
            
        except Exception as e:
            import traceback
            self.logger.log_error(f"Failed to generate page framework: {str(e)}")
            self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
            # Log failed API response
            if self.logger:
                self.logger.log_api_response(
                    "Generate Page Framework (Vision)",
                    success=False,
                    error=str(e),
                    stage="Generate Page Framework",
                    call_id=call_id
                )
            self.logger.end_stage("Generate Page Framework")
            raise
    
    def _extract_links(self, architecture: Any, link_type: str) -> List[Dict[str, str]]:
        """Extract header or footer links from architecture"""
        if hasattr(architecture, link_type):
            return getattr(architecture, link_type)
        elif isinstance(architecture, dict):
            return architecture.get(link_type, [])
        return []

    def _extract_special_access_pages(self, architecture: Any) -> List[Dict[str, Any]]:
        """Extract pages with special access methods (avatar, user menu, etc.)"""
        special_pages = []

        # Get pages from architecture
        if hasattr(architecture, 'pages'):
            pages = architecture.pages
        elif isinstance(architecture, dict):
            pages = architecture.get('pages', [])
        else:
            return []

        for page in pages:
            access_methods = page.get('access_methods', [])
            for method in access_methods:
                location = str(method.get('location', '')).lower()
                # Check for special access types that need UI elements
                if any(keyword in location for keyword in ['avatar', 'user', 'dropdown', 'menu']):
                    special_pages.append({
                        'page_name': page.get('name', ''),
                        'filename': page.get('filename', ''),
                        'access_location': method.get('location', ''),
                        'access_description': method.get('description', ''),
                        'access_type': method.get('type', '')
                    })
                    break  # Only add once per page

        return special_pages
    
    def _prepare_design_context(self, design_analysis: Any) -> str:
        """Prepare design context from analysis results"""
        if not design_analysis:
            return "No design analysis available. Use modern, professional design."
        
        context_parts = []
        
        # Extract key design elements (handle both dict and dataclass)
        if hasattr(design_analysis, 'visual_features') and design_analysis.visual_features:
            visual = design_analysis.visual_features
            context_parts.append(f"Visual Style: {visual.get('overall_style', 'Modern')}")
        elif isinstance(design_analysis, dict) and "visual_features" in design_analysis:
            visual = design_analysis["visual_features"]
            context_parts.append(f"Visual Style: {visual.get('overall_style', 'Modern')}")
        
        if hasattr(design_analysis, 'color_scheme') and design_analysis.color_scheme:
            context_parts.append(f"Color Scheme: {json.dumps(design_analysis.color_scheme, indent=2)}")
        elif isinstance(design_analysis, dict) and "color_scheme" in design_analysis:
            context_parts.append(f"Color Scheme: {json.dumps(design_analysis['color_scheme'], indent=2)}")
        
        if hasattr(design_analysis, 'typography') and design_analysis.typography:
            context_parts.append(f"Typography: {json.dumps(design_analysis.typography, indent=2)}")
        elif isinstance(design_analysis, dict) and "typography" in design_analysis:
            context_parts.append(f"Typography: {json.dumps(design_analysis['typography'], indent=2)}")
        
        if hasattr(design_analysis, 'spacing_system') and design_analysis.spacing_system:
            context_parts.append(f"Spacing: {json.dumps(design_analysis.spacing_system, indent=2)}")
        elif isinstance(design_analysis, dict) and "spacing_system" in design_analysis:
            context_parts.append(f"Spacing: {json.dumps(design_analysis['spacing_system'], indent=2)}")
        
        if hasattr(design_analysis, 'ui_patterns') and design_analysis.ui_patterns:
            context_parts.append(f"UI Patterns: {json.dumps(design_analysis.ui_patterns, indent=2)}")
        elif isinstance(design_analysis, dict) and "ui_patterns" in design_analysis:
            context_parts.append(f"UI Patterns: {json.dumps(design_analysis['ui_patterns'], indent=2)}")
        
        return "\n".join(context_parts)
    
    def _build_framework_prompt_with_vision(self,
                                           website_type: str,
                                           header_links: List[Dict[str, str]],
                                           footer_links: List[Dict[str, str]],
                                           design_context: str,
                                           special_access_pages: List[Dict[str, Any]] = None) -> str:
        """Build prompt for vision-based framework generation"""

        # Build special access pages context if any
        special_access_context = ""
        if special_access_pages:
            special_access_context = f"""

Special Access Pages (pages that need additional navigation elements):
{json.dumps(special_access_pages, indent=2)}

For these pages, you MUST add the corresponding UI elements in the header:
- For "avatar header" or "user menu" access: Add a user avatar/icon in the top right corner with dropdown menu linking to these pages
- For "dropdown" access: Add appropriate dropdown navigation
These pages MUST be accessible from the header through a user avatar/dropdown menu.
"""

        prompt = f"""You are a senior web developer. Analyze the provided design image and generate a complete HTML framework with header and footer that matches the visual style, along with comprehensive CSS styling.

Website Type: {website_type}

Header Navigation Links (must include these):
{json.dumps(header_links, indent=2)}

Footer Links (must include these):
{json.dumps(footer_links, indent=2)}
{special_access_context}
Design Analysis Context:
{design_context}

Requirements:
1. ANALYZE THE DESIGN IMAGE to extract:
   - Visual style and aesthetics
   - Color palette (exact colors from the image)
   - Typography choices
   - Layout patterns
   - Spacing and sizing
   - Header/footer design patterns

2. Create a complete HTML framework matching the design:
   - Do NOT include any page-specific content, this is a reusable framework for all pages in the website
   - Only include header, footer, and (optional) global navigation sidebar if and only if it is a persistent site-wide element in the design.
   - Header that matches the design's header style
   - Footer that matches the design's footer style
   - Use the exact navigation links provided above
   - Main content area with id="content"
   - Modern, semantic HTML5 structure

3. Header Requirements:
   - Match the header layout from the design
   - Include all provided header_links
   - Maintain the design's visual style
   - If Special Access Pages are provided, add a user avatar/icon in the top right corner with a dropdown menu containing links to those pages

4. Footer Requirements:
   - Match the footer layout from the design
   - Include all provided footer_links
   - Maintain the design's visual style

5. CSS Requirements:
   - Extract exact colors from the design image
   - Match typography from the design
   - Replicate spacing and sizing
   - Create CSS variables for the design system
   - Ensure pixel-perfect alignment with design
   - If user avatar dropdown is added, include CSS for the dropdown menu (hidden by default, shown on hover/click)

Return JSON format:
{{
    "framework_html": "Complete HTML with header/footer matching the design",
    "framework_css": "CSS that replicates the design's visual style"
}}

**CRITICAL**
- Language: Use English only, even though the design image may be in another language.
- Do NOT include any button or interactive elements that do not have corresponding links provided in header_links, footer_links, or special_access_pages.
- svg file is not allowed in the framework.

IMPORTANT: The framework must visually match the provided design image while using the exact navigation links specified above.
"""
        
        return prompt