#!/usr/bin/env python3
"""Main entry point for Casper Pi Voice Assistant"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.assistant import VoiceAssistant
from src.utils import load_config


async def main():
    """Main entry point."""
    try:
        config = load_config()
        
        assistant = VoiceAssistant(config)
        await assistant.run()
        
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

