#!/usr/bin/env python3
"""State manager for voice assistant"""

import asyncio
import os
import logging
import pyaudio
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum, auto
from typing import Optional

from .wake_word import WakeWordDetector
from .voice_clients.gemini_live import GeminiLiveClient
from .mcp import MCPRegistry
from .display import DisplayManager, DisplayState

# Import services
from .services.task_executor import TaskExecutor
from .services.agent import Agent
from .services.webhook_server import WebhookServer
from .services.telegram_bot import TelegramBot


class State(Enum):
    IDLE = auto()
    ACTIVE = auto()


class StateManager:
    """Manages state transitions between IDLE (wake word) and ACTIVE (conversation)"""
    
    def __init__(self, enable_webhook: bool = None, enable_telegram: bool = None):
        """Initialize StateManager
        
        Args:
            enable_webhook: Enable webhook server (defaults to ENABLE_WEBHOOK env var)
            enable_telegram: Enable Telegram bot (defaults to ENABLE_TELEGRAM env var)
        """
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
        
        # Services (optional)
        self.task_executor = None
        self.agent = None
        self.webhook_server = None
        self.telegram_bot = None
        
        # Service configuration
        self.enable_webhook = enable_webhook if enable_webhook is not None else os.getenv("ENABLE_WEBHOOK", "false").lower() in ("true", "1", "yes")
        self.enable_telegram = enable_telegram if enable_telegram is not None else os.getenv("ENABLE_TELEGRAM", "false").lower() in ("true", "1", "yes")
        
        # Background tasks
        self._background_tasks = []
    
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
            
            # Initialize shared memory manager (load embedding model once)
            shared_memory = None
            if os.getenv("ENABLE_AGENT_MEMORY", "true").lower() == "true":
                from .services.memory import MemoryManager
                try:
                    shared_memory = MemoryManager(api_key=os.getenv("GEMINI_API_KEY"))
                    print("✓ Shared memory initialized")
                except Exception as e:
                    print(f"⚠️ Memory initialization warning: {e}")
            
            # Initialize components - use stored sample rate and shared memory
            self.wake_detector = WakeWordDetector(wake_word="casper", sample_rate=self.sample_rate, thread_pool=self.thread_pool)
            self.gemini_client = GeminiLiveClient(
                mcp_registry=mcp_registry,
                display_manager=self.display_manager,
                thread_pool=self.thread_pool,
                shared_memory=shared_memory
            )
            self.gemini_client.input_stream = self.input_stream
            
            # Initialize services if enabled
            await self._initialize_services(mcp_registry, shared_memory)
            
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
            
            # Cleanup services
            await self._cleanup_services()
            
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
    
    async def _initialize_services(self, mcp_registry: Optional[MCPRegistry], shared_memory=None):
        """Initialize webhook and telegram services"""
        try:
            # Create task executor
            self.task_executor = TaskExecutor(
                mcp_registry=mcp_registry,
                display_manager=self.display_manager
            )
            
            # Create agent (for natural language processing) with shared memory
            try:
                self.agent = Agent(
                    task_executor=self.task_executor,
                    shared_memory=shared_memory
                )
                print("✓ Agent initialized (natural language support enabled)")
            except Exception as e:
                print(f"⚠️ Failed to initialize agent: {e}")
                print("   Services will work without natural language processing")
                self.agent = None
            
            # Start webhook server
            if self.enable_webhook:
                try:
                    webhook_host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
                    webhook_port = int(os.getenv("WEBHOOK_PORT", "8080"))
                    
                    self.webhook_server = WebhookServer(
                        task_executor=self.task_executor,
                        agent=self.agent,
                        host=webhook_host,
                        port=webhook_port
                    )
                    
                    # Start in background
                    webhook_task = asyncio.create_task(self.webhook_server.start())
                    self._background_tasks.append(webhook_task)
                    
                    print(f"✓ Webhook server starting on {webhook_host}:{webhook_port}")
                except Exception as e:
                    print(f"⚠️ Failed to start webhook server: {e}")
            
            # Start Telegram bot
            if self.enable_telegram:
                try:
                    self.telegram_bot = TelegramBot(
                        task_executor=self.task_executor,
                        agent=self.agent
                    )
                    
                    # Start in background
                    telegram_task = asyncio.create_task(self.telegram_bot.start())
                    self._background_tasks.append(telegram_task)
                    
                    print("✓ Telegram bot starting")
                except Exception as e:
                    print(f"⚠️ Failed to start Telegram bot: {e}")
        
        except Exception as e:
            print(f"⚠️ Failed to initialize services: {e}")
    
    async def _cleanup_services(self):
        """Cleanup webhook and telegram services"""
        # Stop webhook server
        if self.webhook_server:
            try:
                await self.webhook_server.stop()
                print("  ✓ Webhook server stopped")
            except Exception as e:
                print(f"⚠️ Error stopping webhook: {e}")
        
        # Stop Telegram bot
        if self.telegram_bot:
            try:
                await self.telegram_bot.stop()
                print("  ✓ Telegram bot stopped")
            except Exception as e:
                print(f"⚠️ Error stopping Telegram bot: {e}")
        
        # Cancel background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to complete
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        self._background_tasks.clear()
    
    def cleanup(self):
        """Cleanup resources - fast and safe"""
        print("🧹 Cleaning up resources...")
        
        # Signal all operations to stop
        if self.gemini_client:
            self.gemini_client.active = False
            # Use safe close method (prevents double-free)
            try:
                self.gemini_client._close_output_stream()
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

