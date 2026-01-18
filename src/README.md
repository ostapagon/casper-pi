# Casper Voice Assistant

Simple voice assistant with wake word detection and Gemini Live API integration.

## Structure

```
src/
├── main.py                     # Entry point
├── state.py                    # State manager (switches IDLE ↔ ACTIVE)
├── wake_word.py                # Wake word detector (Vosk)
└── voice_clients/
    └── gemini_live.py          # Gemini Live client
```

## How It Works

**State Manager** (`state.py`) controls the loop:
- **IDLE state**: Listens for "casper" wake word
- **ACTIVE state**: Runs Gemini conversation
- **Back to IDLE**: When conversation ends

**Components**:
- `WakeWordDetector`: Listens for "casper" using Vosk
- `GeminiLiveClient`: Handles conversation with Gemini Live API
- `StateManager`: Switches between components

## Usage

```bash
# Run
python3 src/main.py

# Or use helper script
./run.sh
```

## Flow

1. Start → **IDLE** (listening for wake word)
2. Say "casper" → **ACTIVE** (Gemini conversation)
3. Say "goodbye" → **IDLE** (back to listening)
4. Repeat...

## Environment

Create `.env` file:
```
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=your_audio_model_here
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
