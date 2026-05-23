import os
from PIL import ImageFont

def get_text_width(text, font):
    """
    Measures the width of text in pixels using the given Pillow font.
    """
    if not text:
        return 0
    try:
        # Use font.getbbox (standard in modern Pillow versions)
        bbox = font.getbbox(text)
        if bbox:
            return bbox[2] - bbox[0]
    except Exception:
        # Fallback to older font.getsize if getbbox fails or is not available
        try:
            return font.getsize(text)[0]
        except Exception:
            pass
    # Worst case approximation (average characters width based on font size)
    return len(text) * (font.size if hasattr(font, 'size') else 10) * 0.6

def load_font(font_path, font_size):
    """
    Loads font from file path. Fallbacks to standard Windows fonts if not found
    to ensure Unicode (Vietnamese) support.
    """
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception:
            pass
            
    # Windows default fonts supporting Vietnamese
    fallbacks = [
        "arial.ttf",
        "segoeui.ttf",
        "calibri.ttf",
        "tahoma.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf"
    ]
    
    for font_name in fallbacks:
        try:
            return ImageFont.truetype(font_name, font_size)
        except Exception:
            continue
            
    # Fallback to PIL default font if no system fonts found
    return ImageFont.load_default()

def wrap_text(text: str, max_width: float, font) -> list[str]:
    """
    Wraps text into multiple lines so that each line does not exceed max_width.
    Supports manual newlines (\n).
    """
    if not text:
        return []
    if max_width <= 0:
        return [text]
        
    paragraphs = text.split("\n")
    all_lines = []
    
    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            all_lines.append("")
            continue
            
        words = para_clean.split()
        current_line = []
        
        for word in words:
            if not current_line:
                current_line.append(word)
            else:
                candidate = " ".join(current_line + [word])
                w = get_text_width(candidate, font)
                if w <= max_width:
                    current_line.append(word)
                else:
                    all_lines.append(" ".join(current_line))
                    current_line = [word]
                    
        if current_line:
            all_lines.append(" ".join(current_line))
            
    return all_lines

def fit_text_to_box(text: str, box_width: float, box_height: float, font_path: str = None, 
                    initial_font_size: int = 32, min_font_size: int = 20, 
                    line_height_ratio: float = 1.3) -> dict:
    """
    Wraps text and shrinks font size until it fits within box_width and box_height.
    Returns size, lines and lineHeight configuration, plus overflow status if it fails.
    """
    font_size = initial_font_size
    
    while font_size >= min_font_size:
        font = load_font(font_path, font_size)
        lines = wrap_text(text, box_width, font)
        
        line_height = int(font_size * line_height_ratio)
        total_height = len(lines) * line_height
        
        if total_height <= box_height:
            return {
                "fontSize": font_size,
                "lines": lines,
                "lineHeight": line_height
            }
            
        font_size -= 1
        
    # If it still overflows at min_font_size, return min_font_size with overflow=True
    min_font = load_font(font_path, min_font_size)
    min_lines = wrap_text(text, box_width, min_font)
    min_line_height = int(min_font_size * line_height_ratio)
    
    return {
        "fontSize": min_font_size,
        "lines": min_lines,
        "lineHeight": min_line_height,
        "overflow": True
    }
