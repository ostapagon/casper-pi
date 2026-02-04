#!/usr/bin/env python3
"""Simple Gemini Live voice client"""

import asyncio
import os
import pyaudio
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from google import genai
from google.genai import types

from ..display import DisplayManager, DisplayToolRegistry

# Load environment variables
load_dotenv()


class GeminiLiveClient:
    """Simple Gemini Live client"""
    
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    INPUT_RATE = 16000
    OUTPUT_RATE = 24000
    INPUT_CHUNK = 512  # Balanced for latency and efficiency
    OUTPUT_CHUNK = 768  # Proportional to output rate
    
    def __init__(self, api_key=None, model=None, mcp_registry=None, display_manager=None, thread_pool: Optional[ThreadPoolExecutor] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        self.thread_pool = thread_pool
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment or parameters")
        
        self.client = genai.Client(api_key=self.api_key)
        self.mcp_registry = mcp_registry
        
        # Display - use shared instance if provided, otherwise create new (for testing)
        self.display_manager = display_manager or DisplayManager()
        self.display_tool_registry = DisplayToolRegistry(self.display_manager)
        
        # Audio (input_stream will be provided by StateManager)
        self.pya = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        # Audio queues (balanced size - not too large to avoid latency buildup)
        self.audio_out = asyncio.Queue(maxsize=30)  # Output buffer
        self.audio_in = asyncio.Queue(maxsize=30)   # Input buffer
        
        # State
        self.active = False
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
        except Exception:
            pass
    
    def _is_fatal_error(self, error):
        """Check if error is fatal (should stop session)"""
        error_str = str(error).lower()
        # WebSocket 1011 = Internal error (known Gemini Live API issue)
        # Don't treat as fatal - let it retry
        if "1011" in error_str:
            print(f"⚠️ WebSocket 1011 error (Gemini API issue): {error}")
            return False
        # Policy violations are fatal
        return "1008" in error_str or "policy violation" in error_str
    
    async def _capture(self):
        """Capture mic"""
        while self.active:
            try:
                if self.thread_pool:
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(
                        self.thread_pool,
                        lambda: self.input_stream.read(self.INPUT_CHUNK, exception_on_overflow=False)
                    )
                else:
                    data = await asyncio.to_thread(self.input_stream.read, self.INPUT_CHUNK, exception_on_overflow=False)
                await self.audio_in.put({"data": data, "mime_type": "audio/pcm"})
            except Exception:
                if self.active:
                    self.active = False
                break
    
    async def _send(self, session):
        """Send to Gemini - continuous streaming with optimal latency"""
        while self.active:
            try:
                # Balanced timeout - fast but not too aggressive
                msg = await asyncio.wait_for(self.audio_in.get(), timeout=0.02)
                await session.send_realtime_input(audio=msg)
            except asyncio.TimeoutError:
                # Queue empty - yield briefly
                await asyncio.sleep(0.001)  # 1ms yield
            except Exception as e:
                if self._is_fatal_error(e):
                    self.active = False
                break
    
    async def _receive(self, session):
        """Receive from Gemini - handle audio AND tool calls"""
        print("📡 Starting to receive from Gemini...")
        last_activity = 0
        while self.active:
            try:
                async for response in session.receive():
                    if not self.active:
                        return
                    
                    last_activity += 1
                    
                    # Check for tool calls
                    if hasattr(response, 'tool_call') and response.tool_call:
                        function_responses = []
                        session_ended = False
                        for fc in response.tool_call.function_calls:
                            # Print tool call parameters
                            print(f"🔧 Tool call: {fc.name}")
                            if fc.args:
                                print(f"   Params: {fc.args}")
                            
                            if fc.name == "session_end":
                                print("👋 Goodbye!")
                                session_ended = True
                                # Send response back before ending
                                function_responses.append(
                                    types.FunctionResponse(
                                        name=fc.name,
                                        id=getattr(fc, 'id', None),
                                        response={'result': 'Session ended'}
                                    )
                                )
                                # Set active to False immediately to stop all tasks
                                self.active = False
                            elif fc.name.startswith("display_"):
                                # Execute display tool
                                try:
                                    result = self.display_tool_registry.execute(fc.name, fc.args or {})
                                    if isinstance(result, dict) and "result" in result:
                                        response_data = result["result"]
                                        print(f"   Display tool result: {response_data}")
                                    elif isinstance(result, dict) and "error" in result:
                                        response_data = {"error": result["error"]}
                                        print(f"   Display tool error: {result['error']}")
                                    else:
                                        response_data = result
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'result': response_data}
                                        )
                                    )
                                except Exception as e:
                                    print(f"   Display tool exception: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'error': str(e)}
                                        )
                                    )
                            elif self.mcp_registry:
                                # Execute MCP tool
                                try:
                                    result = await self.mcp_registry.execute(fc.name, fc.args or {})
                                    # Extract result from formatted response
                                    if isinstance(result, dict) and "result" in result:
                                        response_data = result["result"]
                                    elif isinstance(result, dict) and "error" in result:
                                        response_data = {"error": result["error"]}
                                    else:
                                        response_data = result
                                    
                                    # Print tool result summary
                                    if isinstance(response_data, dict):
                                        # Show summary for common result structures
                                        if "total" in response_data:
                                            print(f"   Result: total={response_data.get('total')}, "
                                                  f"review={response_data.get('breakdown', {}).get('review', {}).get('returned', 0)}, "
                                                  f"new={response_data.get('breakdown', {}).get('new', {}).get('returned', 0)}")
                                        elif "error" in response_data:
                                            print(f"   Result: ERROR - {response_data.get('error')}")
                                        else:
                                            # Show first few keys for other dicts
                                            keys = list(response_data.keys())[:5]
                                            print(f"   Result: {keys} (showing keys only)")
                                    else:
                                        result_str = str(response_data)
                                        if len(result_str) > 200:
                                            result_str = result_str[:200] + "..."
                                        print(f"   Result: {result_str}")
                                    
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'result': response_data}
                                        )
                                    )
                                except Exception as e:
                                    print(f"   Error: {e}")
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'error': str(e)}
                                        )
                                    )
                        
                        # Send function responses back using correct API
                        if function_responses:
                            try:
                                tool_response = types.LiveClientToolResponse(
                                    function_responses=function_responses
                                )
                                await session.send(input=tool_response)
                                
                                # End session if session_end was called
                                if session_ended:
                                    # Give Gemini a moment to respond
                                    await asyncio.sleep(0.3)
                                    return
                            except Exception as e:
                                if self.active:
                                    print(f"⚠️ Failed to send tool response: {e}")
                                # Still exit if session_end was called
                                if session_ended:
                                    return
                    
                    # Handle audio data
                    if response.data is not None:
                        await self.audio_out.put(response.data)
                    
                    # Check for turn_complete to restart the loop
                    if hasattr(response, 'server_content') and response.server_content:
                        if hasattr(response.server_content, 'turn_complete') and response.server_content.turn_complete:
                            print(f"   ✓ Turn complete (received {last_activity} responses)")
                            last_activity = 0
                            break
                
            except asyncio.CancelledError:
                return
            except Exception as e:
                if self._is_fatal_error(e):
                    self.active = False
                    return
                if not self.active:
                    return
                await asyncio.sleep(0.1)
    
    async def _play(self):
        """Play audio with optimal latency"""
        print("🔊 Audio playback ready...")
        try:
            while self.active:
                try:
                    # Balanced timeout for responsive playback
                    audio = await asyncio.wait_for(self.audio_out.get(), timeout=0.08)
                    if not self.output_stream:
                        print("   Opening output stream...")
                        if self.thread_pool:
                            loop = asyncio.get_event_loop()
                            self.output_stream = await loop.run_in_executor(
                                self.thread_pool,
                                lambda: self.pya.open(
                                    format=self.FORMAT, channels=self.CHANNELS,
                                    rate=self.OUTPUT_RATE, output=True, frames_per_buffer=self.OUTPUT_CHUNK
                                )
                            )
                        else:
                            self.output_stream = await asyncio.to_thread(
                                self.pya.open, format=self.FORMAT, channels=self.CHANNELS,
                                rate=self.OUTPUT_RATE, output=True, frames_per_buffer=self.OUTPUT_CHUNK
                            )
                    
                    if self.thread_pool:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(self.thread_pool, self.output_stream.write, audio)
                    else:
                        await asyncio.to_thread(self.output_stream.write, audio)
                except asyncio.TimeoutError:
                    # No audio - brief yield
                    await asyncio.sleep(0.001)
                except OSError:
                    # Audio device error - try to reinitialize
                    if self.output_stream:
                        try:
                            self.output_stream.close()
                        except:
                            pass
                        self.output_stream = None
                    await asyncio.sleep(0.1)
                except Exception:
                    if not self.active:
                        break
        finally:
            if self.output_stream:
                try:
                    self.output_stream.close()
                except:
                    pass
                self.output_stream = None
    
    async def _conversation(self):
        """Run conversation"""
        self.session_start = datetime.now()
        
        # Build tools list
        function_declarations = [{"name": "session_end"}]
        if self.mcp_registry:
            mcp_tools = self.mcp_registry.get_function_declarations()
            function_declarations.extend(mcp_tools)
        display_tools = self.display_tool_registry.get_function_declarations()
        function_declarations.extend(display_tools)
        
        tools = [{"function_declarations": function_declarations}]
        
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": (
                "You are Casper, a friendly voice assistant. "
                "Respond naturally and conversationally in short, concise answers. "
                "When the user says goodbye or wants to end the conversation, call the session_end function. "
                
                "LANGUAGE: Always respond in the same language the user is speaking to you. "
                "Detect if the user speaks English, Ukrainian (українська), or Chinese (中文), and respond in that language. "
                "Match the user's language throughout the entire conversation. "
                
                "IMPORTANT: After rating an Anki card (using rate_card), always call the sync tool to sync with AnkiWeb. "
                
                "When reviewing Anki cards: call display_anki_card with front text to show the question, then call it again with show_back=true after the user answers to show both front and back. Keep the card displayed on screen while reviewing. IMPORTANT: Only call display_set_state('active') when the review session is COMPLETELY FINISHED and you're ready to return to normal conversation - do NOT switch to active immediately after showing one card. The display has animations for sleep/idle states but not for active state. "
                
                "When showing calendar events: After retrieving calendar data (using list_calendar_events), ALWAYS display the events on screen using display_show_info. Format the events clearly with title like 'Your Schedule for [date]' and each event as a separate line showing time and event name. For example: '3:00 PM - Meeting', '5:00 PM - Dinner', etc. "
                
                "When showing Anki statistics or deck info: After getting Anki data (using get_due_cards or list_decks), use display_show_info to show the key information on screen - like number of cards due, deck names, review status, etc. "
                
                "General display rule: Whenever you retrieve structured information (calendar, Anki, lists, schedules), use display_show_info to show it visually on screen while you speak about it. This helps the user see the information clearly. The display animations work best for sleep and idle states."
            ),
            "tools": tools
        }
        
        try:
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                # Create tasks and store references for cancellation
                capture_task = asyncio.create_task(self._capture())
                send_task = asyncio.create_task(self._send(session))
                receive_task = asyncio.create_task(self._receive(session))
                play_task = asyncio.create_task(self._play())
                
                tasks = [capture_task, send_task, receive_task, play_task]
                
                try:
                    # Wait for any task to complete (likely _receive when session_end is called)
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    
                    # Cancel remaining tasks
                    for task in pending:
                        task.cancel()
                    
                    # Wait for cancelled tasks to finish (with timeout)
                    if pending:
                        await asyncio.wait(pending, timeout=1.0)
                        
                except asyncio.CancelledError:
                    # Cancel all tasks if this is cancelled
                    for task in tasks:
                        task.cancel()
                    raise
        except* Exception as e:
            # Check for fatal errors and log all errors
            for exc in e.exceptions:
                error_str = str(exc)
                print(f"⚠️ Conversation exception: {error_str}")
                if "1011" in error_str:
                    print("   (Known Gemini Live API WebSocket issue - will retry)")
                if self._is_fatal_error(exc):
                    self.active = False
    
    async def run_conversation(self):
        """Run a single conversation session"""
        self.active = True
        self.conv_history = []
        
        # Set display to active when conversation starts (lazy init)
        from ..display.states import DisplayState
        try:
            if not self.display_manager.is_initialized:
                self.display_manager.initialize()
            self.display_manager.set_state(DisplayState.ACTIVE)
        except Exception as e:
            print(f"⚠️ Display state warning: {e}")
        
        # Ensure output stream is closed before starting
        if self.output_stream:
            try:
                if self.output_stream.is_active():
                    self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception as e:
                print(f"⚠️ Error closing previous output stream: {e}")
            self.output_stream = None
        
        try:
            await self._conversation()
        except Exception as e:
            print(f"⚠️ Conversation exception: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.active = False
            
            # Clean up output stream
            if self.output_stream:
                try:
                    if self.output_stream.is_active():
                        self.output_stream.stop_stream()
                    self.output_stream.close()
                except Exception as e:
                    print(f"⚠️ Error closing output stream: {e}")
                self.output_stream = None
            
            # Clear audio queues (more aggressive cleanup)
            try:
                # Clear output queue
                cleared_out = 0
                while not self.audio_out.empty():
                    try:
                        self.audio_out.get_nowait()
                        cleared_out += 1
                    except:
                        break
                
                # Clear input queue
                cleared_in = 0
                while not self.audio_in.empty():
                    try:
                        self.audio_in.get_nowait()
                        cleared_in += 1
                    except:
                        break
                
                if cleared_out > 0 or cleared_in > 0:
                    print(f"  ✓ Cleared {cleared_out} output, {cleared_in} input audio chunks")
            except Exception as e:
                print(f"⚠️ Error clearing audio queues: {e}")
            
            # Save conversation
            try:
                self._save_conv()
            except Exception as e:
                print(f"⚠️ Error saving conversation: {e}")
            
            # Force garbage collection to free memory
            import gc
            gc.collect()
