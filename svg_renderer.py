import os
import html
import json
from text_fit import fit_text_to_box, load_font, get_text_width

def escape_xml(text):
    """
    Escapes special XML/HTML characters to prevent parsing errors.
    """
    return html.escape(str(text), quote=True)

def get_alignment_props(align, x, width):
    """
    Converts alignment type to SVG text-anchor and x position.
    """
    align = (align or "left").lower()
    if align == "center":
        return "middle", x + width / 2
    elif align == "right":
        return "end", x + width
    else:
        return "start", x

def render_text_block(block: dict, warnings: list) -> str:
    """
    Renders title, paragraph, or text block using <text> and <tspan>.
    """
    x = block.get("x", 0)
    y = block.get("y", 0)
    width = block.get("width", 0)
    height = block.get("height", 0)
    font_size = block.get("fontSize", 16)
    font_weight = block.get("fontWeight", "normal")
    align = block.get("align", "left")
    
    block_type = str(block.get("type", "paragraph")).lower()
    
    # Quy định min_font_size theo loại block
    if block_type == "title":
        min_font_size = 28
    elif block_type == "caption":
        min_font_size = 18
    elif block_type == "formula":
        min_font_size = 22
    else:  # paragraph / text
        min_font_size = 22

    # Đảm bảo font_size ban đầu không nhỏ hơn min_font_size
    if font_size < min_font_size:
        font_size = min_font_size

    text = block.get("text", "")
    lines = block.get("lines", [])
    
    original_font_size = font_size
    # Nếu block có text thì dùng fit_text_to_box để tự động chia dòng và giảm cỡ chữ
    if text:
        fit_res = fit_text_to_box(
            text, 
            box_width=width, 
            box_height=height, 
            initial_font_size=font_size,
            min_font_size=min_font_size,
            line_height_ratio=1.25
        )
        font_size = fit_res.get("fontSize", font_size)
        lines = fit_res.get("lines", [])
        if fit_res.get("overflow"):
            warnings.append(f"[SEVERE] Block '{block.get('id', 'unknown')}' ({block_type}) text overflows bounding box [w={width}, h={height}] at min_font_size={min_font_size}")
        elif font_size < original_font_size:
            warnings.append(f"[WARNING] Block '{block.get('id', 'unknown')}' ({block_type}) font size reduced from {original_font_size} to {font_size} to fit block")
            
    # Nếu chỉ có lines thì vẫn giảm cỡ chữ nếu vượt chiều cao
    elif lines:
        line_height_ratio = 1.25
        total_height = len(lines) * font_size * line_height_ratio
        if total_height > height:
            while total_height > height and font_size > min_font_size:
                font_size -= 1
                total_height = len(lines) * font_size * line_height_ratio
            if total_height > height:
                warnings.append(f"[SEVERE] Block '{block.get('id', 'unknown')}' ({block_type}) lines overflow bounding box [h={height}] at min_font_size={min_font_size}")
            elif font_size < original_font_size:
                warnings.append(f"[WARNING] Block '{block.get('id', 'unknown')}' ({block_type}) font size reduced from {original_font_size} to {font_size} to fit block")
                
    if not lines:
        return ""
        
    anchor, tspan_x = get_alignment_props(align, x, width)
    font_family = "DejaVu Sans, Noto Sans, Arial, sans-serif"
    
    start_y = y + font_size * 0.85
    line_height = font_size * 1.25
    
    tspans = []
    for i, line in enumerate(lines):
        escaped_line = escape_xml(line)
        if i == 0:
            tspans.append(f'<tspan x="{tspan_x}" y="{start_y}">{escaped_line}</tspan>')
        else:
            tspans.append(f'<tspan x="{tspan_x}" dy="{line_height}">{escaped_line}</tspan>')
            
    tspan_str = "\n  ".join(tspans)
    
    return f"""  <text font-family="{font_family}" font-size="{font_size}" font-weight="{font_weight}" text-anchor="{anchor}" fill="#000000">
    {tspan_str}
  </text>"""

def render_table(block: dict, warnings: list) -> str:
    """
    Renders table using <rect> for cell borders/backgrounds and <text> for values.
    Supports left and right alignment (text-anchor="end" for currency/amounts).
    """
    x = block.get("x", 0)
    y = block.get("y", 0)
    font_size = block.get("fontSize", 16)
    columns = block.get("columns", [])
    rows = block.get("rows", [])
    
    if not columns or not rows:
        return ""
        
    font_family = "DejaVu Sans, Noto Sans, Arial, sans-serif"
    svg_elements = []
    
    min_cell_font_size = 20  # table cell min_font_size = 20
    if font_size < min_cell_font_size:
        font_size = min_cell_font_size

    current_y = y
    for row_idx, row in enumerate(rows):
        row_height = row.get("height", 50)
        current_x = x
        cells = row.get("cells", [])
        
        for col_idx, col in enumerate(columns):
            if col_idx >= len(cells):
                break
                
            col_width = col.get("width", 100)
            align = col.get("align", "left").lower()
            cell_text = cells[col_idx]
            
            # Stylize header row (gray fill, bold text)
            cell_fill = "#f2f2f2" if row_idx == 0 else "none"
            font_weight = "bold" if row_idx == 0 else "normal"
            
            # Draw cell border
            svg_elements.append(
                f'  <rect x="{current_x}" y="{current_y}" width="{col_width}" height="{row_height}" fill="{cell_fill}" stroke="#000000" stroke-width="2" />'
            )
            
            # Fit single line text width inside cell
            cell_font_size = font_size
            padding = 15
            max_text_w = col_width - padding * 2
            
            font = load_font(None, cell_font_size)
            text_w = get_text_width(cell_text, font)
            
            while text_w > max_text_w and cell_font_size > min_cell_font_size:
                cell_font_size -= 1
                font = load_font(None, cell_font_size)
                text_w = get_text_width(cell_text, font)
                
            if text_w > max_text_w:
                warnings.append(f"[SEVERE] Table block '{block.get('id', 'unknown')}' cell '{cell_text}' overflows column width {col_width} at min_font_size={min_cell_font_size}")
            elif cell_font_size < font_size:
                warnings.append(f"[WARNING] Table cell '{cell_text}' font size reduced from {font_size} to {cell_font_size} to fit column width")
            
            # Horizontal cell alignment
            if align == "center":
                text_anchor = "middle"
                text_x = current_x + col_width / 2
            elif align == "right":
                text_anchor = "end"
                text_x = current_x + col_width - padding
            else:
                text_anchor = "start"
                text_x = current_x + padding
                
            # Vertical center adjustment
            text_y = current_y + row_height / 2 + cell_font_size * 0.35
            
            escaped_text = escape_xml(cell_text)
            svg_elements.append(
                f'  <text x="{text_x}" y="{text_y}" font-family="{font_family}" font-size="{cell_font_size}" font-weight="{font_weight}" text-anchor="{text_anchor}" fill="#000000">{escaped_text}</text>'
            )
            
            current_x += col_width
            
        current_y += row_height
        
    return "\n".join(svg_elements)

def render_arrow(block: dict) -> str:
    """
    Renders arrow using <line> with marker-end.
    Optionally puts a text label centered on top of the arrow line.
    """
    x1 = block.get("x1", 0)
    y1 = block.get("y1", 0)
    x2 = block.get("x2", 0)
    y2 = block.get("y2", 0)
    stroke_width = block.get("strokeWidth", 4)
    color = block.get("color", "#000000")
    label = block.get("label", "")
    
    svg_elements = []
    
    # Draw arrow line referencing the defs marker
    svg_elements.append(
        f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{stroke_width}" marker-end="url(#arrowhead)" />'
    )
    
    if label:
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2 - 10
        font_family = "DejaVu Sans, Noto Sans, Arial, sans-serif"
        font_size = max(14, int(stroke_width * 3.5))
        escaped_label = escape_xml(label)
        svg_elements.append(
            f'  <text x="{mid_x}" y="{mid_y}" font-family="{font_family}" font-size="{font_size}" text-anchor="middle" fill="{color}">{escaped_label}</text>'
        )
        
    return "\n".join(svg_elements)

def render_svg(layout: dict, output_path: str) -> list[str]:
    """
    Converts a complete layout dictionary to an SVG file.
    Returns a list of overflow warnings.
    """
    page = layout.get("page", {})
    width = page.get("width", 800)
    height = page.get("height", 600)
    background = page.get("background", "#ffffff")
    
    blocks = layout.get("blocks", [])
    
    svg_content = []
    warnings = []
    
    # Root element
    svg_content.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">')
    
    # Standard definitions (like arrowhead marker)
    svg_content.append('  <defs>')
    svg_content.append('    <marker id="arrowhead" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">')
    svg_content.append('      <path d="M 0 0 L 10 5 L 0 10 z" fill="#000000" />')
    svg_content.append('    </marker>')
    svg_content.append('  </defs>')
    
    # Page canvas
    svg_content.append(f'  <rect width="{width}" height="{height}" fill="{background}" />')
    
    # Render layout blocks
    for block in blocks:
        block_type = block.get("type", "").lower()
        if block_type in ("title", "paragraph", "text"):
            svg_content.append(render_text_block(block, warnings))
        elif block_type == "table":
            svg_content.append(render_table(block, warnings))
        elif block_type == "arrow":
            svg_content.append(render_arrow(block))
            
    svg_content.append('</svg>')
    
    # Save output file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg_content))

    return warnings


def export_svg_to_formats(svg_path, png_path, pdf_path, export_png=True, export_pdf=False):
    if not (export_png or export_pdf):
        return
    try:
        import cairosvg
        if export_png:
            print(f"→ Xuất PNG preview bằng CairoSVG")
            cairosvg.svg2png(url=str(svg_path), write_to=str(png_path))
            print(f"✓ Đã lưu PNG preview tại: {png_path}")
        if export_pdf:
            print(f"→ Xuất PDF bằng CairoSVG")
            cairosvg.svg2pdf(url=str(svg_path), write_to=str(pdf_path))
            print(f"✓ Đã lưu PDF tại: {pdf_path}")
    except Exception as e:
        print(f"⚠ Lỗi khi xuất PNG/PDF bằng CairoSVG: {e}")
