"""Wake word detection using Vosk"""

import asyncio
import json
import pyaudio
from typing import Callable, Optional
from vosk import Model, KaldiRecognizer


class WakeWordDetector:    
    def __init__(
        self,
        wake_word: str = "casper",
        model_path: str = "assets/vosk-model-small-en-us-0.15",
        sample_rate: int = 16000
    ):
        self.wake_word = wake_word.lower()
        self.sample_rate = sample_rate
        self.model_path = model_path
        
        # Vosk components (initialized lazily)
        self.model: Optional[Model] = None
        self.recognizer: Optional[KaldiRecognizer] = None
        
        # Control
        self.running = False
    
    def _load_model(self) -> None:
        """Load Vosk model (called once on first use)"""
        if self.model is None:
            print(f"Loading wake word model from {self.model_path}...")
            self.model = Model(self.model_path)
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            self.recognizer.SetWords(True)
            print(f"✓ Wake word detector ready (listening for '{self.wake_word}')")
    
    async def detect(
        self,
        audio_stream: pyaudio.Stream,
        chunk_size: int,
        on_wake_word: Callable[[], None]
    ) -> None:
        # Load model if not already loaded
        self._load_model()
        
        self.running = True
        print(f"🎤 Listening for '{self.wake_word}'...")
        
        try:
            while self.running:
                # Read audio chunk (non-blocking via thread pool)
                audio_data = await asyncio.to_thread(
                    audio_stream.read,
                    chunk_size,
                    exception_on_overflow=False
                )
                
                # Process with Vosk
                detected = await self._process_audio_chunk(audio_data)
                
                if detected:
                    print(f"✓ '{self.wake_word}' detected!")
                    # Call callback
                    if asyncio.iscoroutinefunction(on_wake_word):
                        await on_wake_word()
                    else:
                        on_wake_word()
                    # Stop detection after wake word (parent will restart if needed)
                    self.running = False
                    break
                    
        except Exception as e:
            if self.running:  # Only log if not intentionally stopped
                print(f"⚠️ Wake word detection error: {e}")
    
    async def _process_audio_chunk(self, audio_data: bytes) -> bool:
        if self.recognizer is None:
            return False
        
        # Process audio with Vosk (CPU-bound, run in thread pool)
        if await asyncio.to_thread(self.recognizer.AcceptWaveform, audio_data):
            # Final result
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").lower()
            if self.wake_word in text:
                return True
        else:
            # Partial result (for faster detection)
            partial = json.loads(self.recognizer.PartialResult())
            text = partial.get("partial", "").lower()
            if self.wake_word in text:
                return True
        
        return False
    
    def stop(self) -> None:
        self.running = False
    
    def reset(self) -> None:
        if self.recognizer:
            self.recognizer.Reset()

