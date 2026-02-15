# Casper Pi Voice Assistant

A voice assistant for Raspberry Pi 5 with local wake word detection, cloud-based conversation, and parallel webhook/Telegram interfaces.

> **📖 Blog Post**: Read about building Casper on [ostapagon's blog](https://ostapagon.github.io/posts/2026-02-07-raspberry-ai/) - "Raspberry AI: Agent That Won't Ghost You for $200"

## Architecture

```
Three Parallel Interfaces:

1. Voice Assistant (local + cloud):
   Microphone → Wake Word → Gemini Live → Speaker

2. Webhook Server (HTTP API):
   HTTP Requests → Task Executor → MCP Tools

3. Telegram Bot (mobile chat):
   Telegram Messages → Task Executor → MCP Tools
```

## Components

- **Wake Word Detection**: Local, runs continuously (Vosk)
- **Voice Pipeline**: Gemini Live API (unified STT/LLM/TTS)
- **Audio I/O**: PyAudio for microphone and speaker
- **Webhook Server**: FastAPI REST API for automation
- **Telegram Bot**: Mobile chat interface with voice support
- **MCP Integration**: Tool execution across all interfaces

## Tech Stack

- Python 3.9+
- Vosk (wake word detection)
- Google Gemini Live API
- PyAudio (audio I/O)

## Setup

1. Install dependencies
2. Download Vosk model
3. Configure environment variables (GEMINI_API_KEY)
4. Install Chinese fonts (for display support)
5. Install and configure Anki with AnkiConnect
6. Run

## Font Requirements

The display supports both English and Chinese characters. Install Chinese fonts:

```bash
sudo apt-get install -y fonts-wqy-microhei fonts-noto-cjk
```

These fonts are automatically used by the display system to render Chinese characters correctly.

## Anki Integration

This project uses a **custom Anki MCP server** (not the AnkiMCP addon) located at `src/mcp/servers/anki/server.py`. 

**Requirements:**
- Anki desktop application installed
- AnkiConnect addon installed (code: 2055492159)
- Anki must be running (AnkiConnect runs on port 8765)

**Features:**
- Custom due date filtering logic
- Deck-specific configuration via `src/mcp/servers/anki/decks.json`
- Proper handling of "Again" cards and review limits

See `src/mcp/README.md` for detailed Anki setup instructions.

## Features

✅ **Voice Assistant** - Local wake word + Gemini Live conversations
✅ **Webhook Server** - HTTP REST API for automation/integration
✅ **Telegram Bot** - Mobile chat interface with voice messages
✅ **MCP Tools** - Anki, Google Calendar integration
✅ **OLED Display** - Visual feedback (Chinese/English support)
✅ **Parallel Execution** - All interfaces run simultaneously

## Quick Start

### Basic Setup (Voice Only)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 3. Run
python src/main.py
```

### Full Setup (Voice + Webhook + Telegram)

See [docs/SERVICES_SETUP.md](docs/SERVICES_SETUP.md) for detailed setup instructions.

```bash
# Enable services in .env:
ENABLE_WEBHOOK=true
ENABLE_TELEGRAM=true
TELEGRAM_BOT_TOKEN=your_token_from_botfather
```

## Testing

```bash
# Test core functionality
python cursor_tests/test_task_executor.py

# Test webhook server
python cursor_tests/test_webhook.py

# Test Telegram bot
python cursor_tests/test_telegram.py
```

## Status

Active development - core features implemented and working.

