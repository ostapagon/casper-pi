#!/usr/bin/env python3
"""State manager for voice assistant"""

import asyncio
import pyaudio
from concurrent.futures import ThreadPoolExecutor
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
        self.sample_rate = None  # Store sample rate for components
        
        # Thread pool for blocking I/O (2 threads optimal for Pi stability)
        self.thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="casper-worker")
        
        # Components
        self.wake_detector = None
        self.gemini_client = None
        self.display_manager = DisplayManager()
    
    def _setup_audio(self):
        """Setup microphone stream"""
        if self.input_stream is None:
            print("\n🔍 Audio device detection:")
            print(f"   Total devices: {self.pya.get_device_count()}")
            
            # Show ALL input devices for debugging
            print("\n   Available input devices:")
            for i in range(self.pya.get_device_count()):
                dev = self.pya.get_device_info_by_index(i)
                if dev['maxInputChannels'] > 0:
                    print(f"   [{i}] {dev['name']}")
                    print(f"       Channels: {dev['maxInputChannels']}, Rate: {int(dev['defaultSampleRate'])} Hz")
            
            mic = None
            
            # First, look for USB/hardware devices (not bluetooth/monitor/default source)
            print("\n   Searching for hardware microphones...")
            for i in range(self.pya.get_device_count()):
                dev = self.pya.get_device_info_by_index(i)
                name_lower = dev['name'].lower()
                if dev['maxInputChannels'] > 0:
                    # Skip virtual devices, bluetooth and monitor devices
                    if any(skip in name_lower for skip in ['monitor', 'bluez', 'default source', 'default sink']):
                        print(f"   Skipping: {dev['name']}")
                        continue
                    # Prefer USB/hardware devices
                    if any(hw in name_lower for hw in ['usb', 'hw:', 'powerconf', 'webcam', 'microphone']):
                        mic = dev
                        print(f"   ✓ Found hardware mic: {mic['name']} (index {mic['index']})")
                        break
                    # Accept any real device as fallback
                    elif mic is None:
                        mic = dev
                        print(f"   Candidate: {dev['name']}")
            
            # If no hardware found, try default
            if mic is None:
                try:
                    default = self.pya.get_default_input_device_info()
                    if 'monitor' not in default['name'].lower() and 'bluez' not in default['name'].lower():
                        mic = default
                        print(f"   Using default: {mic['name']} (index {mic['index']})")
                except:
                    pass
            
            # Last resort: any non-monitor input
            if mic is None:
                print("   Falling back to any available input...")
                for i in range(self.pya.get_device_count()):
                    dev = self.pya.get_device_info_by_index(i)
                    if dev['maxInputChannels'] > 0 and 'monitor' not in dev['name'].lower():
                        mic = dev
                        break
            
            if mic is None:
                raise RuntimeError("No suitable input audio device found")
            
            print(f"\n✓ Selected mic: {mic['name']}")
            print(f"  Device index: {mic['index']}")
            print(f"  Channels: {mic['maxInputChannels']}, Native rate: {int(mic['defaultSampleRate'])} Hz")
            
            # Use 16kHz for wake word detection (Vosk model requirement)
            self.sample_rate = 16000
            
            # Use 512 frames - good balance for speech recognition
            self.input_stream = self.pya.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                input_device_index=mic["index"],
                frames_per_buffer=512
            )
            print(f"✓ Mic ready (using {self.sample_rate} Hz for wake word detection)")
    
    async def run(self):
        """Main loop"""
        try:
            self._setup_audio()
            
            # Initialize MCP registry
            mcp_registry = MCPRegistry()
            try:
                await asyncio.wait_for(mcp_registry.initialize(), timeout=10.0)
            except Exception as e:
                print(f"⚠️ MCP initialization warning: {e}")
                mcp_registry = None
            
            # Initialize components - use stored sample rate
            self.wake_detector = WakeWordDetector(wake_word="casper", sample_rate=self.sample_rate, thread_pool=self.thread_pool)
            self.gemini_client = GeminiLiveClient(mcp_registry=mcp_registry, display_manager=self.display_manager, thread_pool=self.thread_pool)
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
                    
                    # Ensure audio stream is ready
                    if not self.input_stream or not self.input_stream.is_active():
                        print("⚠️ Audio stream not active, reopening...")
                        self._close_audio_stream()
                        self._setup_audio()
                        self.gemini_client.input_stream = self.input_stream
                    elif self.gemini_client.input_stream != self.input_stream:
                        self.gemini_client.input_stream = self.input_stream
                    
                    wake_event = asyncio.Event()
                    task = asyncio.create_task(
                        self.wake_detector.detect(self.input_stream, 512, lambda: wake_event.set())
                    )
                    try:
                        await wake_event.wait()
                    finally:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    
                    # Transition to ACTIVE immediately
                    self.state = State.ACTIVE
                    
                    # Set display to active (non-blocking)
                    try:
                        if not self.display_manager.is_initialized:
                            self.display_manager.initialize()
                        self.display_manager.set_state(DisplayState.ACTIVE)
                    except Exception as e:
                        print(f"⚠️ Display state warning: {e}")
                    
                    print("\n🎙️ Starting conversation...")
                
                elif self.state == State.ACTIVE:
                    # ACTIVE: Conversation with Gemini (no timeout - runs until session_end)
                    try:
                        await self.gemini_client.run_conversation()
                    except KeyboardInterrupt:
                        raise  # Re-raise immediately
                    except Exception as e:
                        print(f"⚠️ Conversation error: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # Back to IDLE immediately
                    self.state = State.IDLE
                    
                    # Force garbage collection
                    import gc
                    gc.collect()
                    
                    # Set display to sleep (non-blocking)
                    try:
                        if self.display_manager.is_initialized:
                            self.display_manager.set_state(DisplayState.SLEEP)
                    except Exception as e:
                        print(f"⚠️ Display state warning: {e}")
                    
                    print("💤 Back to idle\n")
                    
                    # Clean up wake detector state
                    try:
                        self.wake_detector.reset()
                    except Exception as e:
                        print(f"⚠️ Wake detector reset warning: {e}")
        
        except KeyboardInterrupt:
            print("\n👋 Bye!")
        except Exception as e:
            print(f"❌ Fatal error in main loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Cleanup MCP registry
            if mcp_registry:
                try:
                    await mcp_registry.cleanup()
                except Exception as e:
                    print(f"⚠️ MCP cleanup warning: {e}")
            self.cleanup()
    
    def _close_audio_stream(self):
        """Close the input audio stream"""
        if self.input_stream:
            try:
                if self.input_stream.is_active():
                    self.input_stream.stop_stream()
                self.input_stream.close()
            except Exception as e:
                print(f"⚠️ Error closing audio stream: {e}")
            self.input_stream = None
    
    def cleanup(self):
        """Cleanup resources - fast and safe"""
        print("🧹 Cleaning up resources...")
        
        # Signal all operations to stop
        if self.gemini_client:
            self.gemini_client.active = False
        
        # Close output stream (resilient)
        if self.gemini_client and self.gemini_client.output_stream:
            try:
                if self.gemini_client.output_stream.is_active():
                    self.gemini_client.output_stream.stop_stream()
                self.gemini_client.output_stream.close()
                self.gemini_client.output_stream = None
                print("  ✓ Output stream closed")
            except Exception:
                pass  # Silent fail
        
        # Close input stream
        try:
            self._close_audio_stream()
            print("  ✓ Input stream closed")
        except Exception:
            pass  # Silent fail
        
        # Cleanup wake detector
        if self.wake_detector:
            try:
                self.wake_detector.cleanup()
                print("  ✓ Wake detector cleaned up")
            except Exception:
                pass  # Silent fail
        
        # Cleanup display
        if self.display_manager:
            try:
                self.display_manager.cleanup()
                print("  ✓ Display cleaned up")
            except Exception:
                pass  # Silent fail
        
        # Shutdown thread pool
        if self.thread_pool:
            try:
                self.thread_pool.shutdown(wait=False, cancel_futures=True)
                print("  ✓ Thread pool shutdown")
            except Exception:
                pass  # Silent fail
        
        # Terminate PyAudio
        try:
            self.pya.terminate()
            print("  ✓ PyAudio terminated")
        except Exception:
            pass  # Silent fail
        
        print("✓ Cleanup complete")

