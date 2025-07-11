import yaml
import os
from pathlib import Path

class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            current_dir = Path(__file__).parent
            config_path = current_dir.parent / "config" / "config.yaml"
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
    
    @property
    def critic_model(self):
        return self._config['models']['critic_model']
    
    @property
    def retrace_model(self):
        return self._config['models']['retrace_model']
    
    @property
    def api_version(self):
        return self._config['azure_openai']['api_version']
    
    @property
    def gpt4o_endpoints(self):
        return self._config['azure_openai']['endpoints']['gpt4o']
    
    @property
    def o3_endpoints(self):
        return self._config['azure_openai']['endpoints']['o3']
    
    @property
    def max_workers(self):
        return self._config['performance']['max_workers']
    
    @property
    def history_path(self):
        return self._config['paths']['history_path']
    
    @property
    def domains(self):
        return self._config['paths']['domains']

config = Config()
