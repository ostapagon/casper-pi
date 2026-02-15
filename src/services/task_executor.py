#!/usr/bin/env python3
"""Task executor service - executes tasks using MCP tools"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes tasks using MCP registry and other services"""
    
    def __init__(self, mcp_registry=None, display_manager=None):
        """Initialize task executor
        
        Args:
            mcp_registry: MCP registry instance for tool execution
            display_manager: Display manager instance for visual feedback
        """
        self.mcp_registry = mcp_registry
        self.display_manager = display_manager
        self._task_history = []
        self._max_history = 100
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            Dict with result or error
        """
        start_time = datetime.now()
        
        try:
            logger.info(f"Executing tool: {tool_name}")
            logger.debug(f"Arguments: {arguments}")
            
            # Check if tool exists
            if self.mcp_registry and tool_name in self.mcp_registry.tools:
                # Execute MCP tool
                result = await self.mcp_registry.execute(tool_name, arguments)
                
                # Record in history
                execution_time = (datetime.now() - start_time).total_seconds()
                self._add_to_history({
                    "type": "tool",
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "timestamp": start_time.isoformat(),
                    "execution_time": execution_time
                })
                
                return {
                    "success": True,
                    "tool": tool_name,
                    "result": result,
                    "execution_time": execution_time
                }
            else:
                error_msg = f"Tool '{tool_name}' not found"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg,
                    "available_tools": list(self.mcp_registry.tools.keys()) if self.mcp_registry else []
                }
                
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "tool": tool_name
            }
    
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a generic task
        
        Args:
            task: Task definition with 'type' and other parameters
            
        Returns:
            Dict with result or error
        """
        task_type = task.get("type")
        
        if task_type == "tool_call":
            # Execute MCP tool
            tool_name = task.get("tool_name")
            arguments = task.get("arguments", {})
            return await self.execute_tool(tool_name, arguments)
        
        elif task_type == "display":
            # Display operation
            if not self.display_manager:
                return {"success": False, "error": "Display manager not available"}
            
            action = task.get("action")
            if action == "show_text":
                text = task.get("text", "")
                title = task.get("title", "Message")
                try:
                    from ..display.states import DisplayState
                    if not self.display_manager.is_initialized:
                        self.display_manager.initialize()
                    self.display_manager.show_info(title=title, lines=[text])
                    return {"success": True, "message": "Text displayed"}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            
            elif action == "set_state":
                state = task.get("state", "active")
                try:
                    from ..display.states import DisplayState
                    if not self.display_manager.is_initialized:
                        self.display_manager.initialize()
                    state_enum = getattr(DisplayState, state.upper())
                    self.display_manager.set_state(state_enum)
                    return {"success": True, "message": f"Display state set to {state}"}
                except Exception as e:
                    return {"success": False, "error": str(e)}
        
        elif task_type == "custom":
            # Custom task execution (extensible)
            handler = task.get("handler")
            params = task.get("params", {})
            return {
                "success": False,
                "error": "Custom task handlers not yet implemented",
                "task": task
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown task type: {task_type}",
                "supported_types": ["tool_call", "display", "custom"]
            }
    
    def _add_to_history(self, entry: Dict[str, Any]):
        """Add entry to task history"""
        self._task_history.append(entry)
        if len(self._task_history) > self._max_history:
            self._task_history.pop(0)
    
    def get_history(self, limit: Optional[int] = None) -> list:
        """Get task execution history
        
        Args:
            limit: Maximum number of entries to return (None = all)
            
        Returns:
            List of history entries
        """
        if limit:
            return self._task_history[-limit:]
        return self._task_history.copy()
    
    def clear_history(self):
        """Clear task execution history"""
        self._task_history.clear()
    
    def get_available_tools(self) -> Dict[str, Any]:
        """Get available tools mapped to their definitions
        
        Returns:
            Dict mapping tool names to their MCP tool definitions
        """
        if not self.mcp_registry:
            return {}
        
        # Return tools in format expected by agent: {tool_name: tool_definition}
        tools_map = {}
        for tool_name, tool_info in self.mcp_registry.tools.items():
            tool_def = tool_info["tool"]
            # Only include tools with valid schema
            if isinstance(tool_def, dict) and "inputSchema" in tool_def:
                tools_map[tool_name] = tool_def
            else:
                print(f"⚠️ Skipping invalid tool: {tool_name} (missing inputSchema)")
        
        return tools_map
