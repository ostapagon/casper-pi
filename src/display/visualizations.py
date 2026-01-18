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
    """Render sleep state - simple text"""
    return render_text("sleep", size=24)

def render_awake_state(tick: int = 0) -> Image.Image:
    """Render awake state - simple text"""
    return render_text("active", size=24)

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
