"""Utility functions for Casper Pi Voice Assistant"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Load environment variables
    load_dotenv()
    
    # Override with environment variables if present
    if os.getenv('PROVIDER'):
        config['provider']['name'] = os.getenv('PROVIDER')
    
    return config


def get_env_var(key: str, default: str = None) -> str:
    """Get environment variable with optional default."""
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Environment variable {key} is required but not set")
    return value

