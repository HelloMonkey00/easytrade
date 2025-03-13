"""
Utility functions for configuration management.
"""
import os
import json
import yaml
import logging
from typing import Dict, Any, Optional


def load_json_config(file_path: str) -> Dict[str, Any]:
    """
    Load configuration from a JSON file.
    
    Args:
        file_path: Path to JSON configuration file
        
    Returns:
        Configuration dictionary
    """
    try:
        with open(file_path, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        logging.error(f"Error loading JSON config from {file_path}: {e}")
        return {}


def load_yaml_config(file_path: str) -> Dict[str, Any]:
    """
    Load configuration from a YAML file.
    
    Args:
        file_path: Path to YAML configuration file
        
    Returns:
        Configuration dictionary
    """
    try:
        with open(file_path, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        logging.error(f"Error loading YAML config from {file_path}: {e}")
        return {}


def save_json_config(config: Dict[str, Any], file_path: str) -> bool:
    """
    Save configuration to a JSON file.
    
    Args:
        config: Configuration dictionary
        file_path: Path to save JSON configuration file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            
        with open(file_path, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        logging.error(f"Error saving JSON config to {file_path}: {e}")
        return False


def save_yaml_config(config: Dict[str, Any], file_path: str) -> bool:
    """
    Save configuration to a YAML file.
    
    Args:
        config: Configuration dictionary
        file_path: Path to save YAML configuration file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            
        with open(file_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        logging.error(f"Error saving YAML config to {file_path}: {e}")
        return False


def load_config(file_path: str) -> Dict[str, Any]:
    """
    Load configuration from a file (JSON or YAML).
    
    Args:
        file_path: Path to configuration file
        
    Returns:
        Configuration dictionary
    """
    if file_path.endswith('.json'):
        return load_json_config(file_path)
    elif file_path.endswith(('.yaml', '.yml')):
        return load_yaml_config(file_path)
    else:
        logging.error(f"Unsupported config file format: {file_path}")
        return {}


def save_config(config: Dict[str, Any], file_path: str) -> bool:
    """
    Save configuration to a file (JSON or YAML).
    
    Args:
        config: Configuration dictionary
        file_path: Path to save configuration file
        
    Returns:
        True if successful, False otherwise
    """
    if file_path.endswith('.json'):
        return save_json_config(config, file_path)
    elif file_path.endswith(('.yaml', '.yml')):
        return save_yaml_config(config, file_path)
    else:
        logging.error(f"Unsupported config file format: {file_path}")
        return False


def merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge two configuration dictionaries.
    
    Args:
        base_config: Base configuration dictionary
        override_config: Override configuration dictionary
        
    Returns:
        Merged configuration dictionary
    """
    result = base_config.copy()
    
    for key, value in override_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
            
    return result


class Config:
    """Configuration manager class."""
    
    def __init__(self, config_file: Optional[str] = None, defaults: Optional[Dict[str, Any]] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_file: Path to configuration file (optional)
            defaults: Default configuration values (optional)
        """
        self.config_file = config_file
        self.config = defaults or {}
        
        if config_file and os.path.exists(config_file):
            loaded_config = load_config(config_file)
            self.config = merge_configs(self.config, loaded_config)
            
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        return self.config.get(key, default)
        
    def set(self, key: str, value: Any):
        """
        Set a configuration value.
        
        Args:
            key: Configuration key
            value: Configuration value
        """
        self.config[key] = value
        
    def save(self, file_path: Optional[str] = None) -> bool:
        """
        Save the configuration to a file.
        
        Args:
            file_path: Path to save configuration file (defaults to self.config_file)
            
        Returns:
            True if successful, False otherwise
        """
        file_path = file_path or self.config_file
        if not file_path:
            logging.error("No file path specified for saving configuration")
            return False
            
        return save_config(self.config, file_path)
        
    def update(self, config: Dict[str, Any]):
        """
        Update the configuration with new values.
        
        Args:
            config: Configuration dictionary to update with
        """
        self.config = merge_configs(self.config, config) 