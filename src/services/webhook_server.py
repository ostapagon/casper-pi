#!/usr/bin/env python3
"""Webhook server using FastAPI"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from .task_executor import TaskExecutor
from .agent import Agent

logger = logging.getLogger(__name__)


# Request models
class AgentRequest(BaseModel):
    """Request to process message via agent"""
    message: str
    session_id: Optional[str] = "default"
    context: Optional[Dict[str, Any]] = None


class ToolCallRequest(BaseModel):
    """Request to execute a tool directly (bypass agent)"""
    tool_name: str
    arguments: Dict[str, Any] = {}


class TaskRequest(BaseModel):
    """Request to execute a generic task directly (bypass agent)"""
    type: str  # 'tool_call', 'display', 'custom'
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    action: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    state: Optional[str] = None
    handler: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class WebhookServer:
    """Webhook server for external task execution"""
    
    def __init__(
        self,
        task_executor: TaskExecutor,
        agent: Optional[Agent] = None,
        host: str = "0.0.0.0",
        port: int = 8080
    ):
        """Initialize webhook server
        
        Args:
            task_executor: TaskExecutor instance
            agent: Agent instance for natural language processing
            host: Server host (default: 0.0.0.0)
            port: Server port (default: 8080)
        """
        self.task_executor = task_executor
        self.agent = agent
        self.host = host
        self.port = port
        self.app = FastAPI(
            title="Casper Pi Webhook API",
            description="Webhook API for Casper voice assistant",
            version="0.1.0"
        )
        self._server = None
        self._running = False
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup API routes"""
        
        @self.app.get("/")
        async def root():
            """Root endpoint"""
            return {
                "service": "Casper Pi Webhook API",
                "version": "0.1.0",
                "status": "running",
                "timestamp": datetime.now().isoformat()
            }
        
        @self.app.get("/health")
        async def health():
            """Health check endpoint"""
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat()
            }
        
        @self.app.post("/agent")
        async def agent_process(request: AgentRequest):
            """Process message through agent (natural language)"""
            if not self.agent:
                raise HTTPException(status_code=503, detail="Agent not available")
            
            try:
                result = await self.agent.process(
                    message=request.message,
                    session_id=request.session_id,
                    context=request.context
                )
                return result
            except Exception as e:
                logger.error(f"Agent error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.delete("/agent/session/{session_id}")
        async def clear_session(session_id: str):
            """Clear agent conversation session"""
            if not self.agent:
                raise HTTPException(status_code=503, detail="Agent not available")
            
            self.agent.clear_session(session_id)
            return {"message": f"Session {session_id} cleared"}
        
        @self.app.get("/tools")
        async def list_tools():
            """List available tools"""
            return self.task_executor.get_available_tools()
        
        @self.app.post("/tools/execute")
        async def execute_tool(request: ToolCallRequest):
            """Execute a tool"""
            try:
                result = await self.task_executor.execute_tool(
                    request.tool_name,
                    request.arguments
                )
                return result
            except Exception as e:
                logger.error(f"Error executing tool: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.post("/tasks/execute")
        async def execute_task(request: TaskRequest):
            """Execute a generic task"""
            try:
                task = request.dict(exclude_none=True)
                result = await self.task_executor.execute_task(task)
                return result
            except Exception as e:
                logger.error(f"Error executing task: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/history")
        async def get_history(limit: Optional[int] = None):
            """Get task execution history"""
            return {
                "history": self.task_executor.get_history(limit=limit),
                "total": len(self.task_executor.get_history())
            }
        
        @self.app.delete("/history")
        async def clear_history():
            """Clear task execution history"""
            self.task_executor.clear_history()
            return {"message": "History cleared"}
    
    async def start(self):
        """Start the webhook server"""
        if self._running:
            logger.warning("Webhook server already running")
            return
        
        logger.info(f"Starting webhook server on {self.host}:{self.port}")
        
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False  # Reduce noise
        )
        self._server = uvicorn.Server(config)
        self._running = True
        
        try:
            await self._server.serve()
        except Exception as e:
            logger.error(f"Webhook server error: {e}", exc_info=True)
        finally:
            self._running = False
    
    async def stop(self):
        """Stop the webhook server"""
        if self._server and self._running:
            logger.info("Stopping webhook server")
            self._server.should_exit = True
            self._running = False
    
    @property
    def is_running(self) -> bool:
        """Check if server is running"""
        return self._running
