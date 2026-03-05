"""
TDD Layout Designer Module

This module designs page layouts based on visual design analysis and page functionality,
creating detailed layout specifications for each page including grid systems, spacing,
component positioning, and responsive breakpoints.
"""

import json
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import asdict

from tdd_logger_module import TDDLogger
from tdd_page_designer import PageDesign, PageLayout
from llm_caller import call_openai_api_json


class TDDLayoutDesigner:
    """
    Designs page layouts based on design analysis and page functionality
    """
    
    def __init__(self,
                 logger: Optional[TDDLogger] = None,
                 max_concurrent: int = 3,
                 model=None,
                 reasoning_effort=None):
        """
        Initialize the TDD Layout Designer

        Args:
            logger: TDD logger instance
            max_concurrent: Maximum concurrent layout designs
            model: Model to use (e.g., "gpt-4.1", "gpt-5", None for default)
            reasoning_effort: Reasoning effort level (e.g., "low", "medium", "high")
        """
        self.logger = logger or TDDLogger()
        self.max_concurrent = max_concurrent
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def design_layouts(self,
                                  page_designs: List[PageDesign],
                                  design_analysis: Dict[str, Any],
                                  data_models: Dict[str, Any],
                                  website_type: str) -> List[PageDesign]:
        """
        Design layouts for all pages based on visual analysis
        
        Args:
            page_designs: List of page designs from Step 5
            design_analysis: Visual design analysis from Step 6
            data_models: Enhanced data models
            website_type: Type of website
            
        Returns:
            Updated page designs with layout information
        """
        self.logger.start_stage("Design Page Layouts", "frontend")
        self.logger.log_info(f"🎨 Designing layouts for {len(page_designs)} pages...")
        
        # Prepare design context
        design_context = self._prepare_design_context(design_analysis)
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # Design layouts in parallel
        tasks = [
            self._design_single_layout_async(
                page_design, design_context, data_models, website_type, semaphore
            )
            for page_design in page_designs
        ]
        
        updated_pages = await asyncio.gather(*tasks)
        
        self.logger.log_info(f"✅ Successfully designed layouts for {len(updated_pages)} pages")
        self.logger.end_stage("Design Page Layouts")
        return updated_pages
    
    def _prepare_design_context(self, design_analysis: Dict[str, Any]) -> Dict:
        """
        Prepare design context from analysis results

        Args:
            design_analysis: Design analysis from Step 6

        Returns:
            Formatted design context for layout generation
        """
        # Handle both dict and object formats
        if hasattr(design_analysis, '__dict__'):
            design_analysis = design_analysis.__dict__

        layout_chars = design_analysis.get('layout_characteristics', {})

        context = {
            "visual_style": design_analysis.get('visual_features', {}).get('overall_style', 'Modern'),
            "color_scheme": design_analysis.get('color_scheme', {}),
            "typography": design_analysis.get('typography', {}),
            "spacing_system": design_analysis.get('spacing_system', {}),
            "layout_characteristics": layout_chars,
            "ui_patterns": design_analysis.get('ui_patterns', []),
            "interaction_hints": design_analysis.get('interaction_hints', []),
            # Extract detailed layout descriptions from design analysis
            "layout_from_design": {
                "content_arrangement": layout_chars.get('content_arrangement', ''),
                "space_allocation": layout_chars.get('space_allocation', ''),
                "content_density": layout_chars.get('content_density', ''),
                "visual_flow": layout_chars.get('visual_flow', '')
            }
        }
        return context

    def _extract_px_value(self, value: str, default: str) -> str:
        """
        Extract first pixel value from a string or return default

        Args:
            value: String that may contain pixel values (e.g., "24px-32px margin")
            default: Default value if no pixel value found

        Returns:
            Pixel value string (e.g., "24px")
        """
        import re
        if not value:
            return default
        match = re.search(r'(\d+)\s*px', str(value))
        if match:
            return f"{match.group(1)}px"
        return default

    def _extract_breakpoints(self, responsive_hints: List[str]) -> Dict[str, str]:
        """
        Extract responsive breakpoints from hints or return defaults

        Args:
            responsive_hints: List of responsive design hints from analysis

        Returns:
            Dict with mobile, tablet, desktop breakpoints
        """
        import re
        breakpoints = {
            "mobile": "768px",
            "tablet": "1024px",
            "desktop": "1440px"
        }
        for hint in responsive_hints:
            hint_lower = hint.lower()
            if 'mobile' in hint_lower:
                match = re.search(r'(\d+)\s*px', hint_lower)
                if match:
                    breakpoints['mobile'] = f"{match.group(1)}px"
            elif 'tablet' in hint_lower:
                match = re.search(r'(\d+)\s*px', hint_lower)
                if match:
                    breakpoints['tablet'] = f"{match.group(1)}px"
            elif 'desktop' in hint_lower:
                match = re.search(r'(\d+)\s*px', hint_lower)
                if match:
                    breakpoints['desktop'] = f"{match.group(1)}px"
        return breakpoints
    
    def _design_single_layout(self,
                             page_design: PageDesign,
                             design_context: Dict,
                             data_models: Dict,
                             website_type: str) -> PageDesign:
        """
        Design layout for a single page
        
        Args:
            page_design: Page design to add layout to
            design_context: Visual design context
            data_models: Data models
            website_type: Type of website
            
        Returns:
            Updated page design with layout
        """
        filename = page_design.filename
        self.logger.log_info(f"  Designing layout for: {filename}")
        
        # Build prompt
        prompt = self._build_layout_prompt(page_design, design_context, data_models, website_type)
        
        # Call LLM with logging
        try:
            # Log the API call and get call_id
            call_id = self.logger.log_api_call(
                "design_page_layout",
                prompt,
                {"page": filename}
            )

            response_text, usage_info = call_openai_api_json(
                [{"role": "user", "content": prompt}],
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log the response
            self.logger.log_api_response(
                "design_page_layout",
                success=(response_text is not None),
                response=response_text,
                usage_info=usage_info,
                call_id=call_id
            )
            
            if response_text is None:
                raise Exception("API call returned None")
            
            response = json.loads(response_text)

            # Parse response
            interpreted_strategy = response.get("interpreted_layout_strategy", {})
            overall_description = response.get("overall_layout_description", "")
            component_layouts = response.get("component_layouts", [])
            
            # Extract layout parameters from design context
            spacing_system = design_context.get('spacing_system', {})
            layout_chars = design_context.get('layout_characteristics', {})

            # Build spacing rules from design analysis with fallback defaults
            spacing_rules = {
                "section_padding": self._extract_px_value(spacing_system.get('section_margin', ''), '64px'),
                "component_gap": self._extract_px_value(spacing_system.get('component_padding', ''), '24px'),
                "content_margin": self._extract_px_value(spacing_system.get('base_unit', ''), '16px')
            }

            # Extract responsive breakpoints
            responsive_breakpoints = self._extract_breakpoints(layout_chars.get('responsive_hints', []))

            # Create PageLayout with design-extracted values
            page_layout = PageLayout(
                grid_system=layout_chars.get('grid_system', '12-column'),
                spacing_rules=spacing_rules,
                layout_pattern=interpreted_strategy.get("content_arrangement", ""),
                visual_hierarchy=[],
                responsive_breakpoints=responsive_breakpoints,
                layout_strategies=interpreted_strategy,
                overall_description=overall_description,
                component_layouts=component_layouts
            )
            
            # Update component positions
            for component in page_design.components:
                # Find corresponding layout description
                comp_layout = next(
                    (cl for cl in component_layouts if cl["id"] == component.id),
                    None
                )
                if comp_layout:
                    component.position = comp_layout
            
            # Update page design with layout
            page_design.layout = page_layout
            
            return page_design
            
        except Exception as e:
            self.logger.log_error(f"Failed to design layout for {filename}: {e}")
            # Return original page design without layout
            return page_design
    
    async def _design_single_layout_async(self,
                                         page_design: PageDesign,
                                         design_context: Dict,
                                         data_models: Dict,
                                         website_type: str,
                                         semaphore: asyncio.Semaphore) -> PageDesign:
        """
        Async version of _design_single_layout
        """
        async with semaphore:
            return await asyncio.to_thread(
                self._design_single_layout,
                page_design,
                design_context,
                data_models,
                website_type
            )
    
    def _build_layout_prompt(self,
                            page_design: PageDesign,
                            design_context: Dict,
                            data_models: Dict,
                            website_type: str) -> str:
        """
        Build prompt for layout design
        
        Args:
            page_design: Page to design layout for
            design_context: Visual design context
            data_models: Data models
            website_type: Type of website
            
        Returns:
            Formatted prompt string
        """
        # Convert page functionality to dict format
        page_functionality = {
            "core_features": page_design.page_functionality.core_features,
            "user_workflows": page_design.page_functionality.user_workflows,
            "interactions": page_design.page_functionality.interactions,
            "state_logic": page_design.page_functionality.state_logic
        }
        
        # Convert components to simplified format
        existing_components = []
        for comp in page_design.components:
            existing_components.append({
                "id": comp.id,
                "type": comp.type,
                "functionality": comp.functionality,
                "data_binding": comp.data_binding,
                "event_handlers": comp.event_handlers
            })
        
        prompt = f"""
You are a senior UI/UX designer specializing in modern web design. Your task is to create a thoughtful, detailed layout for existing components based on the design mockup analysis.

**DESIGN DNA (extracted from professional mockup):**
- Visual Style: {design_context.get('visual_style', 'Modern')}
- Grid System: {design_context.get('layout_characteristics', {}).get('grid_system', '12-column')}
- Layout Pattern from Mockup: {design_context.get('layout_characteristics', {}).get('layout_pattern', 'Not specified')}
- Spacing System: {json.dumps(design_context.get('spacing_system', {}), indent=2)}

**LAYOUT CHARACTERISTICS FROM DESIGN MOCKUP:**
The following layout characteristics were directly observed from the design mockup. Use these as your primary guide for component layouts:

- Content Arrangement: {design_context.get('layout_from_design', {}).get('content_arrangement', 'Not specified')}
- Space Allocation: {design_context.get('layout_from_design', {}).get('space_allocation', 'Not specified')}
- Content Density: {design_context.get('layout_from_design', {}).get('content_density', 'Not specified')}
- Visual Flow: {design_context.get('layout_from_design', {}).get('visual_flow', 'Not specified')}

**PAGE CONTEXT:**
- Website Type: {website_type}
- Page Name: {page_design.name}
- Page Description: {page_design.description}
- Components to Layout: {json.dumps([{'id': c['id'], 'type': c['type']} for c in existing_components])}

**YOUR TASK:**

Based on the layout characteristics extracted from the design mockup above, create specific layout descriptions for each component.

**STEP 1: Interpret the Design Mockup Layout**

Review the layout characteristics from the design mockup and translate them into concrete layout decisions for this specific page. The layout should faithfully reflect the visual patterns observed in the mockup.

**STEP 2: Describe Each Component's Layout Using Natural Language**

For each component, write a specific, visualizable layout description that:
- Reflects the content arrangement, space allocation, density, and visual flow from the mockup
- Is specific enough to form a mental picture
- Describes relative relationships between components
- Uses clear directional words (top, bottom, left, right, center)
- Includes approximate proportions (occupies 1/3 of page, spans 80% width, etc.)

Good example:
"The search box is positioned at the top center of the page, spanning 60% of the page width, with generous whitespace above and below following the spacious density pattern from the mockup"

Bad example:
"Search box is on the page" (too vague)

**STEP 3: Describe Overall Layout Picture**

Write a paragraph describing the complete layout that:
- Captures the essence of the design mockup's layout characteristics
- Allows readers to imagine the full visual effect
- Explains how the components work together spatially

Return JSON format:
{{
    "interpreted_layout_strategy": {{
        "content_arrangement": "Your interpretation of how to apply the mockup's content arrangement to this page",
        "space_allocation": "Your interpretation of how to apply the mockup's space allocation to this page",
        "content_density": "Your interpretation of how to apply the mockup's content density to this page",
        "visual_flow": "Your interpretation of how to apply the mockup's visual flow to this page"
    }},
    "overall_layout_description": "A comprehensive description of the page's overall layout that paints a clear picture and reflects the design mockup",
    "component_layouts": [
        {{
            "id": "actual-component-id",
            "layout_narrative": "Specific layout description for this component, including position, size, and relationship to other elements - must reflect the mockup's layout characteristics",
            "visual_prominence": "primary|secondary|tertiary",
            "spatial_behavior": "Description of any special spatial behavior like fixed, floating, sticky, etc."
        }}
    ]
}}

IMPORTANT:
- Each component ID must match exactly with the EXISTING COMPONENTS list
- The layout should faithfully reflect the design mockup's visual patterns
- Your layout descriptions should be specific and actionable
- Maintain consistency with the design DNA throughout
"""
        
        return prompt
    
    def generate_layout_summary(self, page_designs: List[PageDesign]) -> str:
        """
        Generate a summary of layout designs
        
        Args:
            page_designs: List of page designs with layouts
            
        Returns:
            Summary string
        """
        lines = ["=== Layout Design Summary ==="]
        
        for page in page_designs:
            if hasattr(page, 'layout') and page.layout:
                lines.append(f"\n{page.name} ({page.filename}):")
                lines.append(f"  Pattern: {page.layout.layout_pattern}")
                lines.append(f"  Grid: {page.layout.grid_system}")
                if page.layout.overall_description:
                    lines.append(f"  Description: {page.layout.overall_description[:100]}...")
                if page.layout.component_layouts:
                    lines.append(f"  Components positioned: {len(page.layout.component_layouts)}")
            else:
                lines.append(f"\n{page.name}: No layout defined")
        
        lines.append("\n" + "=" * 30)
        return "\n".join(lines)