"""Visualization functions for display states"""

import textwrap
from PIL import Image, ImageDraw, ImageFont

def _load_font(size=16):
    """Load font with fallbacks - tries Chinese/CJK fonts first (support both English and Chinese)"""
    # Try Chinese/CJK fonts first (support both English and Chinese characters)
    chinese_fonts = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # WenQuanYi Micro Hei (best for small displays)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Noto Sans CJK
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",  # Noto Sans CJK Bold
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Droid Sans Fallback
    ]
    
    for font_path in chinese_fonts:
        try:
            return ImageFont.truetype(font_path, size)
        except:
            continue
    
    # Fallback to Latin fonts (English only)
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", size)
        except:
            return ImageFont.load_default()

def render_sleep_state(tick: int = 0) -> Image.Image:
    """Render sleep state - ghost with animated zzz"""
    img = Image.new('RGB', (128, 96), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Ghost dimensions (scaled for 128x96 display)
    g_w = 45  # Ghost width
    g_h = 55  # Ghost height
    c_x = 64  # Center X
    c_y = 50  # Center Y
    
    left = c_x - g_w // 2
    top = c_y - g_h // 2
    right = c_x + g_w // 2
    bottom = c_y + g_h // 2
    
    # Draw Arms (side nubs)
    draw.pieslice([left - 10, c_y - 10, left + 10, c_y + 20], 90, 270, fill=(255, 255, 255))
    draw.pieslice([right - 10, c_y - 10, right + 10, c_y + 20], 270, 90, fill=(255, 255, 255))
    
    # Head (top circle)
    draw.ellipse([left, top, right, top + g_w], fill=(255, 255, 255))
    
    # Body (rectangle)
    draw.rectangle([left, top + g_w // 2, right, bottom], fill=(255, 255, 255))
    
    # Wavy tail (circles at bottom)
    wave_count = 4
    wave_width = g_w / wave_count
    for i in range(wave_count):
        wx = left + (i * wave_width)
        wy = bottom - (wave_width / 2)
        draw.ellipse([wx, wy, wx + wave_width, wy + wave_width], fill=(255, 255, 255))
    
    # Closed eyes (arcs)
    eye_offset = 10
    eye_y = c_y - 5
    eye_radius = 6  # Keep original size for closed eyes
    
    draw.arc([c_x - eye_offset - eye_radius, eye_y - eye_radius, 
              c_x - eye_offset + eye_radius, eye_y + eye_radius], 
             start=0, end=180, fill=(0, 0, 0), width=2)
    draw.arc([c_x + eye_offset - eye_radius, eye_y - eye_radius, 
              c_x + eye_offset + eye_radius, eye_y + eye_radius], 
             start=0, end=180, fill=(0, 0, 0), width=2)
    
    # Mouth (small O)
    draw.ellipse([c_x - 3, c_y + 8, c_x + 3, c_y + 14], fill=(0, 0, 0))
    
    # Draw Z function
    def draw_z(x, y, s):
        draw.line([x, y, x+s, y], fill=(255, 255, 255), width=2)
        draw.line([x+s, y, x, y+s], fill=(255, 255, 255), width=2)
        draw.line([x, y+s, x+s, y+s], fill=(255, 255, 255), width=2)
    
    # Animated Zzz with floating effect
    y_offset = int(3 * (tick % 20) / 20)
    draw_z(c_x + 20, c_y - 20 - y_offset, 5)
    draw_z(c_x + 28, c_y - 30 - y_offset, 7)
    draw_z(c_x + 38, c_y - 42 - y_offset, 9)
    
    return img

def render_awake_state(tick: int = 0) -> Image.Image:
    """Render idle/awake state - ghost with open eyes"""
    img = Image.new('RGB', (128, 96), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Ghost dimensions (same as sleep state)
    g_w = 45  # Ghost width
    g_h = 55  # Ghost height
    c_x = 64  # Center X
    c_y = 50  # Center Y
    
    left = c_x - g_w // 2
    top = c_y - g_h // 2
    right = c_x + g_w // 2
    bottom = c_y + g_h // 2
    
    # Draw Arms (side nubs)
    draw.pieslice([left - 10, c_y - 10, left + 10, c_y + 20], 90, 270, fill=(255, 255, 255))
    draw.pieslice([right - 10, c_y - 10, right + 10, c_y + 20], 270, 90, fill=(255, 255, 255))
    
    # Head (top circle)
    draw.ellipse([left, top, right, top + g_w], fill=(255, 255, 255))
    
    # Body (rectangle)
    draw.rectangle([left, top + g_w // 2, right, bottom], fill=(255, 255, 255))
    
    # Wavy tail (circles at bottom) - slightly animated
    wave_count = 4
    wave_width = g_w / wave_count
    wave_offset = int(1 * (tick % 20) / 20)
    for i in range(wave_count):
        wx = left + (i * wave_width)
        wy = bottom - (wave_width / 2)
        y_adjust = wave_offset if i % 2 == 0 else -wave_offset
        draw.ellipse([wx, wy + y_adjust, wx + wave_width, wy + wave_width + y_adjust], fill=(255, 255, 255))
    
    # Eyes (black ovals) - 25% smaller
    eye_w = 4  # 25% smaller (was 6)
    eye_h = 7  # 25% smaller (was 9)
    eye_offset = 10
    eye_y = c_y - 10
    
    # Left eye
    draw.ellipse([c_x - eye_offset - eye_w, eye_y - eye_h,
                  c_x - eye_offset + eye_w, eye_y + eye_h], fill=(0, 0, 0))
    # Right eye
    draw.ellipse([c_x + eye_offset - eye_w, eye_y - eye_h,
                  c_x + eye_offset + eye_w, eye_y + eye_h], fill=(0, 0, 0))
    
    # Eye highlights
    draw.ellipse([c_x - eye_offset - 1, eye_y - 4, c_x - eye_offset + 2, eye_y - 1], fill=(255, 255, 255))
    draw.ellipse([c_x + eye_offset - 1, eye_y - 4, c_x + eye_offset + 2, eye_y - 1], fill=(255, 255, 255))
    
    # Mouth (smile - chord)
    mouth_w = 10
    mouth_h = 8
    mouth_y = c_y + 5
    draw.chord([c_x - mouth_w, mouth_y, c_x + mouth_w, mouth_y + mouth_h], 
               start=0, end=180, fill=(0, 0, 0))
    
    # Cheeks (grey)
    draw.ellipse([c_x - 22, c_y, c_x - 15, c_y + 4], fill=(200, 200, 200))
    draw.ellipse([c_x + 15, c_y, c_x + 22, c_y + 4], fill=(200, 200, 200))
    
    return img

def render_text(text: str, size: int = 20) -> Image.Image:
    """Render text centered on display with automatic wrapping and font sizing"""
    img = Image.new('RGB', (128, 96), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Try different font sizes to fit text
    max_width = 120  # Leave some margin
    max_height = 90
    font_size = size
    line_height = int(size * 1.2)
    
    for font_size in range(size, 8, -2):  # Start from requested size, go down by 2
        font = _load_font(font_size)
        
        # Wrap text to fit width
        # For Chinese characters, use different width calculation
        # Chinese chars are roughly square, so use font_size directly
        # For mixed text, use a conservative estimate
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
        if has_chinese:
            # Chinese characters: roughly font_size pixels wide
            chars_per_line = int(max_width / font_size)
        else:
            # Latin characters: roughly 0.6 * font_size
            avg_char_width = font_size * 0.6
            chars_per_line = int(max_width / avg_char_width)
        
        wrapped_lines = []
        for line in text.split('\n'):
            if has_chinese:
                # For Chinese, wrap character by character
                current_line = ""
                for char in line:
                    # Check if adding this char would exceed width
                    test_line = current_line + char
                    try:
                        bbox = draw.textbbox((0, 0), test_line, font=font)
                        test_width = bbox[2] - bbox[0]
                    except AttributeError:
                        test_width, _ = draw.textsize(test_line, font=font)
                    
                    if test_width > max_width and current_line:
                        wrapped_lines.append(current_line)
                        current_line = char
                    else:
                        current_line = test_line
                if current_line:
                    wrapped_lines.append(current_line)
            else:
                wrapped_lines.extend(textwrap.wrap(line, width=chars_per_line, break_long_words=True, break_on_hyphens=False))
        
        # Calculate total height needed
        line_height = int(font_size * 1.2)
        total_height = len(wrapped_lines) * line_height
        
        # If it fits, use this size
        if total_height <= max_height:
            break
    else:
        # If no size fits, use smallest and truncate
        font_size = 8
        font = _load_font(font_size)
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
        if has_chinese:
            chars_per_line = int(max_width / font_size)
        else:
            chars_per_line = int(max_width / (8 * 0.6))
        wrapped_lines = []
        for line in text.split('\n'):
            if has_chinese:
                # For Chinese, wrap character by character
                current_line = ""
                for char in line:
                    test_line = current_line + char
                    try:
                        bbox = draw.textbbox((0, 0), test_line, font=font)
                        test_width = bbox[2] - bbox[0]
                    except AttributeError:
                        test_width, _ = draw.textsize(test_line, font=font)
                    if test_width > max_width and current_line:
                        wrapped_lines.append(current_line)
                        current_line = char
                    else:
                        current_line = test_line
                if current_line:
                    wrapped_lines.append(current_line)
            else:
                wrapped_lines.extend(textwrap.wrap(line, width=chars_per_line, break_long_words=True, break_on_hyphens=False))
        wrapped_lines = wrapped_lines[:6]  # Max 6 lines
        line_height = int(font_size * 1.2)
    
    # Draw wrapped text
    y = (96 - (len(wrapped_lines) * line_height)) // 2
    for line in wrapped_lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
        except AttributeError:
            w, _ = draw.textsize(line, font=font)
        x = (128 - w) // 2
        draw.text((x, y), line, fill=(255, 255, 255), font=font)
        y += line_height
    
    return img
