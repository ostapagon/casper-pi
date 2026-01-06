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
4. Run

## Status

Planning phase - architecture defined, implementation pending.

