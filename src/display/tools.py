"""Tool call registry for display functions"""

from typing import Dict, Any, Callable, List, Optional
import inspect
from .manager import DisplayManager
from .states import DisplayState


class DisplayToolRegistry:
    """Registry for display tool calls that can be exposed to Gemini"""
    
    def __init__(self, display_manager: DisplayManager):
        """Initialize registry with display manager"""
        self.display_manager = display_manager
        self._tools: Dict[str, Callable] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default display tools"""
        self.register("display_show_text", self._show_text)
        self.register("display_set_state", self._set_state)
        self.register("display_anki_card", self._display_anki_card)
        self.register("display_show_info", self._show_info)
    
    def register(self, name: str, func: Callable):
        """Register a tool function"""
        self._tools[name] = func
    
    def get_function_declarations(self) -> List[Dict[str, Any]]:
        """Generate Gemini function declarations for registered tools"""
        declarations = []
        
        for name, func in self._tools.items():
            sig = inspect.signature(func)
            params = {}
            
            for param_name, param in sig.parameters.items():
                if param_name == 'self':
                    continue
                
                param_info = {
                    "type": self._python_type_to_gemini_type(param.annotation)
                }
                
                if param.default != inspect.Parameter.empty:
                    param_info["default"] = param.default
                
                params[param_name] = param_info
            
            declarations.append({
                "name": name,
                "description": func.__doc__ or f"Display tool: {name}",
                "parameters": {
                    "type": "object",
                    "properties": params
                }
            })
        
        return declarations
    
    def _python_type_to_gemini_type(self, annotation) -> str:
        """Convert Python type annotation to Gemini type string"""
        # Handle Optional types
        if hasattr(annotation, '__origin__') and annotation.__origin__ is type(None).__class__:
            # It's Optional, get the actual type
            args = getattr(annotation, '__args__', ())
            if args:
                annotation = args[0]
        
        # Handle List types
        if hasattr(annotation, '__origin__') and annotation.__origin__ is list:
            return "array"
        
        if annotation == str or annotation == inspect.Signature.empty:
            return "string"
        elif annotation == int:
            return "integer"
        elif annotation == float:
            return "number"
        elif annotation == bool:
            return "boolean"
        else:
            return "string"  # Default
    
    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call by name with arguments"""
        if name not in self._tools:
            return {"error": f"Unknown tool: {name}"}
        
        try:
            func = self._tools[name]
            result = func(**args)
            return {"success": True, "result": result}
        except Exception as e:
            return {"error": str(e)}
    
    # Tool implementations
    
    def _show_text(self, text: str) -> str:
        """Show text on the display. Args: text (string) - the text to display."""
        try:
            if not self.display_manager.is_initialized:
                self.display_manager.initialize()
            self.display_manager.show_text(text)
            return f"Displayed text: {text}"
        except Exception as e:
            error_msg = f"Error displaying text: {str(e)}"
            print(f"⚠️ {error_msg}")
            return error_msg
    
    def _set_state(self, state: str) -> str:
        """Set the display state. Args: state (string) - one of: 'sleep', 'idle', 'active'."""
        state_lower = state.lower()
        if state_lower == "sleep":
            display_state = DisplayState.SLEEP
        elif state_lower == "idle":
            display_state = DisplayState.IDLE
        elif state_lower == "active":
            display_state = DisplayState.ACTIVE
        else:
            return f"Invalid state: {state}. Valid states: sleep, idle, active"
        
        try:
            if not self.display_manager.is_initialized:
                self.display_manager.initialize()
            self.display_manager.set_state(display_state)
            return f"Display state set to: {state_lower}"
        except Exception as e:
            return f"Error setting display state: {str(e)}"
    
    def _display_anki_card(self, front: str, back: str = None, show_back: bool = False) -> str:
        """Display an Anki card on the display. Args: front (string) - card front text, back (string, optional) - card back text, show_back (boolean, optional) - whether to show back side."""
        try:
            if not self.display_manager.is_initialized:
                self.display_manager.initialize()
            if show_back and back:
                text = f"{front}\n---\n{back}"
            else:
                text = front
            self.display_manager.show_text(text, size=18)
            return f"Displayed card: {front[:30]}..." if len(front) > 30 else f"Displayed card: {front}"
        except Exception as e:
            error_msg = f"Error displaying card: {str(e)}"
            print(f"⚠️ {error_msg}")
            return error_msg
    
    def _show_info(self, title: Optional[str] = None, content: Optional[str] = None, lines: Optional[List[str]] = None) -> str:
        """Display structured information on the display. Use this when the user asks to show something specific. Args: title (string, optional) - title/header text, content (string, optional) - main content text, lines (list, optional) - list of strings to display as separate lines."""
        try:
            if not self.display_manager.is_initialized:
                self.display_manager.initialize()
            
            # Build text from structured input
            text_parts = []
            if title:
                text_parts.append(title)
                text_parts.append("---")
            if lines:
                text_parts.extend(lines)
            elif content:
                text_parts.append(content)
            
            if not text_parts:
                return "Error: No content provided to display"
            
            text = "\n".join(text_parts)
            self.display_manager.show_text(text, size=18)
            return f"Displayed info: {title or 'Information'}"
        except Exception as e:
            error_msg = f"Error displaying info: {str(e)}"
            print(f"⚠️ {error_msg}")
            return error_msg

