"""Main voice assistant orchestrator with state machine"""

import asyncio
from typing import Optional
from src.wake_word import WakeWordDetector
from src.audio_stream import AudioStream
from src.providers.base import BaseProvider
from src.providers.gemini import GeminiProvider


class VoiceAssistant:
    """Main voice assistant with idle/active state management."""
    
    def __init__(self, config: dict):
        """
        Initialize voice assistant.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.state = "idle"  # idle or active
        
        # Initialize components
        self.wake_word_detector: Optional[WakeWordDetector] = None
        self.audio_stream: Optional[AudioStream] = None
        self.provider: Optional[BaseProvider] = None
        
        # Conversation state
        self.conversation_history = []
        self.conversation_timeout = config.get('assistant', {}).get('conversation_timeout', 30)
        self.last_activity_time = None
        
    async def initialize(self) -> None:
        """Initialize all components."""
        # Initialize wake word detector
        wake_word_config = self.config.get('wake_word', {})
        self.wake_word_detector = WakeWordDetector(
            keyword=wake_word_config.get('keyword', 'computer'),
            sensitivity=wake_word_config.get('sensitivity', 0.5)
        )
        self.wake_word_detector.initialize()
        
        # Initialize audio stream
        audio_config = self.config.get('audio', {})
        self.audio_stream = AudioStream(
            sample_rate=audio_config.get('sample_rate', 16000),
            channels=audio_config.get('channels', 1),
            chunk_size=audio_config.get('chunk_size', 1024),
            input_device=audio_config.get('input_device'),
            output_device=audio_config.get('output_device')
        )
        
        # Initialize provider
        provider_name = self.config.get('provider', {}).get('name', 'gemini')
        if provider_name == 'gemini':
            self.provider = GeminiProvider()
        else:
            raise ValueError(f"Unknown provider: {provider_name}")
        
        await self.provider.initialize(self.config)
        
        print("Voice assistant initialized")
        print(f"Wake word: {wake_word_config.get('keyword', 'computer')}")
        print(f"Provider: {provider_name}")
        print("Listening for wake word...")
    
    async def run(self) -> None:
        """Main run loop."""
        await self.initialize()
        
        try:
            # Main loop
            while True:
                if self.state == "idle":
                    await self._idle_loop()
                elif self.state == "active":
                    await self._active_loop()
                else:
                    await asyncio.sleep(0.1)
        finally:
            await self.cleanup()
    
    async def _idle_loop(self) -> None:
        """Idle state: listen for wake word."""
        # Ensure audio stream is initialized for wake word detection
        if not self.audio_stream.input_stream:
            self.audio_stream.initialize_input()
        
        # Set callback for wake word detection
        def on_wake_word():
            # Schedule wake word handler
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._wake_word_detected())
        
        self.wake_word_detector.set_callback(on_wake_word)
        
        # Process audio frames for wake word detection
        # Porcupine needs specific frame length
        frame_length = self.wake_word_detector.get_frame_length()
        sample_rate = self.wake_word_detector.get_sample_rate()
        
        # Check sample rate compatibility
        if self.audio_stream.sample_rate != sample_rate:
            print(f"Warning: Audio sample rate {self.audio_stream.sample_rate}Hz doesn't match wake word requirement {sample_rate}Hz")
            print("Wake word detection may not work correctly. Consider adjusting audio sample_rate in config.yaml")
        
        # Buffer for wake word detection
        buffer = b''
        frame_size = frame_length * 2  # 2 bytes per sample (int16)
        
        try:
            async for audio_chunk in self.audio_stream.stream_microphone():
                # Check if we've transitioned to active state
                if self.state != "idle":
                    break
                
                buffer += audio_chunk
                
                # Process complete frames
                while len(buffer) >= frame_size and self.state == "idle":
                    frame = buffer[:frame_size]
                    buffer = buffer[frame_size:]
                    
                    # Check for wake word
                    try:
                        if self.wake_word_detector.process(frame):
                            # Wake word detected - transition handled by callback
                            await asyncio.sleep(0.1)  # Brief pause
                            break
                    except Exception as e:
                        print(f"Error in wake word detection: {e}")
                        await asyncio.sleep(0.1)
                
                # Small delay to prevent CPU spinning
                await asyncio.sleep(0.01)
        except Exception as e:
            print(f"Error in idle loop: {e}")
            await asyncio.sleep(1.0)
    
    async def _wake_word_detected(self) -> None:
        """Handle wake word detection - transition to active state."""
        if self.state == "idle":
            print("\nWake word detected! Starting conversation...")
            self.state = "active"
            self.last_activity_time = asyncio.get_event_loop().time()
    
    async def _active_loop(self) -> None:
        """Active state: handle voice conversation with streaming pipeline."""
        print("Active - listening for your input...")
        
        # Ensure audio streams are initialized
        if not self.audio_stream.input_stream:
            self.audio_stream.initialize_input()
        if not self.audio_stream.output_stream:
            self.audio_stream.initialize_output()
        
        # Create streaming pipeline: Mic → STT → LLM → TTS → Speaker
        try:
            # Start microphone stream
            mic_stream = self.audio_stream.stream_microphone()
            
            # STT: Audio chunks → Text chunks (streaming)
            text_stream = self.provider.stream_speech_to_text(mic_stream)
            
            # Collect text chunks until we have a complete utterance
            collected_text = ""
            text_buffer = []
            last_text_time = asyncio.get_event_loop().time()
            silence_threshold = 2.0  # seconds of silence to consider utterance complete
            
            print("Listening... ", end='', flush=True)
            
            async def process_text_stream():
                nonlocal collected_text, last_text_time
                async for text_chunk in text_stream:
                    if text_chunk and text_chunk.strip():
                        text_buffer.append(text_chunk)
                        collected_text += text_chunk
                        last_text_time = asyncio.get_event_loop().time()
                        print(text_chunk, end='', flush=True)
            
            # Process text stream
            text_task = asyncio.create_task(process_text_stream())
            
            # Wait for utterance completion (silence threshold)
            while True:
                current_time = asyncio.get_event_loop().time()
                silence_duration = current_time - last_text_time
                
                # If we have text and silence threshold reached, process it
                if collected_text.strip() and silence_duration >= silence_threshold:
                    text_task.cancel()
                    try:
                        await text_task
                    except asyncio.CancelledError:
                        pass
                    break
                
                # Check for overall timeout
                if silence_duration > self.conversation_timeout:
                    if not collected_text.strip():
                        print("\nNo input detected, returning to idle...")
                        text_task.cancel()
                        self.state = "idle"
                        return
                    else:
                        # Process what we have
                        text_task.cancel()
                        try:
                            await text_task
                        except asyncio.CancelledError:
                            pass
                        break
                
                await asyncio.sleep(0.1)
            
            # Process the collected text
            if collected_text.strip():
                print(f"\nUser: {collected_text}")
                
                # Create text stream from collected text
                async def text_chunk_stream():
                    for chunk in text_buffer:
                        yield chunk
                
                # LLM: Text → Response text (streaming)
                print("Assistant: ", end='', flush=True)
                response_stream = self.provider.stream_generate_response(
                    text_chunk_stream(),
                    self.conversation_history
                )
                
                # Collect response for TTS
                response_text = ""
                async for response_chunk in response_stream:
                    response_text += response_chunk
                    print(response_chunk, end='', flush=True)
                
                print()  # New line after response
                
                if response_text.strip():
                    # TTS: Response text → Audio (streaming)
                    async def response_text_stream():
                        yield response_text
                    
                    audio_stream = self.provider.stream_text_to_speech(response_text_stream())
                    
                    # Play audio chunks as they arrive
                    async for audio_chunk in audio_stream:
                        await self.audio_stream.play_audio(audio_chunk)
                
                self.last_activity_time = asyncio.get_event_loop().time()
                
                # Continue conversation (wait a bit then loop for next turn)
                await asyncio.sleep(1.0)
            else:
                # No text collected, return to idle
                print("\nNo valid input, returning to idle...")
                self.state = "idle"
                
        except Exception as e:
            print(f"\nError in active loop: {e}")
            import traceback
            traceback.print_exc()
            self.state = "idle"
    
    async def cleanup(self) -> None:
        """Clean up all resources."""
        print("\nCleaning up...")
        
        if self.wake_word_detector:
            self.wake_word_detector.cleanup()
        
        if self.audio_stream:
            self.audio_stream.cleanup()
        
        if self.provider:
            await self.provider.cleanup()
        
        print("Cleanup complete")

