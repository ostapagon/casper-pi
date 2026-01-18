"""Unified MCP server registry for Gemini Live API integration"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx

from ..config import get_mcp_servers_config

logger = logging.getLogger(__name__)


class MCPHTTPClient:
    """MCP client for HTTP transport"""
    
    def __init__(self, url: str, headers: Dict[str, str] = None):
        self.url = url.rstrip('/')
        self.headers = headers or {}
        self._request_id = 0
        self._initialized = False
        self._client = None
        self._session_id = None
        self._session_id = None
    
    async def initialize(self):
        """Initialize MCP HTTP connection"""
        try:
            self._client = httpx.AsyncClient(timeout=30.0)
            
            # Send initialize request
            init_request = {
                "jsonrpc": "2.0",
                "id": self._get_request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "casper-pi",
                        "version": "0.1.0"
                    }
                }
            }
            
            response = await self._send_request(init_request)
            if response and "result" in response:
                # Session ID is already stored in _session_id by _send_request
                # Send initialized notification (may not be required for HTTP)
                try:
                    await self._send_notification({
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized"
                    })
                except Exception as e:
                    logger.debug(f"Initialized notification failed (may be expected): {e}")
                self._initialized = True
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to initialize MCP HTTP client: {e}")
            return False
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server"""
        if not self._initialized:
            await self.initialize()
        
        request = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": "tools/list"
        }
        
        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"].get("tools", [])
        return []
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server"""
        if not self._initialized:
            await self.initialize()
        
        request = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            }
        }
        
        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"]
        elif response and "error" in response:
            raise Exception(f"MCP tool error: {response['error']}")
        return None
    
    async def _send_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send JSON-RPC request via HTTP (handles SSE responses)"""
        if not self._client:
            return None
        
        try:
            # Merge custom headers with default Content-Type and Accept
            # AnkiMCP requires accepting both application/json and text/event-stream
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            # Add session ID if we have one
            if self._session_id:
                headers["mcp-session-id"] = self._session_id
            headers.update(self.headers)
            
            response = await self._client.post(
                self.url,
                json=request,
                headers=headers
            )
            response.raise_for_status()
            
            # Extract session ID from response header (for first request)
            if not self._session_id:
                self._session_id = response.headers.get("mcp-session-id")
            
            # Check if response is SSE format (text/event-stream)
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type or "event:" in response.text[:100]:
                # Parse SSE format: "event: message\ndata: {...}\n\n"
                text = response.text
                # Extract JSON from "data:" lines
                for line in text.split('\n'):
                    if line.startswith('data: '):
                        json_str = line[6:]  # Remove "data: " prefix
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            continue
                # If no data line found, try parsing whole response as JSON
                try:
                    return response.json()
                except:
                    logger.error(f"Failed to parse SSE response: {text[:200]}")
                    return None
            else:
                # Regular JSON response
                return response.json()
        except Exception as e:
            logger.error(f"Error sending MCP HTTP request: {e}")
            return None
    
    async def _send_notification(self, notification: Dict[str, Any]):
        """Send JSON-RPC notification (no response expected)"""
        if not self._client:
            return
        
        try:
            # Merge custom headers with default Content-Type and Accept
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            # Add session ID if we have one
            if self._session_id:
                headers["mcp-session-id"] = self._session_id
            headers.update(self.headers)
            
            await self._client.post(
                self.url,
                json=notification,
                headers=headers
            )
        except Exception as e:
            logger.debug(f"Error sending MCP HTTP notification: {e}")
    
    def _get_request_id(self) -> int:
        """Get next request ID"""
        self._request_id += 1
        return self._request_id
    
    async def cleanup(self):
        """Cleanup MCP HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None


class MCPClient:
    """Basic MCP client for stdio transport"""
    
    def __init__(self, command: List[str], env: Dict[str, str] = None):
        self.command = command
        self.env = env or {}
        self.process = None
        self._request_id = 0
        self._pending_requests = {}
        self._initialized = False
    
    async def initialize(self):
        """Initialize MCP connection"""
        try:
            # Start subprocess
            env = os.environ.copy()
            env.update(self.env)
            
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            # Start reader task
            asyncio.create_task(self._read_responses())
            
            # Send initialize request
            init_request = {
                "jsonrpc": "2.0",
                "id": self._get_request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "casper-pi",
                        "version": "0.1.0"
                    }
                }
            }
            
            await self._send_request(init_request)
            
            # Wait for initialized notification
            await asyncio.sleep(0.1)  # Give it time to respond
            
            # Send initialized notification
            initialized_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            }
            await self._send_notification(initialized_notification)
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")
            return False
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from MCP server"""
        if not self._initialized:
            await self.initialize()
        
        request = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": "tools/list"
        }
        
        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"].get("tools", [])
        return []
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server"""
        if not self._initialized:
            await self.initialize()
        
        request = {
            "jsonrpc": "2.0",
            "id": self._get_request_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {}
            }
        }
        
        response = await self._send_request(request)
        if response and "result" in response:
            return response["result"]
        elif response and "error" in response:
            raise Exception(f"MCP tool error: {response['error']}")
        return None
    
    async def _send_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send JSON-RPC request and wait for response"""
        if not self.process or not self.process.stdin:
            return None
        
        request_id = request.get("id")
        future = asyncio.Future()
        self._pending_requests[request_id] = future
        
        try:
            message = json.dumps(request) + "\n"
            self.process.stdin.write(message.encode())
            await self.process.stdin.drain()
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=10.0)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for MCP response: {request_id}")
            self._pending_requests.pop(request_id, None)
            return None
        except Exception as e:
            logger.error(f"Error sending MCP request: {e}")
            self._pending_requests.pop(request_id, None)
            return None
    
    async def _send_notification(self, notification: Dict[str, Any]):
        """Send JSON-RPC notification (no response expected)"""
        if not self.process or not self.process.stdin:
            return
        
        try:
            message = json.dumps(notification) + "\n"
            self.process.stdin.write(message.encode())
            await self.process.stdin.drain()
        except Exception as e:
            logger.error(f"Error sending MCP notification: {e}")
    
    async def _read_responses(self):
        """Read responses from MCP server stdout"""
        if not self.process or not self.process.stdout:
            return
        
        buffer = ""
        try:
            while True:
                chunk = await self.process.stdout.read(1024)
                if not chunk:
                    break
                
                buffer += chunk.decode('utf-8', errors='ignore')
                
                # Process complete JSON messages
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            response = json.loads(line)
                            request_id = response.get("id")
                            if request_id in self._pending_requests:
                                future = self._pending_requests.pop(request_id)
                                future.set_result(response)
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse MCP response: {line}")
        except Exception as e:
            logger.error(f"Error reading MCP responses: {e}")
    
    def _get_request_id(self) -> int:
        """Get next request ID"""
        self._request_id += 1
        return self._request_id
    
    async def cleanup(self):
        """Cleanup MCP client"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except Exception as e:
                logger.warning(f"Error cleaning up MCP client: {e}")
                if self.process:
                    self.process.kill()


class MCPRegistry:
    """Unified registry for all MCP servers"""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize MCP registry
        
        Args:
            config_path: Path to mcp_servers.json config file. If None, looks for
                        mcp_servers.json in project root or uses MCP_SERVERS env var.
        """
        self.config_path = config_path
        self.servers: Dict[str, Dict[str, Any]] = {}
        self.clients: Dict[str, MCPClient] = {}
        self.tools: Dict[str, Dict[str, Any]] = {}  # tool_name -> {server, tool_def}
        self._initialized = False
    
    def _load_config(self) -> Dict[str, Any]:
        """Load MCP server configuration"""
        # Try config file first
        if self.config_path:
            config_file = Path(self.config_path)
        else:
            # Look in project root
            project_root = Path(__file__).parent.parent.parent
            config_file = project_root / "src" / "mcp" / "mcp_servers.json"
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    return config.get("mcp_servers", [])
            except Exception as e:
                logger.error(f"Failed to load MCP config from {config_file}: {e}")
        
        # Try environment variable
        env_config = get_mcp_servers_config()
        if env_config:
            try:
                config = json.loads(env_config)
                if isinstance(config, list):
                    return config
                elif isinstance(config, dict) and "mcp_servers" in config:
                    return config["mcp_servers"]
            except Exception as e:
                logger.error(f"Failed to parse MCP_SERVERS env var: {e}")
        
        return []
    
    async def initialize(self):
        """Initialize all enabled MCP servers and discover tools"""
        if self._initialized:
            return
        
        config = self._load_config()
        
        for server_config in config:
            if not server_config.get("enabled", True):
                continue
            
            server_name = server_config.get("name", "unknown")
            transport = server_config.get("transport", "stdio")
            
            try:
                if transport == "http" or transport == "https":
                    # HTTP transport
                    url = server_config.get("url")
                    if not url:
                        logger.warning(f"Server {server_name}: No URL specified for HTTP transport")
                        continue
                    
                    # Get authentication headers if provided
                    headers = {}
                    if "auth" in server_config:
                        auth = server_config["auth"]
                        if auth.get("type") == "bearer":
                            headers["Authorization"] = f"Bearer {auth.get('token')}"
                        elif auth.get("type") == "api_key":
                            headers[auth.get("header", "X-API-Key")] = auth.get("key")
                    
                    client = MCPHTTPClient(url, headers=headers)
                    if await client.initialize():
                        self.clients[server_name] = client
                        self.servers[server_name] = server_config
                        
                        # Discover tools
                        tools = await client.list_tools()
                        for tool in tools:
                            tool_name = tool.get("name")
                            if tool_name:
                                self.tools[tool_name] = {
                                    "server": server_name,
                                    "tool": tool
                                }
                                logger.info(f"Registered tool: {tool_name} from server {server_name}")
                    else:
                        logger.warning(f"Failed to initialize MCP HTTP server: {server_name}")
                
                elif transport == "stdio":
                    # STDIO transport
                    command = server_config.get("command")
                    if not command:
                        logger.warning(f"Server {server_name}: No command specified")
                        continue
                    
                    args = server_config.get("args", [])
                    env = server_config.get("env", {})
                    
                    # Build command list
                    cmd_list = [command] + (args if isinstance(args, list) else [])
                    
                    # Create and initialize client
                    client = MCPClient(cmd_list, env)
                    if await client.initialize():
                        self.clients[server_name] = client
                        self.servers[server_name] = server_config
                        
                        # Discover tools
                        tools = await client.list_tools()
                        for tool in tools:
                            tool_name = tool.get("name")
                            if tool_name:
                                self.tools[tool_name] = {
                                    "server": server_name,
                                    "tool": tool
                                }
                                logger.info(f"Registered tool: {tool_name} from server {server_name}")
                    else:
                        logger.warning(f"Failed to initialize MCP server: {server_name}")
                else:
                    logger.warning(f"Server {server_name}: Unsupported transport: {transport}")
                    continue
                    
            except Exception as e:
                logger.error(f"Error initializing MCP server {server_name}: {e}")
                # Continue with other servers
        
        self._initialized = True
        logger.info(f"MCP Registry initialized with {len(self.clients)} servers and {len(self.tools)} tools")
    
    def get_function_declarations(self) -> List[Dict[str, Any]]:
        """Get Gemini function declarations for all registered tools"""
        declarations = []
        
        for tool_name, tool_info in self.tools.items():
            tool_def = tool_info["tool"]
            server_name = tool_info["server"]
            
            # Convert MCP tool schema to Gemini function declaration
            gemini_decl = self._mcp_to_gemini_schema(tool_name, tool_def, server_name)
            if gemini_decl:
                declarations.append(gemini_decl)
        
        return declarations
    
    def _mcp_to_gemini_schema(self, tool_name: str, tool_def: Dict[str, Any], server_name: str) -> Optional[Dict[str, Any]]:
        """Convert MCP tool schema to Gemini function declaration format"""
        try:
            input_schema = tool_def.get("inputSchema", {})
            
            # Extract properties from JSON schema
            properties = input_schema.get("properties", {})
            required = input_schema.get("required", [])
            
            # Convert to Gemini format
            gemini_properties = {}
            for prop_name, prop_schema in properties.items():
                gemini_prop = self._convert_property_schema(prop_schema)
                if gemini_prop:
                    gemini_properties[prop_name] = gemini_prop
            
            # Ensure properties is always a dict (even if empty)
            if not gemini_properties:
                gemini_properties = {}
            
            declaration = {
                "name": tool_name,
                "description": tool_def.get("description", f"Tool from {server_name} MCP server"),
                "parameters": {
                    "type": "object",
                    "properties": gemini_properties
                }
            }
            
            if required:
                declaration["parameters"]["required"] = required
            
            return declaration
            
        except Exception as e:
            logger.error(f"Error converting MCP tool {tool_name} to Gemini schema: {e}")
            return None
    
    def _convert_property_schema(self, prop_schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert a single property schema from JSON Schema to Gemini format"""
        prop_type = prop_schema.get("type", "string")
        gemini_type = self._json_schema_type_to_gemini(prop_type)
        
        gemini_prop = {"type": gemini_type}
        
        if "description" in prop_schema:
            gemini_prop["description"] = prop_schema["description"]
        
        # Handle array types - Gemini requires items field for arrays
        if prop_type == "array":
            items_schema = prop_schema.get("items")
            if items_schema:
                # Recursively convert the items schema
                items_type = items_schema.get("type", "string")
                gemini_items_type = self._json_schema_type_to_gemini(items_type)
                gemini_prop["items"] = {"type": gemini_items_type}
                
                # If items is an object, convert its properties recursively
                if items_type == "object":
                    items_properties = items_schema.get("properties", {})
                    if items_properties:
                        gemini_items_properties = {}
                        for item_prop_name, item_prop_schema in items_properties.items():
                            converted_item_prop = self._convert_property_schema(item_prop_schema)
                            if converted_item_prop:
                                gemini_items_properties[item_prop_name] = converted_item_prop
                        gemini_prop["items"]["properties"] = gemini_items_properties
                        gemini_prop["items"]["type"] = "object"
            else:
                # If no items specified, default to string array
                gemini_prop["items"] = {"type": "string"}
        
        # Handle object types - recursively convert nested properties
        elif prop_type == "object":
            object_properties = prop_schema.get("properties", {})
            if object_properties:
                gemini_object_properties = {}
                for obj_prop_name, obj_prop_schema in object_properties.items():
                    converted_obj_prop = self._convert_property_schema(obj_prop_schema)
                    if converted_obj_prop:
                        gemini_object_properties[obj_prop_name] = converted_obj_prop
                gemini_prop["properties"] = gemini_object_properties
        
        return gemini_prop
    
    def _json_schema_type_to_gemini(self, json_type: str) -> str:
        """Convert JSON Schema type to Gemini type"""
        type_mapping = {
            "string": "string",
            "integer": "integer",
            "number": "number",
            "boolean": "boolean",
            "array": "array",
            "object": "object"
        }
        return type_mapping.get(json_type, "string")
    
    
    async def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call by routing to the correct MCP server"""
        if tool_name not in self.tools:
            logger.warning(f"Unknown tool requested: {tool_name}")
            return {"error": f"Unknown tool: {tool_name}"}
        
        tool_info = self.tools[tool_name]
        server_name = tool_info["server"]
        
        if server_name not in self.clients:
            logger.error(f"MCP server {server_name} not available for tool {tool_name}")
            return {"error": f"MCP server {server_name} not available"}
        
        try:
            client = self.clients[server_name]
            
            # Execute with timeout
            try:
                result = await asyncio.wait_for(
                    client.call_tool(tool_name, args),
                    timeout=30.0  # 30 second timeout for tool execution
                )
            except asyncio.TimeoutError:
                logger.error(f"Tool {tool_name} execution timed out")
                return {"error": f"Tool execution timed out after 30 seconds"}
            
            # Format result for Gemini
            return self._format_tool_result(tool_name, result)
                
        except Exception as e:
            logger.error(f"Error executing tool {tool_name} on server {server_name}: {e}", exc_info=True)
            return {"error": f"Tool execution failed: {str(e)}"}
    
    def _format_tool_result(self, tool_name: str, result: Any) -> Dict[str, Any]:
        """Format MCP tool result for Gemini"""
        if isinstance(result, dict):
            if "content" in result:
                # MCP tool result format: extract text from content
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    first_content = content[0]
                    if isinstance(first_content, dict) and "text" in first_content:
                        try:
                            # Try to parse JSON text result
                            text_result = first_content["text"]
                            parsed = json.loads(text_result)
                            return {"success": True, "result": parsed}
                        except (json.JSONDecodeError, TypeError):
                            return {"success": True, "result": text_result}
                return {"success": True, "result": str(content)}
            elif "error" in result:
                error_msg = result.get("error", {}).get("message", str(result["error"]))
                logger.error(f"MCP tool {tool_name} returned error: {error_msg}")
                return {"error": error_msg}
            else:
                return {"success": True, "result": result}
        else:
            return {"success": True, "result": str(result)}
    
    async def cleanup(self):
        """Cleanup all MCP server connections"""
        for server_name, client in self.clients.items():
            try:
                await client.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up {server_name}: {e}")
        
        self.clients.clear()
        self.tools.clear()
        self._initialized = False

