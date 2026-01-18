#!/usr/bin/env python3
"""State manager for voice assistant"""

import asyncio
import pyaudio
from enum import Enum, auto

from .wake_word import WakeWordDetector
from .voice_clients.gemini_live import GeminiLiveClient
from .mcp import MCPRegistry
from .display import DisplayManager, DisplayState


class State(Enum):
    IDLE = auto()
    ACTIVE = auto()


class StateManager:
    """Manages state transitions between IDLE (wake word) and ACTIVE (conversation)"""
    
    def __init__(self):
        self.state = State.IDLE
        self.running = True
        
        # Audio setup
        self.pya = pyaudio.PyAudio()
        self.input_stream = None
        
        # Components
        self.wake_detector = None
        self.gemini_client = None
        self.display_manager = DisplayManager()
    
    def _setup_audio(self):
        """Setup microphone stream"""
        if self.input_stream is None:
            mic = self.pya.get_default_input_device_info()
            self.input_stream = self.pya.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                input_device_index=mic["index"],
                frames_per_buffer=256  # Smaller chunks for lower latency
            )
            print("✓ Mic ready")
    
    async def run(self):
        """Main loop"""
        try:
            self._setup_audio()
            
            # Initialize MCP registry
            mcp_registry = MCPRegistry()
            try:
                await asyncio.wait_for(mcp_registry.initialize(), timeout=10.0)
            except:
                mcp_registry = None
            
            # Initialize components
            self.wake_detector = WakeWordDetector(wake_word="casper", sample_rate=16000)
            self.gemini_client = GeminiLiveClient(mcp_registry=mcp_registry, display_manager=self.display_manager)
            self.gemini_client.input_stream = self.input_stream
            
            # Set display to sleep initially (IDLE state)
            try:
                if not self.display_manager.is_initialized:
                    self.display_manager.initialize()
                    # Small delay to ensure display is ready
                    import time
                    time.sleep(0.5)
                self.display_manager.set_state(DisplayState.SLEEP)
                print("✓ Display set to sleep state")
            except Exception as e:
                print(f"⚠️ Display state warning: {e}")
                import traceback
                traceback.print_exc()
            
            while self.running:
                if self.state == State.IDLE:
                    # IDLE: Wait for wake word
                    print("🎤 Say 'casper'...")
                    wake_event = asyncio.Event()
                    task = asyncio.create_task(
                        self.wake_detector.detect(self.input_stream, 256, lambda: wake_event.set())
                    )
                    await wake_event.wait()
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    
                    # Transition to ACTIVE
                    self.state = State.ACTIVE
                    # Set display to active
                    try:
                        if not self.display_manager.is_initialized:
                            self.display_manager.initialize()
                        self.display_manager.set_state(DisplayState.ACTIVE)
                    except Exception as e:
                        print(f"⚠️ Display state warning: {e}")
                    print("\n🎙️ Starting conversation...")
                
                elif self.state == State.ACTIVE:
                    # ACTIVE: Conversation with Gemini
                    await self.gemini_client.run_conversation()
                    
                    # Back to IDLE
                    self.state = State.IDLE
                    # Set display to sleep
                    try:
                        if self.display_manager.is_initialized:
                            self.display_manager.set_state(DisplayState.SLEEP)
                    except Exception as e:
                        print(f"⚠️ Display state warning: {e}")
                    print("💤 Back to idle\n")
                    self.wake_detector.reset()
        
        except KeyboardInterrupt:
            print("\n👋 Bye!")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        if self.input_stream:
            self.input_stream.close()
        if self.gemini_client and self.gemini_client.output_stream:
            self.gemini_client.output_stream.close()
        if self.display_manager:
            self.display_manager.cleanup()
        self.pya.terminate()

