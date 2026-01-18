# Casper Pi Voice Assistant

A voice assistant for Raspberry Pi 5 with local wake word detection and cloud-based conversation.

## Architecture

```
Idle Mode (local, free):
  Microphone → Local Wake Word Detection → Trigger

Active Mode (cloud APIs):
  Microphone → STT → LLM → TTS → Speaker
```

## Components

- **Wake Word Detection**: Local, runs continuously (Vosk or similar)
- **Voice Pipeline**: Gemini Live API (unified STT/LLM/TTS)
- **Audio I/O**: PyAudio for microphone and speaker

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

## Status

Active development - core features implemented and working.

