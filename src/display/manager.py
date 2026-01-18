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
        """Cleanup display resources"""
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
                time.sleep(0.1)
            except:
                pass
    
    def set_state(self, state: DisplayState):
        """Set display state and render appropriate visualization"""
        if not self._initialized:
            self.initialize()
        
        with self._lock:
            old_state = self._state
            self._state = state
            
            # Render sleep and awake states (simple text, no animation needed)
            if state == DisplayState.SLEEP or state == DisplayState.ACTIVE:
                if state == DisplayState.SLEEP:
                    img = render_sleep_state()
                elif state == DisplayState.ACTIVE:
                    img = render_awake_state()
                if self._flip_display:
                    img = img.transpose(Image.ROTATE_180)
                self._show_image(img)
            else:
                # Static visualization for other states
                img = render_text(state.name.lower(), size=16)
                if self._flip_display:
                    img = img.transpose(Image.ROTATE_180)
                self._show_image(img)
    
    def show_text(self, text: str, size: int = 20):
        """Show text on display"""
        if not self._initialized:
            self.initialize()
        
        with self._lock:
            img = render_text(text, size)
            if self._flip_display:
                img = img.transpose(Image.ROTATE_180)
            self._show_image(img)
    
    def show_image(self, image: Image.Image):
        """Show PIL Image on display"""
        if not self._initialized:
            self.initialize()
        
        with self._lock:
            if self._flip_display:
                image = image.transpose(Image.ROTATE_180)
            self._show_image(image)
    
    def _show_image(self, image):
        """Internal method to display PIL Image"""
        if not self._display:
            print("⚠️ Display not initialized, cannot show image")
            return
        
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
            
            # Force display refresh
            self._display.root_group = None
            time.sleep(0.01)  # Small delay
            self._display.root_group = group
        except Exception as e:
            print(f"⚠️ Display error: {e}")
            traceback.print_exc()
    
    @property
    def state(self) -> Optional[DisplayState]:
        """Get current display state"""
        return self._state
    
    @property
    def is_initialized(self) -> bool:
        """Check if display is initialized"""
        return self._initialized
