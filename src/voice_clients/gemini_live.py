#!/usr/bin/env python3
"""Simple Gemini Live voice client"""

import asyncio
import gc
import os
import pyaudio
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from google import genai
from google.genai import types

from ..display import DisplayManager, DisplayToolRegistry
from ..services.memory import MemoryManager

# Load environment variables
load_dotenv()


class GeminiLiveClient:
    """Simple Gemini Live client"""
    
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    INPUT_RATE = 16000
    OUTPUT_RATE = 24000
    INPUT_CHUNK = 512  # Balanced for latency and efficiency
    OUTPUT_CHUNK = 512  # Smaller chunks = lower latency
    
    def __init__(self, api_key=None, model=None, mcp_registry=None, display_manager=None, thread_pool: Optional[ThreadPoolExecutor] = None, enable_memory: bool = True, shared_memory=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        self.thread_pool = thread_pool
        self.verbose_transcripts = os.getenv("VERBOSE_TRANSCRIPTS", "false").lower() == "true"
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment or parameters")
        
        self.client = genai.Client(api_key=self.api_key)
        self.mcp_registry = mcp_registry
        self.agent = None
        
        # Display - use shared instance if provided, otherwise create new (for testing)
        self.display_manager = display_manager or DisplayManager()
        self.display_tool_registry = DisplayToolRegistry(self.display_manager)
        
        # Memory system - use shared instance if provided
        if shared_memory:
            self.memory = shared_memory
            print("✓ Voice assistant using shared memory")
        elif enable_memory and os.getenv("ENABLE_AGENT_MEMORY", "true").lower() == "true":
            # Fallback: create own instance (for testing)
            self.memory = MemoryManager(api_key=self.api_key)
            print("✓ Voice assistant memory enabled")
        else:
            self.memory = None
        
        self.conversation_messages = []
        self.session_id = "voice"
        
        # Audio (input_stream will be provided by StateManager)
        self.pya = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self._output_stream_lock = asyncio.Lock()  # Prevent double-close
        # Audio queues (smaller for faster response)
        self.audio_out = asyncio.Queue(maxsize=15)  # Output buffer
        self.audio_in = asyncio.Queue(maxsize=15)   # Input buffer
        
        # State
        self.active = False
        self.session_start = None
    
    def _build_system_instruction(self, memory_context=None):
        """Build system instruction with optional memory context"""
        base = (
            "You are Casper, a friendly voice assistant. "
            "Respond naturally in short, concise answers. "
            "Call session_end when the user says goodbye. "
            
            "LANGUAGE (CRITICAL): Speak in the SAME language the USER is speaking. "
            "If user speaks English, respond in English. If user speaks Chinese, respond in Chinese. "
            "DO NOT switch languages unless the user switches first. "
            "EXCEPTION: During Anki card review, when showing the answer/back of a card, read the Chinese characters aloud in Chinese (not the pinyin). "
            "For example, if the card shows '课程 - (ke4cheng2)', pronounce '课程' in Chinese. "
            
            "DATA ACCURACY: Use EXACT numbers from tool responses. If get_due_cards returns 42, say 42, not any other number. "
            
            "ANKI: After rating a card, sync with AnkiWeb. Display cards using display_anki_card. Strip HTML from card text. "
            "NEVER call display_set_state during review. "
            
            "DISPLAY: Show retrieved info (calendar, Anki, etc.) using display_show_info. "
            "Keep titles SHORT (2-5 words). "
            
            "MEMORY: Use memory_save_fact and memory_recall. Store facts in English with Latin alphabet."
        )
        
        # Add memory context if available
        if memory_context:
            memory_section = "\n\n=== YOUR MEMORY (use this to personalize responses) ===\n"
            
            if memory_context.get("facts"):
                memory_section += "\nWhat you know about the user:\n"
                for fact in memory_context["facts"][:5]:  # Reduced from 8 to 5
                    memory_section += f"- [{fact['category']}] {fact['fact']}\n"
            
            if memory_context.get("task_patterns"):
                memory_section += "\nCommon tasks:\n"
                for pattern in memory_context["task_patterns"][:3]:  # Reduced from 5 to 3
                    memory_section += f"- {pattern['task']} (used {pattern['frequency']} times)\n"
            
            if memory_context.get("recent_conversations"):
                memory_section += "\nRecent conversation:\n"
                for conv in memory_context["recent_conversations"][:1]:  # Reduced from 2 to 1
                    memory_section += f"- {conv['summary']}\n"
            
            memory_section += "\nUse this information to provide personalized, context-aware responses.\n=== END MEMORY ===\n"
            base += memory_section
        
        return base
    
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
                # Fast timeout for low latency
                msg = await asyncio.wait_for(self.audio_in.get(), timeout=0.01)
                await session.send_realtime_input(audio=msg)
            except asyncio.TimeoutError:
                # Queue empty - minimal yield
                await asyncio.sleep(0.0005)  # 0.5ms yield
            except Exception as e:
                if self._is_fatal_error(e):
                    self.active = False
                break
    
    async def _receive(self, session):
        """Receive from Gemini - handle audio AND tool calls"""
        print("📡 Starting to receive from Gemini...")
        last_activity = 0
        tool_responses_sent = False  # Track if we just sent tool responses
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
                            elif fc.name == "memory_save_fact" and self.memory:
                                # Save fact to memory
                                try:
                                    fact = fc.args.get("fact")
                                    category = fc.args.get("category", "information")
                                    tags = fc.args.get("tags") if isinstance(fc.args.get("tags"), list) else None
                                    scope = fc.args.get("scope")
                                    date = fc.args.get("date")
                                    
                                    saved = self.memory.save_fact(
                                        fact_text=fact,
                                        category=category,
                                        confidence=1.0,
                                        source="voice_explicit",
                                        tags=tags,
                                        scope=scope,
                                        date=date
                                    )
                                    if saved:
                                        print(f"💾 Saved fact: {fact}")
                                    else:
                                        print(f"💾 Fact already exists or failed: {fact}")
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'result': f'Remembered: {fact}' if saved else 'Fact already known'}
                                        )
                                    )
                                except Exception as e:
                                    print(f"   Error saving fact: {e}")
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'error': str(e)}
                                        )
                                    )
                            elif fc.name == "memory_recall" and self.memory:
                                # Recall from memory
                                try:
                                    query = fc.args.get("query", "")
                                    context = self.memory.get_relevant_context(self.session_id, query)
                                    result_text = "I remember:\n"
                                    for fact in context.get("facts", [])[:5]:
                                        result_text += f"- {fact['fact']}\n"
                                    print(f"🧠 Recalled memory about: {query}")
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'result': result_text}
                                        )
                                    )
                                except Exception as e:
                                    print(f"   Error recalling memory: {e}")
                                    function_responses.append(
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=getattr(fc, 'id', None),
                                            response={'error': str(e)}
                                        )
                                    )
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
                                        
                                        # Record in memory
                                        if self.memory:
                                            try:
                                                self.memory.record_task_usage(fc.name, fc.args)
                                            except Exception:
                                                pass
                                        
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
                                
                                # Mark that we sent tool responses (expect Gemini's response next)
                                if not session_ended:
                                    tool_responses_sent = True
                                
                                # End session if session_end was called
                                if session_ended:
                                    # Give Gemini a brief moment to respond
                                    await asyncio.sleep(0.15)
                                    return
                            except Exception as e:
                                if self.active:
                                    print(f"⚠️ Failed to send tool response: {e}")
                                # Still exit if session_end was called
                                if session_ended:
                                    return
                    
                    # Handle transcriptions (from user and assistant)
                    if hasattr(response, 'server_content') and response.server_content:
                        # Check for input transcription (user speech)
                        if hasattr(response.server_content, 'input_transcription') and response.server_content.input_transcription:
                            input_text = response.server_content.input_transcription.text
                            if input_text:
                                # Store user message for memory
                                self.conversation_messages.append({
                                    "role": "user",
                                    "content": input_text,
                                    "timestamp": time.time()
                                })
                                if self.verbose_transcripts:
                                    print(f"   User: {input_text}")
                        
                        # Check for output transcription (assistant speech)
                        if hasattr(response.server_content, 'output_transcription') and response.server_content.output_transcription:
                            output_text = response.server_content.output_transcription.text
                            if output_text:
                                # Store assistant message for memory
                                self.conversation_messages.append({
                                    "role": "assistant",
                                    "content": output_text,
                                    "timestamp": time.time()
                                })
                                if self.verbose_transcripts:
                                    print(f"   Assistant: {output_text}")
                    
                    # Handle audio data
                    if response.data is not None:
                        await self.audio_out.put(response.data)
                    
                    # Check for turn_complete to restart the loop
                    if hasattr(response, 'server_content') and response.server_content:
                        if hasattr(response.server_content, 'turn_complete') and response.server_content.turn_complete:
                            # If we just sent tool responses, this turn_complete is for the tool call
                            # Don't break yet - continue to receive Gemini's spoken response
                            if tool_responses_sent:
                                print(f"   ✓ Tool turn complete (received {last_activity} responses) - waiting for assistant response...")
                                last_activity = 0
                                tool_responses_sent = False  # Reset flag
                                continue  # Continue receiving instead of breaking
                            
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
                    # Fast timeout for low latency playback
                    audio = await asyncio.wait_for(self.audio_out.get(), timeout=0.04)
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
                    # No audio - minimal yield
                    await asyncio.sleep(0.01)
                except OSError:
                    # Audio device error - close and reinitialize
                    self._close_output_stream()
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    # Task cancelled during shutdown - exit cleanly
                    break
                except Exception:
                    if not self.active:
                        break
        finally:
            # Close output stream safely
            try:
                self._close_output_stream()
            except Exception:
                pass  # Ignore errors during shutdown
    
    async def _conversation(self):
        """Run conversation"""
        self.session_start = datetime.now()
        
        # Clear conversation tracking
        self.conversation_messages = []
        
        # Get memory context for this voice session
        memory_context = None
        if self.memory:
            try:
                memory_context = self.memory.get_relevant_context(self.session_id, "voice conversation")
                if memory_context.get('facts') or memory_context.get('recent_conversations'):
                    print(f"📚 Retrieved memory: {len(memory_context.get('facts', []))} facts, "
                          f"{len(memory_context.get('recent_conversations', []))} recent conversations")
            except Exception as e:
                print(f"⚠️ Memory retrieval warning: {e}")
        
        # Build tools list
        function_declarations = [{"name": "session_end"}]
        if self.mcp_registry:
            mcp_tools = self.mcp_registry.get_function_declarations()
            function_declarations.extend(mcp_tools)
        display_tools = self.display_tool_registry.get_function_declarations()
        function_declarations.extend(display_tools)
        
        # Add memory tools
        if self.memory:
            memory_tools = [
                {
                    "name": "memory_save_fact",
                    "description": "Save an important fact about the user for future conversations. Always write facts in English.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "The fact to remember (write in English)"},
                                    "category": {"type": "string", "description": "Category: preference, habit, information, or learning"},
                                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags for filtering (in English)"},
                                    "scope": {"type": "string", "description": "Optional scope: personal or generic"},
                                    "date": {"type": "string", "description": "Optional date (YYYY-MM-DD) if time-related"}
                        },
                        "required": ["fact", "category"]
                    }
                },
                {
                    "name": "memory_recall",
                    "description": "Recall specific information from past conversations. Query in ONLY in  English.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "What to recall from memory (in English)"}
                        },
                        "required": ["query"]
                    }
                }
            ]
            function_declarations.extend(memory_tools)
        
        tools = [{"function_declarations": function_declarations}]
        
        config = {
            "response_modalities": ["AUDIO"],
            "output_audio_transcription": {},  # Enable output transcription
            "input_audio_transcription": {},   # Enable input transcription
            "system_instruction": self._build_system_instruction(memory_context),
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
                    
                    # Wait for cancelled tasks to actually finish (prevent heap corruption)
                    if pending:
                        try:
                            await asyncio.wait_for(
                                asyncio.gather(*pending, return_exceptions=True),
                                timeout=2.0
                            )
                        except asyncio.TimeoutError:
                            pass  # Tasks didn't finish in time, proceed anyway
                        
                except asyncio.CancelledError:
                    # Cancel all tasks if this is cancelled
                    for task in tasks:
                        task.cancel()
                    # Wait for them to actually stop
                    await asyncio.gather(*tasks, return_exceptions=True)
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
    
    def _close_output_stream(self):
        """Safely close output stream (prevents double-free)"""
        # Quick check without lock for performance
        if not self.output_stream:
            return
        
        # Use try-finally to ensure we always release the stream reference
        stream_to_close = self.output_stream
        self.output_stream = None  # Clear immediately to prevent other calls
        
        if stream_to_close:
            try:
                if stream_to_close.is_active():
                    stream_to_close.stop_stream()
            except Exception:
                pass
            try:
                stream_to_close.close()
            except Exception:
                pass
    
    async def _store_memory_async(self, session_id: str, messages: list):
        """Store conversation in memory asynchronously (non-blocking)"""
        try:
            print("💾 Storing voice conversation in memory (background)...")
            
            # Run synchronous memory operations in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            
            # Store conversation summary
            await loop.run_in_executor(
                None,
                lambda: self.memory.store_conversation(session_id, messages)
            )
            # Extract facts only if conversation is substantial (5+ messages)
            if len(messages) >= 5:
                await loop.run_in_executor(
                    None,
                    lambda: self.memory.extract_and_store_facts(messages, source="voice_assistant")
                )
            else:
                print("  (Skipping fact extraction for short conversation)")
            
            print("✓ Voice conversation stored in memory")
        except Exception as e:
            print(f"⚠️ Memory storage warning: {e}")
    
    async def run_conversation(self):
        """Run a single conversation session"""
        self.active = True
        
        # Set display to active when conversation starts (lazy init)
        from ..display.states import DisplayState
        try:
            if not self.display_manager.is_initialized:
                self.display_manager.initialize()
            self.display_manager.set_state(DisplayState.ACTIVE)
        except Exception as e:
            print(f"⚠️ Display state warning: {e}")
        
        # Ensure output stream is closed before starting
        self._close_output_stream()
        
        try:
            await self._conversation()
        except Exception as e:
            print(f"⚠️ Conversation exception: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.active = False
            
            # Clear audio queues FIRST (before closing stream)
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
            
            # Now close output stream safely (after queues are empty)
            try:
                self._close_output_stream()
            except Exception:
                pass  # Ignore errors during shutdown cleanup
            
            # Small delay to ensure PyAudio cleanup completes
            try:
                await asyncio.sleep(0.1)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass  # Ignore if interrupted during cleanup
            
            # Store conversation in memory (async, non-blocking)
            if self.memory and len(self.conversation_messages) >= 2:
                try:
                    # Create a copy of messages to avoid race conditions
                    messages_copy = self.conversation_messages.copy()
                    session_id_copy = self.session_id
                    
                    # Start background task for memory storage
                    asyncio.create_task(self._store_memory_async(session_id_copy, messages_copy))
                except Exception:
                    pass  # Ignore memory storage errors during shutdown
            
            # Force garbage collection to free memory
            gc.collect()
