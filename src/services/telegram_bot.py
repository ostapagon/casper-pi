#!/usr/bin/env python3
"""Telegram bot for Casper voice assistant"""

import asyncio
import logging
import os
import tempfile
from typing import Optional
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from telegram.request import HTTPXRequest

from .task_executor import TaskExecutor
from .agent import Agent

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram bot for executing tasks and processing audio"""
    
    def __init__(
        self,
        task_executor: TaskExecutor,
        agent: Optional[Agent] = None,
        token: Optional[str] = None
    ):
        """Initialize Telegram bot
        
        Args:
            task_executor: TaskExecutor instance
            agent: Agent instance for natural language processing
            token: Telegram bot token (or from TELEGRAM_BOT_TOKEN env var)
        """
        self.task_executor = task_executor
        self.agent = agent
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        
        if not self.token:
            raise ValueError("Telegram bot token required (TELEGRAM_BOT_TOKEN env var or token parameter)")
        
        # Create custom request with longer timeouts (for slow networks like Pi)
        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=30.0,   # 30s to establish connection (default is 5s)
            read_timeout=30.0,      # 30s to read response (default is 5s)
            write_timeout=30.0,     # 30s to send request
            pool_timeout=30.0       # 30s to get connection from pool
        )
        
        self.app = Application.builder().token(self.token).request(request).build()
        self._running = False
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup message and command handlers"""
        
        # Command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("tools", self._cmd_list_tools))
        self.app.add_handler(CommandHandler("history", self._cmd_history))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("clear", self._cmd_clear))
        
        # Message handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self.app.add_handler(MessageHandler(filters.VOICE, self._handle_voice))
        self.app.add_handler(MessageHandler(filters.AUDIO, self._handle_audio))
    
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        mode = "agent" if self.agent else "direct"
        welcome_msg = (
            "🤖 *Casper Pi Bot*\n\n"
            "I can help you execute tasks and process audio.\n\n"
            "*Commands:*\n"
            "/help - Show help\n"
            "/tools - List available tools\n"
            "/history - Show task history\n"
            "/status - Show system status\n"
            "/clear - Clear conversation history\n\n"
            f"*Mode:* {mode.upper()}\n"
        )
        if self.agent:
            welcome_msg += "\n✨ *AI Agent Mode*\nJust tell me what you want in natural language!"
        else:
            welcome_msg += "\n*Usage:*\nSend text commands or voice messages!"
        
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        if self.agent:
            help_msg = (
                "🆘 *Casper Pi Bot Help*\n\n"
                "✨ *AI Agent Mode Enabled*\n\n"
                "Just talk to me naturally! I'll understand and execute the right tools.\n\n"
                "*Examples:*\n"
                "• \"Show me my Anki decks\"\n"
                "• \"How many cards do I have to review?\"\n"
                "• \"What's on my calendar today?\"\n"
                "• \"Display 'Hello' on the screen\"\n"
                "• \"Search the web for Python tutorials\"\n\n"
                "*Voice Messages:*\n"
                "Send voice messages for hands-free interaction!\n\n"
                "*Commands:*\n"
                "/clear - Clear conversation history"
            )
        else:
            help_msg = (
                "🆘 *Casper Pi Bot Help*\n\n"
                "*Direct Mode*\n\n"
                "*Text Commands:*\n"
                "• `tool: <tool_name> <json_args>` - Execute a tool\n"
                "• `display: <text>` - Display text on screen\n\n"
                "*Voice Messages:*\n"
                "Send a voice message and I'll process it\n\n"
                "*Examples:*\n"
                "• `tool: list_decks {}`\n"
                "• `display: Hello World`"
            )
        await update.message.reply_text(help_msg, parse_mode='Markdown')
    
    async def _cmd_list_tools(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /tools command"""
        tools_info = self.task_executor.get_available_tools()
        
        if len(tools_info) == 0:
            await update.message.reply_text("No tools available")
            return
        
        msg = f"🔧 *Available Tools* ({len(tools_info)})\n\n"
        for tool_name, tool_def in tools_info.items():
            msg += f"• `{tool_name}`\n"
            if isinstance(tool_def, dict):
                desc = tool_def.get('description', 'No description')[:100]
                msg += f"  _{desc}_\n\n"
            else:
                msg += f"  _No description_\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /history command"""
        history = self.task_executor.get_history(limit=10)
        
        if not history:
            await update.message.reply_text("No history available")
            return
        
        msg = f"📜 *Recent History* (last {len(history)} tasks)\n\n"
        for entry in history:
            timestamp = entry.get("timestamp", "")
            tool_name = entry.get("tool_name", "unknown")
            exec_time = entry.get("execution_time", 0)
            msg += f"• `{tool_name}` - {exec_time:.2f}s\n"
            msg += f"  {timestamp[:19]}\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        tools_info = self.task_executor.get_available_tools()
        history = self.task_executor.get_history()
        mode = "AI Agent" if self.agent else "Direct"
        
        msg = (
            "📊 *System Status*\n\n"
            f"🧠 Mode: {mode}\n"
            f"🔧 Available tools: {len(tools_info)}\n"
            f"📜 Task history: {len(history)}\n"
            f"🤖 Bot status: Running\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear command"""
        if not self.agent:
            await update.message.reply_text("⚠️ Agent mode not enabled")
            return
        
        user_id = str(update.effective_user.id)
        self.agent.clear_session(user_id)
        await update.message.reply_text("✅ Conversation history cleared!")
    
    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        text = update.message.text
        user_id = str(update.effective_user.id)
        
        try:
            # Parse command
            if text.startswith("tool:"):
                # Direct tool execution: "tool: tool_name {json_args}"
                await self._execute_tool_command(update, text[5:].strip())
            
            elif text.startswith("display:"):
                # Direct display command: "display: text"
                await self._execute_display_command(update, text[8:].strip())
            
            elif self.agent:
                # Natural language processing via agent
                await update.message.reply_text("🤔 Processing...")
                
                result = await self.agent.process(
                    message=text,
                    session_id=f"telegram_{user_id}"
                )
                
                if result.get("success"):
                    response = result.get("response", "Done!")
                    # Split long responses
                    if len(response) > 4000:
                        for i in range(0, len(response), 4000):
                            await update.message.reply_text(response[i:i+4000])
                    else:
                        await update.message.reply_text(response)
                else:
                    error = result.get("error", "Unknown error")
                    await update.message.reply_text(f"❌ Error: {error}")
            
            else:
                # No agent available
                await update.message.reply_text(
                    f"Received: {text}\n\n"
                    "Use `/help` to see available commands."
                )
        
        except Exception as e:
            logger.error(f"Error handling text message: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _execute_tool_command(self, update: Update, command: str):
        """Execute a tool command"""
        try:
            # Parse: "tool_name {json_args}"
            parts = command.split(maxsplit=1)
            tool_name = parts[0]
            arguments = {}
            
            if len(parts) > 1:
                import json
                arguments = json.loads(parts[1])
            
            await update.message.reply_text(f"⚙️ Executing tool: `{tool_name}`...", parse_mode='Markdown')
            
            result = await self.task_executor.execute_tool(tool_name, arguments)
            
            if result.get("success"):
                exec_time = result.get("execution_time", 0)
                result_data = result.get("result", {})
                
                # Format result
                msg = f"✅ Tool executed successfully ({exec_time:.2f}s)\n\n"
                msg += f"```json\n{self._format_result(result_data)}\n```"
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                error = result.get("error", "Unknown error")
                await update.message.reply_text(f"❌ Error: {error}")
        
        except Exception as e:
            logger.error(f"Error executing tool command: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _execute_display_command(self, update: Update, text: str):
        """Execute a display command"""
        try:
            await update.message.reply_text("📺 Displaying on screen...")
            
            result = await self.task_executor.execute_task({
                "type": "display",
                "action": "show_text",
                "title": "Telegram Message",
                "text": text
            })
            
            if result.get("success"):
                await update.message.reply_text("✅ Displayed successfully")
            else:
                error = result.get("error", "Unknown error")
                await update.message.reply_text(f"❌ Error: {error}")
        
        except Exception as e:
            logger.error(f"Error executing display command: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages"""
        user_id = str(update.effective_user.id)
        
        try:
            await update.message.reply_text("🎤 Processing voice message...")
            
            # Download voice file
            voice_file = await update.message.voice.get_file()
            
            # Create temp file
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
                await voice_file.download_to_drive(temp_ogg.name)
                temp_ogg_path = temp_ogg.name
            
            try:
                if self.agent:
                    # Process with agent (supports audio directly)
                    logger.info("Processing voice with agent")
                    
                    result = await self.agent.process(
                        audio_path=temp_ogg_path,
                        audio_mime_type="audio/ogg",
                        session_id=f"telegram_{user_id}"
                    )
                    
                    if result.get("success"):
                        response = result.get("response", "Done!")
                        # Split long responses
                        if len(response) > 4000:
                            for i in range(0, len(response), 4000):
                                await update.message.reply_text(response[i:i+4000])
                        else:
                            await update.message.reply_text(response)
                    else:
                        error = result.get("error", "Unknown error")
                        await update.message.reply_text(f"❌ Error: {error}")
                else:
                    # No agent available
                    await update.message.reply_text(
                        "✅ Voice message received\n\n"
                        "Agent not available - enable AGENT_MODEL in .env for voice processing"
                    )
            
            finally:
                os.unlink(temp_ogg_path)
        
        except Exception as e:
            logger.error(f"Error handling voice message: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle audio files"""
        await update.message.reply_text("🎵 Audio file received (processing not yet implemented)")
    
    def _format_result(self, result, max_length: int = 500) -> str:
        """Format result for display"""
        import json
        result_str = json.dumps(result, indent=2, ensure_ascii=False)
        if len(result_str) > max_length:
            result_str = result_str[:max_length] + "\n... (truncated)"
        return result_str
    
    async def start(self):
        """Start the Telegram bot with retry logic"""
        if self._running:
            logger.warning("Telegram bot already running")
            return
        
        logger.info("Starting Telegram bot")
        self._running = True
        
        # Retry parameters
        max_retries = 3
        retry_delay = 5  # seconds
        
        try:
            for attempt in range(max_retries):
                try:
                    # Initialize and start bot
                    logger.info(f"Attempting to connect to Telegram API (attempt {attempt + 1}/{max_retries})...")
                    await self.app.initialize()
                    await self.app.start()
                    
                    # Start polling
                    await self.app.updater.start_polling(
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True
                    )
                    
                    logger.info("✓ Telegram bot started successfully")
                    
                    # Keep running
                    while self._running:
                        await asyncio.sleep(1)
                    
                    # If we exit the loop cleanly, break retry loop
                    break
                
                except Exception as e:
                    error_msg = str(e)
                    
                    # Check if it's a connection/timeout error
                    if any(x in error_msg for x in ["Timed out", "ConnectTimeout", "Connection", "ConnectError", "NetworkError", "connection attempts failed"]):
                        if attempt < max_retries - 1:
                            logger.warning(f"⚠️ Telegram connection failed (attempt {attempt + 1}/{max_retries}): Connection error")
                            logger.info(f"Retrying in {retry_delay}s...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            continue
                        else:
                            print(f"⚠️ Failed to start Telegram bot: No internet connection or invalid token")
                            print("   Voice assistant and webhook continue running normally")
                            break
                    else:
                        # Other errors, log without full traceback
                        print(f"⚠️ Telegram bot error: {error_msg}")
                        break
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the Telegram bot"""
        if not self._running:
            return
        
        logger.info("Stopping Telegram bot")
        self._running = False
        
        try:
            if self.app.updater and self.app.updater.running:
                await self.app.updater.stop()
            if self.app.running:
                await self.app.stop()
            await self.app.shutdown()
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")
    
    @property
    def is_running(self) -> bool:
        """Check if bot is running"""
        return self._running
