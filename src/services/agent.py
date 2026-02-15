#!/usr/bin/env python3
"""Intelligent agent using Gemini API with long-term memory"""

import asyncio
import os
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from .task_executor import TaskExecutor
from .memory import MemoryManager

logger = logging.getLogger(__name__)


class Agent:
    """Intelligent agent with memory that uses LLM to decide which tools to call"""
    
    def __init__(
        self,
        task_executor: TaskExecutor,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        enable_memory: bool = True,
        shared_memory=None
    ):
        """Initialize agent
        
        Args:
            task_executor: TaskExecutor instance with MCP tools
            api_key: Gemini API key (or from GEMINI_API_KEY env var)
            model: Gemini model (or from AGENT_MODEL env var)
            enable_memory: Enable long-term memory system
            shared_memory: Shared MemoryManager instance (avoids duplicate model loading)
        """
        self.task_executor = task_executor
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("AGENT_MODEL", "gemini-1.5-flash")
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY required for agent")
        
        self.client = genai.Client(api_key=self.api_key)
        
        # Conversation sessions (chat objects)
        self._sessions: Dict[str, Any] = {}
        
        # Message tracking for memory
        self._session_messages: Dict[str, List[Dict[str, Any]]] = {}
        self._message_count: Dict[str, int] = {}
        self._session_summaries: Dict[str, str] = {}
        
        # Memory system - use shared instance if provided
        if shared_memory:
            self.memory = shared_memory
            logger.info("✓ Agent using shared memory")
        elif enable_memory:
            # Fallback: create own instance
            self.memory = MemoryManager(api_key=self.api_key)
            logger.info("✓ Agent memory enabled")
        else:
            self.memory = None
        
        self.enable_memory = bool(self.memory)
    
    async def _store_memory_async(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Store memory in background thread to avoid blocking responses"""
        try:
            loop = asyncio.get_event_loop()
            
            # Store conversation in thread pool (non-blocking)
            await loop.run_in_executor(
                None,
                lambda: self.memory.store_conversation(session_id, messages)
            )
            
            # Extract facts only for substantial conversations (5+ messages)
            if len(messages) >= 5:
                await loop.run_in_executor(
                    None,
                    lambda: self.memory.extract_and_store_facts(messages, source=f"agent_{session_id}")
                )
                logger.info("✓ Memory stored (async)")
            else:
                logger.info("✓ Conversation stored (skipped fact extraction)")
        except Exception as e:
            logger.warning(f"Async memory storage failed: {e}")
    
    def _get_system_instruction(self, memory_context: Optional[Dict[str, Any]] = None) -> str:
        """Get system instruction with optional memory context"""
        from datetime import datetime, timedelta
        
        # Get current date context
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_day = now.strftime("%A")
        
        # Calculate common relative dates
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Find next Friday
        days_until_friday = (4 - now.weekday()) % 7  # Friday is 4
        if days_until_friday == 0:
            days_until_friday = 7  # If today is Friday, get next Friday
        next_friday = (now + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")
        
        base = (
            "You are Casper, a helpful AI assistant with access to various tools. "
            "When users ask you to do something, analyze their request and use the appropriate tools. "
            "You have access to Anki flashcard management, Google Calendar, Perplexity search, and display control. "
            "\n\n"
            "IMPORTANT CONTEXT AWARENESS:\n"
            f"- Today is {current_day}, {current_date}\n"
            f"- Tomorrow is {tomorrow}\n"
            f"- Next Friday is {next_friday}\n"
            "- When users ask about 'next week', 'tomorrow', 'friday', 'next month', etc., "
            "calculate the exact date and use it in tool calls WITHOUT asking the user.\n"
            "- If users ask 'what's happening friday', use the calendar tool with the calculated date.\n"
            "- Be proactive: infer missing information from context (current date, user's habits, etc.) "
            "instead of asking for clarification.\n"
            "\n"
            "Always provide clear, concise responses. "
            "If a task succeeds, confirm what was done. "
            "If a task fails, explain what went wrong. "
            "You can execute multiple tools in sequence if needed.\n"
            "Memory tools available: memory_save_fact to remember user details (ALWAYS write facts in English, "
            "even if conversation is in another language - translate/transliterate as needed), "
            "memory_recall to retrieve specific past information (query in English for best results)."
        )
        
        # Add memory context if available and relevant
        if memory_context:
            memory_section = "\n\n=== Context from past interactions ===\n"
            
            # Session summary (if any)
            session_summary = memory_context.get("session_summary")
            if session_summary:
                memory_section += f"- Recent summary: {session_summary}\n"
            
            # Relevant facts
            facts = memory_context.get("facts", [])
            if facts:
                for fact in facts[:10]:  # Use top 5-10 facts
                    memory_section += f"- {fact['fact']}\n"
                
                memory_section += "\nUse this context naturally when relevant to the conversation.\n"
            
            # Recent conversations (episodic)
            if memory_context.get("recent_conversations"):
                memory_section += "\nRecent conversations:\n"
                for conv in memory_context["recent_conversations"][:3]:
                    summary = conv.get("summary") or "Conversation"
                    memory_section += f"- {summary}\n"
            
            # Task patterns (if relevant)
            if memory_context.get("task_patterns"):
                patterns = memory_context["task_patterns"][:3]
                if patterns:
                    memory_section += "\nCommon tasks: "
                    memory_section += ", ".join([p['task'] for p in patterns])
                    memory_section += "\n"
            
            memory_section += "=== End context ===\n"
            base += memory_section
        
        return base
    
    async def process(
        self,
        message: Optional[str] = None,
        audio_path: Optional[str] = None,
        audio_data: Optional[bytes] = None,
        audio_mime_type: str = "audio/wav",
        session_id: str = "default",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Process a message using the agent with memory
        
        Args:
            message: User message in natural language (text)
            audio_path: Path to audio file (for speech input)
            audio_data: Raw audio bytes (alternative to audio_path)
            audio_mime_type: MIME type of audio
            session_id: Session ID for conversation context
            context: Optional context information
            
        Returns:
            Dict with response and metadata
        """
        if not message and not audio_path and not audio_data:
            return {
                "success": False,
                "error": "Either message, audio_path, or audio_data required",
                "response": "I need a message or audio to process."
            }
        
        start_time = datetime.now()
        
        try:
            # Initialize session tracking
            if session_id not in self._session_messages:
                self._session_messages[session_id] = []
                self._message_count[session_id] = 0
            
            # Get memory context (limit facts to reduce token usage and avoid rate limits)
            memory_context = None
            if self.memory and message:
                memory_context = self.memory.get_relevant_context(session_id, message, max_facts=10)
                logger.info(f"Retrieved memory: {len(memory_context.get('facts', []))} facts, "
                          f"{len(memory_context.get('task_patterns', []))} patterns")
            
            if memory_context is not None and self._session_summaries.get(session_id):
                memory_context["session_summary"] = self._session_summaries[session_id]
            
            # Track user message
            user_content = message if message else f"[Audio: {audio_mime_type}]"
            self._session_messages[session_id].append({
                "role": "user",
                "content": user_content,
                "timestamp": time.time()
            })
            
            # Auto-clear session if conversation gets too long (prevent context overflow & 429 errors)
            if len(self._session_messages[session_id]) > 20:
                logger.info(f"Session {session_id} reached 20+ messages, resetting for fresh context")
                # Store old context in memory before clearing
                if self.memory:
                    messages_copy = self._session_messages[session_id].copy()
                    try:
                        summary = self.memory.summarize_messages(messages_copy)
                        self._session_summaries[session_id] = summary
                        asyncio.create_task(
                            self._store_memory_async(session_id, messages_copy)
                        )
                    except Exception as e:
                        logger.warning(f"Session summary failed: {e}")
                
                # Clear old chat to force recreation with fresh context
                self._sessions.pop(session_id, None)
                # Keep last 4 messages for continuity
                recent_msgs = self._session_messages[session_id][-4:]
                self._session_messages[session_id] = recent_msgs
                self._message_count[session_id] = len(recent_msgs)
            
            # Log input
            if message:
                logger.info(f"Agent processing text: {message[:100]}")
            elif audio_path or audio_data:
                logger.info("Agent processing audio input")
            
            # Get or create chat session
            if session_id not in self._sessions:
                # Build function declarations
                tools_info = self.task_executor.get_available_tools()
                function_declarations = self._build_function_declarations(tools_info)
                
                # Create config with or without tools
                config_params = {
                    "system_instruction": self._get_system_instruction(memory_context),
                    "temperature": 0.7
                }
                
                # Only add tools if we have valid declarations
                if function_declarations:
                    config_params["tools"] = [types.Tool(function_declarations=function_declarations)]
                    logger.info(f"Created chat with {len(function_declarations)} tools")
                else:
                    logger.warning("No valid tools available, creating chat without tools")
                
                # Create new chat with memory-aware system instruction
                chat = self.client.chats.create(
                    model=self.model,
                    config=types.GenerateContentConfig(**config_params)
                )
                self._sessions[session_id] = chat
            else:
                chat = self._sessions[session_id]
            
            # Prepare input
            if audio_path:
                with open(audio_path, 'rb') as f:
                    audio_bytes = f.read()
                input_parts = [types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime_type)]
            elif audio_data:
                input_parts = [types.Part.from_bytes(data=audio_data, mime_type=audio_mime_type)]
            else:
                input_parts = [message]
            
            # Send message with retry
            response = self._send_with_retry(chat, input_parts)
            
            # Handle response and tool calls
            final_response = await self._handle_response(chat, response, session_id)
            
            # Track assistant response
            self._session_messages[session_id].append({
                "role": "assistant",
                "content": final_response,
                "timestamp": time.time()
            })
            self._message_count[session_id] += 1
            
            # Store in memory every 4 messages (async, non-blocking)
            if self.memory and self._message_count[session_id] % 4 == 0:
                # Copy messages to avoid race conditions
                messages_copy = self._session_messages[session_id][-10:].copy()
                # Start background task
                asyncio.create_task(self._store_memory_async(session_id, messages_copy))
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "success": True,
                "response": final_response,
                "session_id": session_id,
                "execution_time": execution_time,
                "model": self.model,
                "input_type": "audio" if (audio_path or audio_data) else "text"
            }
            
        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "success": False,
                "error": str(e),
                "response": f"I encountered an error: {str(e)}",
                "session_id": session_id,
                "execution_time": execution_time
            }
    
    async def _handle_response(self, chat, response, session_id: str) -> str:
        """Handle response from LLM, executing tools if needed"""
        if not response.candidates or len(response.candidates) == 0:
            return "I couldn't generate a response."
        
        candidate = response.candidates[0]
        
        # Extract text and function calls
        text_parts = []
        function_calls = []
        
        if candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
                elif hasattr(part, 'function_call') and part.function_call:
                    function_calls.append(part.function_call)
        
        # No tool calls? Return text
        if not function_calls:
            return ' '.join(text_parts) if text_parts else "I don't have a response."
        
        # Execute tool calls
        logger.info(f"Executing {len(function_calls)} tool call(s)")
        function_responses = []
        
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}
            
            logger.info(f"Calling tool: {tool_name} with args: {tool_args}")
            
            try:
                # Handle memory tools directly
                if self.memory and tool_name == "memory_save_fact":
                    fact = tool_args.get("fact")
                    category = tool_args.get("category", "information")
                    tags = tool_args.get("tags") if isinstance(tool_args.get("tags"), list) else None
                    scope = tool_args.get("scope")
                    date = tool_args.get("date")
                    saved = self.memory.save_fact(
                        fact_text=fact,
                        category=category,
                        confidence=1.0,
                        source="agent_explicit",
                        tags=tags,
                        scope=scope,
                        date=date
                    )
                    result = {"result": f"Remembered: {fact}" if saved else "Fact already known"}
                elif self.memory and tool_name == "memory_recall":
                    query = tool_args.get("query", "")
                    context = self.memory.get_relevant_context(session_id, query)
                    result_text = "I remember:\n"
                    for fact in context.get("facts", [])[:5]:
                        result_text += f"- {fact['fact']}\n"
                    result = {"result": result_text}
                else:
                    # Execute MCP tool
                    result = await self.task_executor.execute_tool(tool_name, tool_args)
                
                # Record in memory
                if self.memory:
                    try:
                        self.memory.record_task_usage(tool_name, tool_args)
                    except Exception:
                        pass
                
                # Build function response
                response_payload = result if isinstance(result, dict) else {"result": result}
                function_responses.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response=response_payload
                    )
                )
                logger.info(f"✓ Tool {tool_name} completed")
                
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                function_responses.append(
                    types.Part.from_function_response(
                        name=tool_name,
                        response={"error": str(e)}
                    )
                )
        
        # Send tool results back to LLM
        if function_responses:
            final_response = self._send_with_retry(chat, function_responses)
            
            # Extract final text
            if final_response.candidates and final_response.candidates[0].content:
                final_text = []
                for part in final_response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        final_text.append(part.text)
                return ' '.join(final_text) if final_text else "Task completed."
        
        return "Task completed successfully."
    
    def _send_with_retry(self, chat, content, max_retries: int = 5):
        """Send message with retry on rate limit (5 retries, ~2s delays each)"""
        import random
        
        for attempt in range(max_retries):
            try:
                return chat.send_message(content)
            except ClientError as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
                
                if is_rate_limit and attempt < max_retries - 1:
                    # Increasing delays: 2s, 3s, 4s, 5s, 6s (+ small jitter)
                    wait_time = (2 + attempt) + random.uniform(0, 0.3)
                    logger.warning(f"Rate limited (429), waiting {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ API Error: {error_str}")
                    if "RESOURCE_EXHAUSTED" in error_str:
                        logger.error("⚠️ API quota issue. Check: https://aistudio.google.com/app/apikey")
                    raise
        raise Exception(f"Max retries ({max_retries}) exceeded")
    
    def _build_function_declarations(self, tools_info: Dict[str, Any]) -> List[types.FunctionDeclaration]:
        """Build Gemini function declarations from MCP tools"""
        declarations = []
        
        for tool_name, tool_def in tools_info.items():
            try:
                # Skip if tool_def is not a dict
                if not isinstance(tool_def, dict):
                    logger.warning(f"Skipping {tool_name}: tool_def is {type(tool_def)}, expected dict")
                    continue
                
                # Get input schema
                input_schema = tool_def.get("inputSchema", {})
                if not isinstance(input_schema, dict):
                    logger.warning(f"Skipping {tool_name}: inputSchema is {type(input_schema)}, expected dict")
                    continue
                
                properties = input_schema.get("properties", {})
                if not isinstance(properties, dict):
                    properties = {}
                
                required = input_schema.get("required", [])
                if not isinstance(required, list):
                    required = []
                
                # Convert properties to Gemini schemas
                gemini_properties = {}
                for prop_name, prop_schema in properties.items():
                    if isinstance(prop_schema, dict):
                        gemini_properties[prop_name] = self._convert_property_to_schema(prop_schema)
                
                # Build parameters
                parameters = types.Schema(
                    type=types.Type.OBJECT,
                    properties=gemini_properties,
                    required=required if required else None
                )
                
                # Create declaration
                declaration = types.FunctionDeclaration(
                    name=tool_name,
                    description=tool_def.get("description", f"Tool: {tool_name}"),
                    parameters=parameters
                )
                
                declarations.append(declaration)
                
            except Exception as e:
                logger.warning(f"Failed to create declaration for {tool_name}: {e}")
        
        # Add memory tools for agent mode
        if self.memory:
            try:
                memory_save = types.FunctionDeclaration(
                    name="memory_save_fact",
                    description="Save an important fact about the user for future conversations. Always write facts in English.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "fact": types.Schema(type=types.Type.STRING, description="The fact to remember (write in English)"),
                            "category": types.Schema(type=types.Type.STRING, description="preference, habit, information, or learning"),
                            "tags": types.Schema(
                                type=types.Type.ARRAY,
                                items=types.Schema(type=types.Type.STRING),
                                description="Optional tags for filtering (in English)"
                            ),
                            "scope": types.Schema(type=types.Type.STRING, description="Optional scope: personal or generic"),
                            "date": types.Schema(type=types.Type.STRING, description="Optional date (YYYY-MM-DD) if time-related")
                        },
                        required=["fact", "category"]
                    )
                )
                memory_recall = types.FunctionDeclaration(
                    name="memory_recall",
                    description="Recall specific information from past conversations. Query in English for best results.",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "query": types.Schema(type=types.Type.STRING, description="What to recall from memory (in English)")
                        },
                        required=["query"]
                    )
                )
                declarations.extend([memory_save, memory_recall])
            except Exception as e:
                logger.warning(f"Failed to create memory tool declarations: {e}")
        
        logger.info(f"Built {len(declarations)} function declarations")
        return declarations
    
    def _convert_property_to_schema(self, prop: Dict[str, Any]) -> types.Schema:
        """Convert JSON schema property to Gemini Schema"""
        prop_type = prop.get("type", "string")
        
        type_mapping = {
            "string": types.Type.STRING,
            "integer": types.Type.INTEGER,
            "number": types.Type.NUMBER,
            "boolean": types.Type.BOOLEAN,
            "array": types.Type.ARRAY,
            "object": types.Type.OBJECT
        }
        
        gemini_type = type_mapping.get(prop_type, types.Type.STRING)
        
        # Build schema
        schema_params = {
            "type": gemini_type,
            "description": prop.get("description")
        }
        
        # Handle arrays
        if gemini_type == types.Type.ARRAY and "items" in prop:
            schema_params["items"] = self._convert_property_to_schema(prop["items"])
        
        # Handle enums
        if "enum" in prop:
            schema_params["enum"] = prop["enum"]
        
        return types.Schema(**{k: v for k, v in schema_params.items() if v is not None})
    
    def get_memory_stats(self) -> Optional[Dict[str, Any]]:
        """Get memory statistics"""
        if not self.memory:
            return None
        return self.memory.get_stats()
    
    def clear_session(self, session_id: str):
        """Clear a specific session (conversation context and local messages)"""
        if session_id in self._sessions:
            del self._sessions[session_id]
        if session_id in self._session_messages:
            del self._session_messages[session_id]
        if session_id in self._message_count:
            del self._message_count[session_id]
        logger.info(f"Cleared session: {session_id}")
