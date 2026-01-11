#!/usr/bin/env python3
"""Main entry point for Casper voice assistant"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.state import StateManager


async def main():
    """Main entry point"""
    print("🚀 Starting Casper voice assistant...")
    print("=" * 60)
    
    # Run state manager (loads config from .env)
    try:
        manager = StateManager()
        await manager.run()
        return 0
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("Please create a .env file with:")
        print("  GEMINI_API_KEY=your_api_key_here")
        print("  GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-12-2025  # optional")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
