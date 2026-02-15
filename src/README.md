# Casper Voice Assistant

Voice assistant with wake word detection, Gemini Live API integration, and multiple service interfaces.

> **📖 Blog Post**: Read about building Casper on [ostapagon's blog](https://ostapagon.github.io/posts/2026-02-07-raspberry-ai/)

## Structure

```
src/
├── main.py                     # Entry point
├── config.py                   # Configuration management
├── state.py                    # State manager (switches IDLE ↔ ACTIVE)
├── wake_word.py                # Wake word detector (Vosk)
├── voice_clients/              # Voice API clients
│   └── gemini_live.py          # Gemini Live client
├── services/                   # Service layer
│   ├── agent.py                # Agent logic with MCP tools
│   ├── memory.py               # Conversation memory management
│   ├── task_executor.py        # Task execution engine
│   ├── telegram_bot.py         # Telegram bot interface
│   └── webhook_server.py       # HTTP webhook server
├── webhooks/                   # Webhook handlers
├── integrations/               # External integrations
├── mcp/                        # MCP registry and servers
│   ├── registry.py             # MCP registry
│   └── servers/                # Custom MCP servers
└── display/                    # OLED display module
    ├── manager.py              # Display manager
    ├── states.py               # Display states
    ├── tools.py                # Display tools for Gemini
    └── visualizations.py       # Visualization functions
```

## How It Works

**State Manager** (`state.py`) controls the loop:
- **IDLE state**: Listens for "casper" wake word
- **ACTIVE state**: Runs Gemini conversation
- **Back to IDLE**: When conversation ends

**Core Components**:
- `WakeWordDetector`: Listens for "casper" using Vosk
- `GeminiLiveClient`: Handles conversation with Gemini Live API
- `StateManager`: Switches between components
- `TaskExecutor`: Executes tasks across all interfaces
- `Agent`: Manages MCP tool integration with Gemini

## Usage

```bash
# Run the voice assistant
python3 src/main.py

# Enable specific services via .env:
# ENABLE_WEBHOOK=true
# ENABLE_TELEGRAM=true
```

## Flow

1. Start → **IDLE** (listening for wake word)
2. Say "casper" → **ACTIVE** (Gemini conversation with MCP tools)
3. Say "goodbye" → **IDLE** (back to listening)
4. Repeat...

## Parallel Services

- **Voice Assistant**: Always active (wake word + Gemini)
- **Webhook Server**: Optional HTTP API (enable with `ENABLE_WEBHOOK=true`)
- **Telegram Bot**: Optional mobile interface (enable with `ENABLE_TELEGRAM=true`)
- All services share the same task executor and MCP tools

## Environment

Create `.env` file:
```
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=your_audio_model_here
ENABLE_WEBHOOK=false
ENABLE_TELEGRAM=false
TELEGRAM_BOT_TOKEN=your_bot_token_here  # if using Telegram
PERPLEXITY_API_KEY=your_key_here         # if using Perplexity MCP
```

## Font Requirements

For display support of Chinese characters, install fonts:

```bash
sudo apt-get install -y fonts-wqy-microhei fonts-noto-cjk
```

The display system automatically uses these fonts to render both English and Chinese text correctly.

## Anki Integration

This project uses a **custom Anki MCP server** (`src/mcp/servers/anki/server.py`) that connects to AnkiConnect. 

**Setup:**
1. Install Anki desktop application
2. Install AnkiConnect addon (code: 2055492159)
3. Start Anki (AnkiConnect runs on port 8765)
4. Configure deck settings in `src/mcp/servers/anki/decks.json` (optional)

See `src/mcp/README.md` for detailed information.

## Conversation History

Saved to `memories/chat_YYYYMMDD_HHMMSS.json`
