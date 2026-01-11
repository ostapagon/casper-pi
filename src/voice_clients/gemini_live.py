#!/usr/bin/env python3
"""Simple Gemini Live voice client"""

import asyncio
import os
import pyaudio
import struct
import math
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from google import genai

from ..wake_word import WakeWordDetector

# Load environment variables
load_dotenv()


class GeminiLiveClient:
    """Simple Gemini Live client"""
    
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    INPUT_RATE = 16000
    OUTPUT_RATE = 24000
    INPUT_CHUNK = 256  # Smaller = faster streaming (was 512)
    OUTPUT_CHUNK = 480  # Smaller = lower latency (was 960)
    
    def __init__(self, api_key=None, model=None):
        # Load from env if not provided
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment or parameters")
        
        self.client = genai.Client(api_key=self.api_key)
        
        # Audio (input_stream will be provided by StateManager)
        self.pya = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.audio_out = asyncio.Queue(maxsize=5)  # Smaller queue = less buffering
        self.audio_in = asyncio.Queue(maxsize=5)   # Smaller queue = less buffering
        
        # State
        self.active = False  # False=IDLE, True=ACTIVE
        
        # Conversation
        self.conv_history = []
        self.session_start = None
    
    
    def _save_conv(self):
        """Save conversation"""
        if not self.conv_history:
            return
        try:
            import json
            Path("memories").mkdir(exist_ok=True)
            ts = self.session_start.strftime("%Y%m%d_%H%M%S")
            with open(f"memories/chat_{ts}.json", "w") as f:
                json.dump({"timestamp": self.session_start.isoformat(), "messages": self.conv_history}, f, indent=2)
            print(f"💾 Saved")
        except Exception as e:
            print(f"⚠️ Save error: {e}")
    
    async def _capture(self):
        """Capture mic"""
        try:
            while self.active:
                data = await asyncio.to_thread(self.input_stream.read, self.INPUT_CHUNK, exception_on_overflow=False)
                await self.audio_in.put({"data": data, "mime_type": "audio/pcm"})
        except Exception as e:
            return
    
    async def _send(self, session):
        """Send to Gemini - continuous streaming"""
        try:
            while self.active:
                msg = await self.audio_in.get()
                await session.send_realtime_input(audio=msg)
        except Exception as e:
            return
    
    async def _receive(self, session):
        """Receive from Gemini - handle audio AND tool calls"""
        print("🎤 Listening...")
        try:
            while self.active:  # <-- RESTORE THIS OUTER LOOP!
                async for response in session.receive():
                    if not self.active:
                        return
                    
                    # Check for tool calls
                    if hasattr(response, 'tool_call') and response.tool_call:
                        for fc in response.tool_call.function_calls:
                            if fc.name == "session_end":
                                print("👋 Goodbye!")
                                self.active = False
                                return
                    
                    # Handle audio data
                    if response.data is not None:
                        await self.audio_out.put(response.data)
                    
                    # Check for turn_complete to restart the loop
                    if hasattr(response, 'server_content') and response.server_content:
                        if hasattr(response.server_content, 'turn_complete') and response.server_content.turn_complete:
                            break  # Break inner loop, continue outer while loop
                    
        except Exception as e:
            if self.active:
                print(f"⚠️ Connection error: {e}")
            self.active = False
            return
    
    async def _play(self):
        """Play audio"""
        try:
            while self.active:
                try:
                    audio = await asyncio.wait_for(self.audio_out.get(), timeout=0.3)  # Faster timeout
                    if not self.output_stream:
                        self.output_stream = await asyncio.to_thread(
                            self.pya.open, format=self.FORMAT, channels=self.CHANNELS,
                            rate=self.OUTPUT_RATE, output=True, frames_per_buffer=self.OUTPUT_CHUNK
                        )
                    await asyncio.to_thread(self.output_stream.write, audio)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            print(f"[DEBUG] _play ended: {e}")
            return
    
    async def _conversation(self):
        """Run conversation"""
        self.session_start = datetime.now()
        
        # Define session_end tool (matching test script format)
        session_end_tool = {"name": "session_end"}
        tools = [{"function_declarations": [session_end_tool]}]
        
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": (
                "You are Casper, a friendly voice assistant. "
                "Respond naturally and conversationally in short, concise answers. "
                "When the user says goodbye or wants to end the conversation, call the session_end function."
            ),
            "tools": tools
        }
        
        try:
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                print("🤖 Connected!")
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._capture())
                        tg.create_task(self._send(session))
                        tg.create_task(self._receive(session))
                        tg.create_task(self._play())
                except* Exception:
                    pass  # Tasks exited cleanly when self.active became False
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted! Ending session...")
            self.active = False
            raise  # Re-raise to propagate up
        except Exception as e:
            print(f"⚠️ Connection error: {e}")
        
        print("💤 Session ended")
    
    async def run_conversation(self):
        """Run a single conversation session"""
        self.active = True
        self.conv_history = []
        await self._conversation()
        self.active = False
        self._save_conv()
