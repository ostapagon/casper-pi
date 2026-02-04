"""DisplayManager for managing SSD1351 OLED display"""

import io
import threading
import time
import traceback
from typing import Optional

import board
import displayio
from adafruit_ssd1351 import SSD1351
from fourwire import FourWire
from PIL import Image

try:
    import lgpio
except ImportError:
    lgpio = None

from ..config import get_flip_display
from .states import DisplayState
from .visualizations import render_sleep_state, render_awake_state, render_text


class DisplayManager:
    """Manages display state and rendering"""
    
    CS_PIN = board.D18
    DC_PIN = board.D19
    RST_PIN = board.D20
    WIDTH = 128
    HEIGHT = 96
    
    def __init__(self):
        """Initialize display manager
        
        Display flip setting is read from FLIP_DISPLAY environment variable.
        """
        self._lock = threading.Lock()
        self._state: Optional[DisplayState] = None
        self._display: Optional[SSD1351] = None
        self._initialized = False
        self._flip_display = get_flip_display()
        self._animation_thread: Optional[threading.Thread] = None
        self._animation_running = False
        self._tick = 0
    
    def initialize(self):
        """Initialize the display hardware"""
        if self._initialized:
            return
        
        with self._lock:
            try:
                # Free GPIO pins if needed
                if lgpio:
                    try:
                        chip = lgpio.gpiochip_open(0)
                        for pin in [18, 19, 20]:
                            try:
                                lgpio.gpio_free(chip, pin)
                            except:
                                pass
                        lgpio.gpiochip_close(chip)
                        time.sleep(0.1)
                    except:
                        pass
                
                # Initialize display
                spi = board.SPI()
                self._display = SSD1351(
                    FourWire(spi, command=self.DC_PIN, chip_select=self.CS_PIN, reset=self.RST_PIN),
                    width=self.WIDTH,
                    height=self.HEIGHT
                )
                self._initialized = True
                print("✓ Display initialized")
            except Exception as e:
                print(f"⚠️ Display error: {e}")
                raise
    
    def cleanup(self):
        """Cleanup display resources - fast with proper thread join"""
        # Stop animation and wait for thread to exit
        self._stop_animation()
        
        # Now safe to cleanup display
        with self._lock:
            if self._display:
                try:
                    self._display.root_group = None
                except:
                    pass
            self._display = None
            self._initialized = False
        
        # Free GPIO pins
        if lgpio:
            try:
                chip = lgpio.gpiochip_open(0)
                for pin in [18, 19, 20]:
                    try:
                        lgpio.gpio_free(chip, pin)
                    except:
                        pass
                lgpio.gpiochip_close(chip)
            except:
                pass
    
    def set_state(self, state: DisplayState):
        """Set display state and render appropriate visualization"""
        if not self._initialized:
            self.initialize()
        
        old_state = self._state
        self._state = state
        
        # Stop previous animation if running
        if old_state != state:
            self._stop_animation()
        
        # Start animation for sleep and idle states ONLY
        # Don't animate ACTIVE state to reduce CPU and avoid conflicts
        if state == DisplayState.SLEEP:
            self._start_animation()
        elif state == DisplayState.IDLE:
            self._start_animation()
        elif state == DisplayState.ACTIVE:
            # Render active state once (no animation) - safer for cleanup
            with self._lock:
                img = render_awake_state()
                if self._flip_display:
                    img = img.transpose(Image.ROTATE_180)
                self._show_image(img)
        else:
            # Static visualization for other states
            with self._lock:
                img = render_text(state.name.lower(), size=16)
                if self._flip_display:
                    img = img.transpose(Image.ROTATE_180)
                self._show_image(img)
    
    def show_text(self, text: str, size: int = 20):
        """Show text on display"""
        if not self._initialized:
            self.initialize()
        
        # Stop animation to prevent conflicts
        self._stop_animation()
        
        with self._lock:
            img = render_text(text, size)
            if self._flip_display:
                img = img.transpose(Image.ROTATE_180)
            self._show_image(img)
    
    def show_image(self, image: Image.Image):
        """Show PIL Image on display"""
        if not self._initialized:
            self.initialize()
        
        # Stop animation to prevent conflicts
        self._stop_animation()
        
        with self._lock:
            if self._flip_display:
                image = image.transpose(Image.ROTATE_180)
            self._show_image(image)
    
    def _show_image(self, image):
        """Internal method to display PIL Image - with safety checks"""
        # Safety check - don't try to show if display is None
        if not self._display or not self._initialized:
            return  # Silent fail if display not initialized
        
        try:
            # Ensure image is RGB mode
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            img_bytes = io.BytesIO()
            image.save(img_bytes, format='BMP')
            img_bytes.seek(0)
            
            # Create new group each time to force update
            bitmap = displayio.OnDiskBitmap(img_bytes)
            tile_grid = displayio.TileGrid(bitmap, pixel_shader=bitmap.pixel_shader)
            group = displayio.Group()
            group.append(tile_grid)
            
            # Force display refresh (no sleep needed)
            self._display.root_group = None
            self._display.root_group = group
        except Exception:
            # Silent fail to avoid spam
            pass
    
    @property
    def state(self) -> Optional[DisplayState]:
        """Get current display state"""
        return self._state
    
    @property
    def is_initialized(self) -> bool:
        """Check if display is initialized"""
        return self._initialized
    
    def _start_animation(self):
        """Start animation thread for current state"""
        if self._animation_running:
            return
        
        self._animation_running = True
        self._tick = 0
        self._animation_thread = threading.Thread(target=self._animation_loop, daemon=True)
        self._animation_thread.start()
    
    def _stop_animation(self):
        """Stop animation thread - fast but ensure it stops"""
        if not self._animation_running:
            return
        
        self._animation_running = False
        
        # Give thread a moment to exit (non-blocking check)
        if self._animation_thread and self._animation_thread.is_alive():
            # Try to join with very short timeout - just enough for one loop iteration
            self._animation_thread.join(timeout=0.1)  # 100ms max - one animation cycle
        
        self._animation_thread = None
    
    def _animation_loop(self):
        """Animation loop that runs in separate thread"""
        try:
            while self._animation_running:
                state = self._state
                if state == DisplayState.SLEEP:
                    img = render_sleep_state(self._tick)
                elif state == DisplayState.IDLE:
                    img = render_awake_state(self._tick)
                else:
                    # State changed, exit loop
                    break
                
                # Check if we should stop BEFORE trying to display
                if not self._animation_running:
                    return
                
                with self._lock:
                    # Double-check display still exists
                    if not self._display or not self._animation_running:
                        return
                    
                    if self._flip_display:
                        img = img.transpose(Image.ROTATE_180)
                    self._show_image(img)
                
                self._tick += 1
                
                # Sleep in small chunks so we can exit quickly
                for _ in range(4):
                    if not self._animation_running:
                        return
                    time.sleep(0.05)  # 4 x 0.05 = 0.2s total, but responsive
        except Exception:
            pass  # Silent fail on cleanup