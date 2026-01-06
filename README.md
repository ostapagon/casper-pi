# Casper Pi Voice Assistant

A minimal voice assistant for Raspberry Pi 5 with wake word detection and provider-agnostic voice conversation. Features streaming audio processing for real-time interaction.

## Features

- **Wake Word Detection**: Pre-trained wake word detection using Picovoice Porcupine
- **Streaming Voice Pipeline**: Real-time streaming from microphone → STT → LLM → TTS → speaker
- **Provider Agnostic**: Easy to swap providers (currently supports Gemini)
- **Minimal Local Computation**: All processing done via cloud APIs

## Architecture

```
Microphone → STT API (Streaming) → LLM API (Streaming) → TTS API (Streaming) → Speaker
```

All components stream data in real-time for low-latency conversation.

## Setup

### Prerequisites

- Raspberry Pi 5 with Raspberry Pi OS
- Microphone and speaker connected
- Python 3.9+

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd casper-pi
```

2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up Google Cloud credentials:
   - Create a Google Cloud project
   - Enable Speech-to-Text API and Text-to-Speech API
   - Create a service account and download the JSON key
   - Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable

5. Configure environment variables:
```bash
cp .env.example .env
# Edit .env and add your API keys
```

Required environment variables:
- `GEMINI_API_KEY`: Your Gemini API key
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to Google Cloud service account JSON

6. Configure settings:
   - Edit `config.yaml` to adjust audio settings, wake word, etc.

### Running

```bash
python main.py
```

The assistant will:
1. Start in idle mode, listening for the wake word
2. When wake word is detected, transition to active mode
3. Stream your voice → STT → LLM → TTS → speaker
4. Return to idle after conversation timeout

## Configuration

### Wake Word

The default wake word is "computer" (pre-trained in Porcupine). You can change it in `config.yaml`:

```yaml
wake_word:
  keyword: computer  # Options: computer, hey siri, alexa, etc.
  sensitivity: 0.5  # 0.0 to 1.0
```

### Audio Settings

```yaml
audio:
  sample_rate: 16000
  channels: 1
  chunk_size: 1024
  input_device: null   # null = default device
  output_device: null  # null = default device
```

### Provider

Currently supports Gemini. To add a new provider:

1. Create `src/providers/your_provider.py`
2. Implement the `BaseProvider` interface
3. Update `config.yaml` to use your provider

## Project Structure

```
casper-pi/
├── main.py                 # Entry point
├── config.yaml             # Configuration
├── requirements.txt        # Dependencies
├── .env.example           # Environment variables template
└── src/
    ├── assistant.py       # Main orchestrator
    ├── wake_word.py       # Wake word detection
    ├── audio_stream.py    # Audio I/O
    ├── utils.py          # Utilities
    └── providers/
        ├── base.py       # Base provider interface
        └── gemini.py    # Gemini provider
```

## Troubleshooting

### Audio Issues

- Check audio devices: `arecord -l` and `aplay -l`
- Test microphone: `arecord -d 5 test.wav && aplay test.wav`
- Adjust device indices in `config.yaml` if needed

### Wake Word Not Detecting

- Try different pre-trained keywords
- Adjust sensitivity in `config.yaml`
- Ensure microphone is working and not muted

### API Errors

- Verify API keys are set correctly in `.env`
- Check Google Cloud credentials are valid
- Ensure APIs are enabled in Google Cloud Console

## License

MIT
