"""Simple voice assistant with wake word detection"""

import json
import subprocess
from vosk import Model, KaldiRecognizer

RATE = 16000
WAKE_WORD = "casper"
MODEL_PATH = "assets/vosk-model-small-en-us-0.15"
CHUNK = 4000

def main():
    # Load model
    print("Loading model...")
    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, RATE)
    recognizer.SetWords(True)
    
    print(f"Listening for '{WAKE_WORD}'... (Ctrl+C to stop)")
    
    # Start audio recording
    cmd = ['pw-record', '--rate', str(RATE), '--channels', '1', '--format', 's16', '-']
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    try:
        while True:
            # Read audio chunk
            audio_data = process.stdout.read(CHUNK * 2)
            if not audio_data:
                if process.poll() is not None:
                    break
                continue
            
            # Detect wake word
            if recognizer.AcceptWaveform(audio_data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").lower()
                if WAKE_WORD in text:
                    print(f"✓ '{WAKE_WORD}' detected! ({text})")
                    # TODO: Start Gemini conversation here
                    print("(Gemini API integration coming soon)")
            else:
                partial = json.loads(recognizer.PartialResult())
                text = partial.get("partial", "").lower()
                if WAKE_WORD in text:
                    print(f"✓ '{WAKE_WORD}' detected! ({text})")
                    # TODO: Start Gemini conversation here
                    print("(Gemini API integration coming soon)")
                    
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        process.terminate()

if __name__ == "__main__":
    main()
