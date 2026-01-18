"""Centralized configuration from environment variables"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_flip_display() -> bool:
    """Get flip_display setting from environment variable
    
    Returns:
        True if FLIP_DISPLAY env var is set to 'true', '1', 'yes', or 'on' (case-insensitive)
        False otherwise
    """
    flip = os.getenv("FLIP_DISPLAY", "false").lower()
    return flip in ("true", "1", "yes", "on")


def get_gemini_api_key() -> Optional[str]:
    """Get Gemini API key from environment variable
    
    Returns:
        API key string or None if not set
    """
    return os.getenv("GEMINI_API_KEY")


def get_gemini_model() -> str:
    """Get Gemini model from environment variable
    
    Returns:
        Model name string, defaults to 'gemini-2.5-flash-native-audio-preview-12-2025'
    """
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")


def get_mcp_servers_config() -> Optional[str]:
    """Get MCP servers configuration from environment variable
    
    Returns:
        JSON string with MCP servers config or None if not set
    """
    return os.getenv("MCP_SERVERS")

