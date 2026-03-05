"""
TDD Design Analyzer Module

This module analyzes design images to extract visual features, colors, layouts,
and other design characteristics for use in page generation.
"""

import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from llm_caller import call_openai_with_image_json_async
from tdd_logger_module import TDDLogger


@dataclass
class DesignAnalysis:
    """Analysis results from design image"""
    visual_features: Dict[str, Any]  # Visual features: style, hierarchy, whitespace
    color_scheme: Dict[str, Any]  # Color scheme: primary, secondary, accent, neutral
    layout_characteristics: Dict[str, Any]  # Layout: grid, patterns, alignment
    ui_patterns: List[Dict[str, Any]]  # UI patterns: buttons, cards, forms
    typography: Dict[str, Any]  # Typography: fonts, sizes, weights
    spacing_system: Dict[str, Any]  # Spacing: base unit, scale
    interaction_hints: List[str]  # Interaction hints: hover, transitions


class TDDDesignAnalyzer:
    """
    Analyzes design images to extract visual characteristics
    """
    
    def __init__(self, logger: Optional[TDDLogger] = None, model=None, reasoning_effort=None):
        """
        Initialize the TDD Design Analyzer

        Args:
            logger: Optional TDDLogger instance
            model: Model to use (e.g., "gpt-4.1", "gpt-5", None for default)
            reasoning_effort: Reasoning effort level (e.g., "low", "medium", "high")
        """
        self.logger = logger or TDDLogger()
        self.model = model
        self.reasoning_effort = reasoning_effort
    
    async def analyze_design(self, image_path: str, website_type: str) -> DesignAnalysis:
        """
        Analyze design image to extract visual features
        
        Args:
            image_path: Path to the design image
            website_type: Type of website being generated
            
        Returns:
            DesignAnalysis object
            
        Raises:
            ValueError: If no image path provided
            Exception: If analysis fails
        """
        if not image_path:
            raise ValueError("Design image path is required")
        
        self.logger.start_stage("Analyze Design Image")
        self.logger.log_info(f"🖼️ Analyzing design image: {image_path}")
        
        prompt = f"""
You are a senior UI/UX design analyst. Analyze the provided design image in detail to extract all visual characteristics, design patterns, and layout principles.

Website Type: {website_type}

**ANALYSIS TASKS:**

1. **Visual Features Analysis**:
   - Identify the overall visual style (modern, minimalist, vibrant, corporate, etc.)
   - Describe visual hierarchy and focal points
   - Note use of whitespace and visual breathing room
   - Identify any unique visual elements or patterns

2. **Color Scheme Extraction**:
   - Primary colors (main brand colors)
   - Secondary colors (supporting colors)
   - Accent colors (for CTAs, highlights)
   - Neutral colors (backgrounds, text, borders)
   - Semantic colors (success, error, warning, info)
   - Provide exact color values if possible

3. **Layout Characteristics**:
   - Grid system (12-column, custom, etc.)
   - Layout patterns (sidebar, centered, full-width)
   - Section organization and flow
   - Responsive design hints
   - Alignment principles used
   - **Content Arrangement**: Describe in detail how content blocks are arranged (e.g., "linear top-to-bottom flow with alternating full-width and two-column sections")
   - **Space Allocation**: How space is distributed among elements (e.g., "main content area occupies top 60% of viewport, followed by evenly distributed card grid")
   - **Content Density**: Visual density and whitespace usage (e.g., "spacious layout with generous padding between sections" or "compact information-dense design")
   - **Visual Flow**: How the eye moves through the design (e.g., "Z-pattern starting from logo, across navigation, down to main content")

4. **UI Patterns Identification** (describe BOTH visual appearance AND structural patterns):
   - For each UI component type, describe:
     a. Visual appearance in detail (specific shapes, shadows, borders, spacing - not just "rounded" but "rounded with 4px radius")
     b. Structural HTML patterns you would expect (e.g., "buttons as styled links", "cards with header bars")
   - Button styles: shape with specific details, typical structure
   - Card/container styles: shadow/border treatment, internal organization
   - Form element designs: input styling, label placement, grouping patterns
   - Navigation patterns: orientation, structure, active state treatment
   - List patterns: item density, separator style, thumbnail placement

5. **Typography Analysis**:
   - Font visual characteristics observed in design (e.g., "geometric sans-serif with high x-height", "elegant serif with thin strokes", "bold condensed display font")
   - Recommended Google Fonts that match the observed style (prefer diverse, distinctive fonts over common ones like Montserrat, Open Sans, Roboto, Arial)
   - Font size hierarchy
   - Font weights used
   - Line height patterns
   - Text alignment preferences

6. **Spacing System**:
   - Base spacing unit
   - Padding patterns
   - Margin patterns
   - Component spacing
   - Section spacing

7. **Interaction Hints**:
   - Hover state indicators
   - Active/selected states
   - Transition/animation suggestions
   - Micro-interaction patterns

Return your analysis in JSON format:
{{
    "visual_features": {{
        "overall_style": "Description of the overall visual style",
        "visual_hierarchy": "How visual hierarchy is established",
        "whitespace_usage": "How whitespace is used",
        "unique_elements": ["List of unique visual elements"]
    }},
    "color_scheme": {{
        "primary": ["#hex1", "#hex2"],
        "secondary": ["#hex3", "#hex4"],
        "accent": ["#hex5"],
        "neutral": ["#hex6", "#hex7", "#hex8"],
        "semantic": {{
            "success": "#hex9",
            "error": "#hex10",
            "warning": "#hex11",
            "info": "#hex12"
        }}
    }},
    "layout_characteristics": {{
        "grid_system": "Type of grid system",
        "layout_pattern": "Main layout pattern",
        "section_organization": "How sections are organized",
        "alignment": "Alignment principles",
        "responsive_hints": ["Responsive design observations"],
        "content_arrangement": "Detailed description of how content blocks are arranged in the design. Be specific - describe the actual visual structure observed, such as 'linear top-to-bottom flow with alternating full-width and two-column content sections' or 'asymmetric layout with dominant left sidebar and stacked content cards on right'",
        "space_allocation": "How space is distributed among visual elements. Describe proportions and relationships, such as 'header and main content area occupy top portion of viewport with minimal padding, followed by dense grid of equally-sized product cards' or 'generous 40% whitespace margins framing centered content column'",
        "content_density": "Description of visual density and whitespace usage. Be specific about the observed density level, such as 'spacious editorial layout with ample breathing room between sections and large margins' or 'compact information-dense interface maximizing content per viewport'",
        "visual_flow": "How the eye naturally moves through the design. Describe the visual path created by the layout, such as 'Z-pattern starting from logo, across main navigation, down to primary content area, then scanning feature cards left-to-right' or 'strong vertical flow with centered focal points drawing eye downward'"
    }},
    "ui_patterns": [
        {{
            "pattern_type": "button",
            "visual_description": "Describe the button's complete visual appearance: shape (e.g., 'rounded rectangle with 4px radius', 'pill-shaped with full rounding', 'sharp rectangular corners'), typical sizes, border treatment, and any skeuomorphic or flat design characteristics",
            "structural_pattern": "Describe how buttons are typically structured in the HTML (e.g., 'simple <button> with icon + text', 'link styled as button', 'button inside wrapper div')"
        }},
        {{
            "pattern_type": "card",
            "visual_description": "Describe the card's visual treatment: shadow style (e.g., 'no shadow, border-based separation', 'subtle drop shadow', 'prominent elevation'), border characteristics, corner treatment, and padding approach",
            "structural_pattern": "Describe typical card structure (e.g., 'header bar + content area', 'image-first with text overlay', 'bordered box with title strip')"
        }},
        {{
            "pattern_type": "form",
            "visual_description": "Describe form element styling: input field appearance, label positioning (above/inline/floating), validation feedback style, and overall form density",
            "structural_pattern": "Describe form layout patterns (e.g., 'stacked labels with full-width inputs', 'inline label-input pairs', 'fieldset-grouped sections')"
        }},
        {{
            "pattern_type": "navigation",
            "visual_description": "Describe navigation visual style: orientation, spacing, active state indicators, and overall design character",
            "structural_pattern": "Describe navigation HTML patterns (e.g., 'simple ul/li list', 'tab-bar with buttons', 'dropdown-based menu')"
        }},
        {{
            "pattern_type": "list",
            "visual_description": "Describe list item styling: density, separator style, thumbnail/icon treatment, and visual hierarchy within items",
            "structural_pattern": "Describe list HTML patterns (e.g., 'table-based rows', 'flexbox media objects', 'grid cards')"
        }}
    ],
    "typography": {{
        "font_families": {{
            "heading": {{
                "visual_style": "Describe the visual characteristics of heading fonts observed in the design (e.g., 'bold geometric sans-serif', 'elegant high-contrast serif', 'playful rounded display')",
                "recommended": "A specific Google Font that matches this style (avoid overused fonts like Montserrat, Open Sans, Roboto, Arial - prefer distinctive alternatives like Poppins, Playfair Display, Space Grotesk, Lora, Raleway, Merriweather, DM Sans, Libre Franklin, etc.)",
                "fallback": "Web-safe fallback font (e.g., 'Georgia, serif' or 'Helvetica, sans-serif')"
            }},
            "body": {{
                "visual_style": "Describe body text font characteristics observed (e.g., 'clean humanist sans-serif', 'readable transitional serif', 'neutral grotesque')",
                "recommended": "A specific Google Font for body text (avoid overused fonts - prefer distinctive options like Source Sans 3, Nunito, Libre Baskerville, Work Sans, IBM Plex Sans, Karla, etc.)",
                "fallback": "Web-safe fallback font"
            }},
            "code": "Font family for code if any (e.g., 'JetBrains Mono', 'Fira Code', 'Source Code Pro')"
        }},
        "font_sizes": {{
            "h1": "size",
            "h2": "size",
            "h3": "size",
            "body": "size",
            "small": "size"
        }},
        "font_weights": {{
            "light": "300",
            "regular": "400",
            "medium": "500",
            "semibold": "600",
            "bold": "700"
        }},
        "line_heights": {{
            "tight": "1.2",
            "normal": "1.5",
            "relaxed": "1.75"
        }}
    }},
    "spacing_system": {{
        "base_unit": "8px",
        "scale": ["4px", "8px", "16px", "24px", "32px", "48px", "64px"],
        "component_padding": "Common padding for components",
        "section_margin": "Common margin between sections"
    }},
    "interaction_hints": [
        "Hover effects observed",
        "Transition patterns",
        "Animation suggestions"
    ]
}}
"""
        
        # Log API call and get call_id
        call_id = None
        if self.logger:
            call_id = self.logger.log_api_call(
                "Analyze Design Image",
                prompt,
                additional_args={
                    "image_path": image_path
                }
            )

        try:
            # Call LLM with image
            result, usage_info = await call_openai_with_image_json_async(
                prompt,
                image_path,
                model=self.model,
                reasoning_effort=self.reasoning_effort
            )
            
            # Log successful API response
            if self.logger:
                self.logger.log_api_response(
                    "Analyze Design Image",
                    success=True,
                    response=result,
                    usage_info=usage_info,
                    call_id=call_id
                )
            
            # Parse response
            if isinstance(result, str):
                analysis_data = json.loads(result)
            else:
                analysis_data = result
            
            # Create DesignAnalysis object
            design_analysis = DesignAnalysis(
                visual_features=analysis_data.get("visual_features", {}),
                color_scheme=analysis_data.get("color_scheme", {}),
                layout_characteristics=analysis_data.get("layout_characteristics", {}),
                ui_patterns=analysis_data.get("ui_patterns", []),
                typography=analysis_data.get("typography", {}),
                spacing_system=analysis_data.get("spacing_system", {}),
                interaction_hints=analysis_data.get("interaction_hints", [])
            )
            
            # Log summary
            self.logger.log_info(f"✅ Successfully analyzed design image")
            self.logger.log_info(f"   - Extracted {len(design_analysis.color_scheme)} color categories")
            self.logger.log_info(f"   - Identified {len(design_analysis.ui_patterns)} UI patterns")
            self.logger.log_info(f"   - Analyzed typography with {len(design_analysis.typography.get('font_sizes', {}))} size levels")
            
            self.logger.end_stage("Analyze Design Image")
            
            return design_analysis
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to analyze design image: {str(e)}"
            self.logger.log_error(error_msg)
            self.logger.log_error(f"Stack trace:\n{traceback.format_exc()}")
            # Log failed API response
            if self.logger:
                self.logger.log_api_response(
                    "Analyze Design Image",
                    success=False,
                    error=str(e),
                    call_id=call_id
                )
            self.logger.end_stage("Analyze Design Image")
            raise Exception(error_msg)
    
    def generate_analysis_summary(self, design_analysis: Optional[DesignAnalysis]) -> str:
        """
        Generate a human-readable summary of design analysis
        
        Args:
            design_analysis: DesignAnalysis object or None
            
        Returns:
            Summary string
        """
        if not design_analysis:
            return "No design analysis available"
        
        lines = []
        lines.append("=== Design Analysis Summary ===\n")
        
        # Visual features
        if design_analysis.visual_features:
            lines.append("Visual Features:")
            lines.append(f"  Style: {design_analysis.visual_features.get('overall_style', 'N/A')}")
            lines.append(f"  Hierarchy: {design_analysis.visual_features.get('visual_hierarchy', 'N/A')}")
        
        # Color scheme
        if design_analysis.color_scheme:
            lines.append("\nColor Scheme:")
            for category, colors in design_analysis.color_scheme.items():
                if isinstance(colors, list):
                    # Convert all items to strings before joining
                    color_strings = [str(color) for color in colors[:3]]
                    lines.append(f"  {category.title()}: {', '.join(color_strings)}")
                elif isinstance(colors, dict):
                    lines.append(f"  {category.title()}: {len(colors)} colors defined")
        
        # Layout
        if design_analysis.layout_characteristics:
            lines.append("\nLayout Characteristics:")
            lines.append(f"  Grid: {design_analysis.layout_characteristics.get('grid_system', 'N/A')}")
            lines.append(f"  Pattern: {design_analysis.layout_characteristics.get('layout_pattern', 'N/A')}")
        
        # UI Patterns
        if design_analysis.ui_patterns:
            lines.append(f"\nUI Patterns: {len(design_analysis.ui_patterns)} patterns identified")
            for pattern in design_analysis.ui_patterns[:3]:  # Show first 3
                lines.append(f"  - {pattern.get('pattern_type', 'Unknown')}")
        
        # Typography
        if design_analysis.typography:
            fonts = design_analysis.typography.get('font_families', {})
            if fonts:
                lines.append("\nTypography:")
                lines.append(f"  Heading Font: {fonts.get('heading', 'N/A')}")
                lines.append(f"  Body Font: {fonts.get('body', 'N/A')}")
        
        # Spacing
        if design_analysis.spacing_system:
            lines.append("\nSpacing System:")
            lines.append(f"  Base Unit: {design_analysis.spacing_system.get('base_unit', 'N/A')}")
            scale = design_analysis.spacing_system.get('scale', [])
            if scale:
                lines.append(f"  Scale: {', '.join(scale[:5])}")
        
        # Interaction hints
        if design_analysis.interaction_hints:
            lines.append(f"\nInteraction Hints: {len(design_analysis.interaction_hints)} patterns")
            for hint in design_analysis.interaction_hints[:3]:  # Show first 3
                lines.append(f"  - {hint}")
        
        return "\n".join(lines)


if __name__ == "__main__":
    # Test the design analyzer
    print("Testing TDD Design Analyzer...")
    
    analyzer = TDDDesignAnalyzer()
    
    # Test with a sample image path
    test_image = "resource/shopping.png"
    test_website_type = "shopping_website"
    
    print(f"Analyzing design image: {test_image}")
    analysis = analyzer.analyze_design(test_image, test_website_type)
    
    if analysis:
        summary = analyzer.generate_analysis_summary(analysis)
        print(summary)
    else:
        print("Failed to analyze design image")