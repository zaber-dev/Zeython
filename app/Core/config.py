"""
Configuration management for the modular MVC framework.
Handles loading and managing application configuration from various sources.
"""

import os
from typing import Dict, Any, Optional, Union
from pathlib import Path
import logging


class Config:
    """
    Configuration manager that loads settings from environment variables and files.
    
    Provides a centralized way to access application configuration with 
    fallback support and type conversion.
    """
    
    def __init__(self, config_dict: Dict[str, Any] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_dict (Dict[str, Any], optional): Initial configuration dictionary
        """
        self._config = config_dict or {}
        self.logger = logging.getLogger("config")
        self._load_environment_variables()
    
    def _load_environment_variables(self):
        """Load configuration from environment variables."""
        # Database configuration
        self._config.update({
            'database': {
                'url': os.environ.get('DATABASE_URL', 'sqlite:///database.db'),
                'host': os.environ.get('DB_HOST', '127.0.0.1'),
                'port': os.environ.get('DB_PORT', '5432'),
                'name': os.environ.get('DB_DATABASE', 'mvc_app'),
                'username': os.environ.get('DB_USERNAME', ''),
                'password': os.environ.get('DB_PASSWORD', '')
            },
            
            # Web service configuration
            'web': {
                'enabled': bool(os.environ.get('FLASK_HOST')),
                'host': os.environ.get('FLASK_HOST', '127.0.0.1'),
                'port': int(os.environ.get('FLASK_PORT', 5000)),
                'debug': os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
            },
            
            # Discord service configuration (optional)
            'discord': {
                'enabled': bool(os.environ.get('DISCORD_TOKEN')),
                'token': os.environ.get('DISCORD_TOKEN', ''),
                'prefix': os.environ.get('DISCORD_PREFIX', '!'),
                'owner_id': os.environ.get('DISCORD_OWNER', ''),
                'bot_invite': os.environ.get('DISCORD_BOT_INVITE', ''),
                'guild_invite': os.environ.get('DISCORD_GUILD_INVITE', '')
            },
            
            # Application configuration
            'app': {
                'name': os.environ.get('APP_NAME', 'Zeython'),
                'debug': os.environ.get('APP_DEBUG', 'False').lower() == 'true',
                'log_level': os.environ.get('LOG_LEVEL', 'INFO'),
                'timezone': os.environ.get('TIMEZONE', 'UTC')
            }
        })
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.
        
        Args:
            key (str): Configuration key (supports dot notation like 'database.url')
            default (Any): Default value if key is not found
            
        Returns:
            Any: Configuration value or default
        """
        try:
            value = self._config
            for part in key.split('.'):
                value = value[part]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any):
        """
        Set a configuration value using dot notation.
        
        Args:
            key (str): Configuration key (supports dot notation)
            value (Any): Value to set
        """
        keys = key.split('.')
        config = self._config
        
        # Navigate to the parent dictionary
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # Set the final value
        config[keys[-1]] = value
    
    def get_service_config(self, service_name: str) -> Dict[str, Any]:
        """
        Get configuration for a specific service.
        
        Args:
            service_name (str): Name of the service
            
        Returns:
            Dict[str, Any]: Service configuration
        """
        return self.get(service_name, {})
    
    def is_service_enabled(self, service_name: str) -> bool:
        """
        Check if a service is enabled.
        
        Args:
            service_name (str): Name of the service
            
        Returns:
            bool: True if service is enabled, False otherwise
        """
        return self.get(f'{service_name}.enabled', False)
    
    def update(self, config_dict: Dict[str, Any]):
        """
        Update configuration with values from a dictionary.
        
        Args:
            config_dict (Dict[str, Any]): Configuration dictionary to merge
        """
        self._merge_config(self._config, config_dict)
    
    def _merge_config(self, base: Dict[str, Any], update: Dict[str, Any]):
        """
        Recursively merge configuration dictionaries.
        
        Args:
            base (Dict[str, Any]): Base configuration dictionary
            update (Dict[str, Any]): Update configuration dictionary
        """
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Get the complete configuration as a dictionary.
        
        Returns:
            Dict[str, Any]: Complete configuration
        """
        return self._config.copy()
    
    def load_from_file(self, file_path: Union[str, Path]):
        """
        Load configuration from a file (JSON, YAML, or Python).
        
        Args:
            file_path (Union[str, Path]): Path to the configuration file
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            self.logger.warning(f"Configuration file not found: {file_path}")
            return
        
        try:
            if file_path.suffix.lower() == '.json':
                import json
                with open(file_path, 'r') as f:
                    config = json.load(f)
                self.update(config)
            elif file_path.suffix.lower() in ['.yml', '.yaml']:
                try:
                    import yaml
                    with open(file_path, 'r') as f:
                        config = yaml.safe_load(f)
                    self.update(config)
                except ImportError:
                    self.logger.error("PyYAML not installed, cannot load YAML configuration")
            elif file_path.suffix.lower() == '.py':
                # Load Python configuration file
                import importlib.util
                spec = importlib.util.spec_from_file_location("config", file_path)
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)
                
                # Extract configuration variables from module
                config = {
                    key: value for key, value in vars(config_module).items()
                    if not key.startswith('_') and not callable(value)
                }
                self.update(config)
            else:
                self.logger.warning(f"Unsupported configuration file format: {file_path.suffix}")
        
        except Exception as e:
            self.logger.error(f"Failed to load configuration from {file_path}: {e}")


# Global configuration instance
config = Config()