"""Wake word detection using Vosk"""

import asyncio
import json
import os
import pyaudio
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor

# Suppress Vosk logging
os.environ['VOSK_LOG_LEVEL'] = '-1'

from vosk import Model, KaldiRecognizer


class WakeWordDetector:    
    def __init__(
        self,
        wake_word: str = "casper",
        model_path: str = "assets/vosk-model-small-en-us-0.15",
        sample_rate: int = 16000,
        thread_pool: Optional[ThreadPoolExecutor] = None
    ):
        self.wake_word = wake_word.lower()
        self.sample_rate = sample_rate
        self.model_path = model_path
        self.thread_pool = thread_pool
        
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
        
        # Reset recognizer state before starting (clears previous audio)
        if self.recognizer:
            self.recognizer.Reset()
        
        self.running = True
        print(f"🎤 Listening for '{self.wake_word}'...")
        
        chunk_count = 0  # For throttling debug prints
        
        try:
            while self.running:
                # Read audio chunk (non-blocking via thread pool)
                # Use asyncio.to_thread for better real-time performance
                audio_data = await asyncio.to_thread(
                    audio_stream.read,
                    chunk_size,
                    exception_on_overflow=False
                )
                
                # Process with Vosk
                detected = await self._process_audio_chunk(audio_data, chunk_count)
                chunk_count += 1
                
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
                
                # Small sleep to reduce CPU usage
                await asyncio.sleep(0.01)
                    
        except Exception as e:
            if self.running:  # Only log if not intentionally stopped
                print(f"⚠️ Wake word detection error: {e}")
    
    async def _process_audio_chunk(self, audio_data: bytes, chunk_count: int = 0) -> bool:
        if self.recognizer is None:
            return False
        
        # Process audio with Vosk (CPU-bound, use asyncio.to_thread for real-time performance)
        accepted = await asyncio.to_thread(self.recognizer.AcceptWaveform, audio_data)
        
        if accepted:
            # Final result
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").lower()
            if text:
                print(f"   Heard: '{text}'")
            if self.wake_word in text:
                return True
        else:
            # Partial result (for faster detection)
            partial = json.loads(self.recognizer.PartialResult())
            text = partial.get("partial", "").lower()
            # Only print partials every 10 chunks to reduce spam
            if text and len(text) > 2 and chunk_count % 10 == 0:
                print(f"   (partial: '{text}')", end='\r')
            if self.wake_word in text:
                print()  # New line after partial
                return True
        
        return False
    
    def stop(self) -> None:
        self.running = False
    
    def reset(self) -> None:
        if self.recognizer:
            self.recognizer.Reset()
    
    def cleanup(self) -> None:
        """Cleanup Vosk resources to prevent memory corruption"""
        try:
            if self.recognizer:
                # Reset before cleanup to clear internal state
                try:
                    self.recognizer.Reset()
                except Exception:
                    pass
                self.recognizer = None
            
            # Don't delete model - keep it loaded for reuse
            # self.model = None
        except Exception as e:
            print(f"⚠️ Error cleaning up Vosk: {e}")


