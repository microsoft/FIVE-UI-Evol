"""
TDD Data Injector Module

Injects website data initialization script into index.html
"""

import json
from typing import Dict, Any
from dataclasses import dataclass
from tdd_logger_module import TDDLogger


@dataclass
class DataInjectionResult:
    """Result of data injection operation"""
    updated_html: str
    injection_successful: bool
    data_items_injected: int


class TDDDataInjector:
    """
    Injects website data into HTML pages for TDD system
    """
    
    def __init__(self, logger: TDDLogger = None):
        """
        Initialize the Data Injector
        
        Args:
            logger: TDDLogger instance
        """
        self.logger = logger or TDDLogger()
    
    def inject_data_to_index(self, html_pages: Dict[str, str], static_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Inject data initialization script to index.html
        
        Args:
            html_pages: Dictionary of filename -> HTML content
            static_data: Generated website data to inject
            
        Returns:
            Updated HTML pages dictionary
            
        Raises:
            Exception: If index.html not found or injection fails
        """
        self.logger.start_stage("Inject Data")
        self.logger.log_info("💉 Injecting data initialization script to index.html...")
        
        if 'index.html' not in html_pages:
            error_msg = "index.html not found in generated pages"
            self.logger.log_error(error_msg)
            raise Exception(error_msg)
        
        # Generate localStorage initialization script
        data_script = self._create_data_initialization_script(static_data)
        
        # Inject script into index.html
        index_html = html_pages['index.html']
        injection_result = self._inject_script_into_html(index_html, data_script)
        
        if not injection_result.injection_successful:
            error_msg = "Failed to inject data script into index.html"
            self.logger.log_error(error_msg)
            raise Exception(error_msg)
        
        # Update html_pages with modified index.html
        updated_pages = dict(html_pages)
        updated_pages['index.html'] = injection_result.updated_html
        
        self.logger.log_info(f"  ✅ Injected {injection_result.data_items_injected} data entities")
        self.logger.log_info("✅ Data injection completed successfully")
        self.logger.end_stage("Inject Data")
        
        return updated_pages
    
    def _create_data_initialization_script(self, static_data: Dict[str, Any]) -> str:
        """
        Create localStorage initialization script for TDD system
        
        Args:
            static_data: Generated website data
            
        Returns:
            JavaScript initialization script as string
        """
        script_lines = [
            "        // Initialize website data",
            "        if (!localStorage.getItem('dataInitialized')) {"
        ]
        
        # Inject static data entities
        data_item_count = 0
        for entity_name, entity_data in static_data.items():
            # Skip metadata (used by evaluation framework, not for localStorage)
            if entity_name.startswith("_"):
                continue

            if isinstance(entity_data, list):
                # Convert to JSON and properly escape for JavaScript
                json_value = json.dumps(entity_data, separators=(',', ':'), ensure_ascii=False)
                escaped_json = self._escape_json_for_javascript(json_value)
                script_lines.append(f'            localStorage.setItem("{entity_name}", "{escaped_json}");')
                data_item_count += len(entity_data)
            else:
                # Handle non-list data (though TDD system should only have lists)
                json_value = json.dumps(entity_data, separators=(',', ':'), ensure_ascii=False)
                escaped_json = self._escape_json_for_javascript(json_value)
                script_lines.append(f'            localStorage.setItem("{entity_name}", "{escaped_json}");')
                data_item_count += 1
        
        # Mark initialization as complete
        script_lines.extend([
            '            localStorage.setItem("dataInitialized", "true");',
            f'            console.log("Website data initialized - {data_item_count} items loaded");',
            "        }"
        ])
        
        return '\n'.join(script_lines)
    
    def _escape_json_for_javascript(self, json_string: str) -> str:
        """
        Escape JSON string for safe inclusion in JavaScript string literal
        
        Args:
            json_string: JSON string to escape
            
        Returns:
            Escaped string safe for JavaScript
        """
        # Escape in the correct order to avoid double-escaping
        escaped = json_string.replace('\\', '\\\\')  # Escape backslashes first
        escaped = escaped.replace('"', '\\"')        # Then escape quotes
        escaped = escaped.replace('\n', '\\n')       # Escape newlines
        escaped = escaped.replace('\r', '\\r')       # Escape carriage returns
        escaped = escaped.replace('\t', '\\t')       # Escape tabs
        return escaped
    
    def _inject_script_into_html(self, html_content: str, data_script: str) -> DataInjectionResult:
        """
        Inject data script into HTML content after </title> tag
        
        Args:
            html_content: Original HTML content
            data_script: JavaScript script to inject
            
        Returns:
            DataInjectionResult with updated HTML and status
        """
        # Find the position to insert the script (after </title>)
        title_end = html_content.find('</title>')
        if title_end == -1:
            self.logger.log_warning("Could not find </title> tag in HTML, trying to inject after <head>")
            # Fallback: try to inject after <head> tag
            head_end = html_content.find('</head>')
            if head_end == -1:
                self.logger.log_error("Could not find </head> tag either")
                return DataInjectionResult(
                    updated_html=html_content,
                    injection_successful=False,
                    data_items_injected=0
                )
            insert_pos = head_end
        else:
            # Find the end of the title tag (including whitespace)
            insert_pos = title_end + len('</title>')
            while insert_pos < len(html_content) and html_content[insert_pos] in ' \t\n\r':
                insert_pos += 1
        
        # Create script tag with the data initialization script
        script_tag = f'\n    <script>\n{data_script}\n    </script>'
        
        # Insert the script at the calculated position
        updated_html = html_content[:insert_pos] + script_tag + html_content[insert_pos:]
        
        # Count data items (rough estimate from script content)
        data_item_count = data_script.count('localStorage.setItem') - 1  # Subtract 1 for "dataInitialized"
        
        return DataInjectionResult(
            updated_html=updated_html,
            injection_successful=True,
            data_items_injected=data_item_count
        )
    
    def validate_injection(self, html_content: str) -> bool:
        """
        Validate that data injection was successful
        
        Args:
            html_content: HTML content to validate
            
        Returns:
            True if injection appears successful, False otherwise
        """
        # Check for presence of data initialization markers
        has_init_check = 'dataInitialized' in html_content
        has_localstorage_calls = 'localStorage.setItem' in html_content
        has_script_tags = '<script>' in html_content and '</script>' in html_content
        
        return has_init_check and has_localstorage_calls and has_script_tags