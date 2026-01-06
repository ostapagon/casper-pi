"""Simple voice assistant with wake word detection"""

import json
import pyaudio
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
    
    # Setup audio
    pa = pyaudio.PyAudio()
    
    # Find first available input device
    input_device = None
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            input_device = i
            break
    
    if input_device is None:
        print("Error: No input device found")
        pa.terminate()
        return
    
    # Open stream
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                     input_device_index=input_device, frames_per_buffer=CHUNK)
    
    try:
        while True:
            audio_data = stream.read(CHUNK, exception_on_overflow=False)
            
            if recognizer.AcceptWaveform(audio_data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").lower()
                if WAKE_WORD in text:
                    print(f"✓ '{WAKE_WORD}' detected! ({text})")
                    # TODO: Start Gemini conversation
            else:
                partial = json.loads(recognizer.PartialResult())
                text = partial.get("partial", "").lower()
                if WAKE_WORD in text:
                    print(f"✓ '{WAKE_WORD}' detected! ({text})")
                    # TODO: Start Gemini conversation
                    
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

if __name__ == "__main__":
    main()
