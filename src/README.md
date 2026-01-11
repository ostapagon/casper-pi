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

## Conversation History

Saved to `memories/chat_YYYYMMDD_HHMMSS.json`
