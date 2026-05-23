def is_numeric(val):
    """
    Checks if a value is a number (int or float) and not a boolean.
    """
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def validate_layout(layout: dict) -> list[str]:
    """
    Validates a JSON layout schema before rendering SVG.
    Returns a list of error messages. If empty, the layout is valid.
    """
    errors = []
    
    if not isinstance(layout, dict):
        return ["Layout must be a dictionary"]
        
    page = layout.get("page")
    if not page or not isinstance(page, dict):
        return ["Layout missing 'page' configuration or it is not a dictionary"]
        
    page_width = page.get("width")
    page_height = page.get("height")
    
    if page_width is None:
        errors.append("Page 'width' is missing")
    elif not is_numeric(page_width) or page_width <= 0:
        errors.append(f"Page 'width' must be a positive number: {page_width}")
        
    if page_height is None:
        errors.append("Page 'height' is missing")
    elif not is_numeric(page_height) or page_height <= 0:
        errors.append(f"Page 'height' must be a positive number: {page_height}")
        
    # If page dimensions are invalid, stop validation early to prevent further out-of-bounds check errors
    if errors:
        return errors
        
    blocks = layout.get("blocks")
    if blocks is None:
        errors.append("Layout missing 'blocks' list")
        return errors
    elif not isinstance(blocks, list):
        errors.append("'blocks' must be a list")
        return errors
        
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"Block at index {idx} is not a dictionary")
            continue
            
        block_id = block.get("id", f"index_{idx}")
        block_type = block.get("type")
        
        if not block_type:
            errors.append(f"Block '{block_id}' missing 'type'")
            continue
            
        block_type = str(block_type).lower()
        
        # Validations for text-like blocks and tables (they share bounding box checks)
        if block_type in ("title", "paragraph", "caption", "formula", "text", "table"):
            x = block.get("x")
            y = block.get("y")
            width = block.get("width")
            height = block.get("height")
            
            # Check bounding box keys exist
            missing_box_keys = []
            if x is None: missing_box_keys.append("x")
            if y is None: missing_box_keys.append("y")
            if width is None: missing_box_keys.append("width")
            if height is None: missing_box_keys.append("height")
            
            if missing_box_keys:
                errors.append(f"Block '{block_id}' ({block_type}) missing bounding box attributes: {', '.join(missing_box_keys)}")
                continue
                
            # Check bounding box numeric types
            if not all(is_numeric(val) for val in (x, y, width, height)):
                errors.append(f"Block '{block_id}' bounding box coordinates and sizes must be numeric")
                continue
                
            # Check positive width/height
            if width <= 0 or height <= 0:
                errors.append(f"Block '{block_id}' width and height must be positive numbers")
                continue
                
            # Check within page bounds
            if x < 0 or y < 0 or (x + width) > page_width or (y + height) > page_height:
                errors.append(f"Block '{block_id}' ({block_type}) boundaries [x={x}, y={y}, w={width}, h={height}] exceed page dimensions [{page_width}x{page_height}]")
                
            # Type-specific text-like checks
            if block_type in ("title", "paragraph", "caption", "formula", "text"):
                lines = block.get("lines")
                font_size = block.get("fontSize", 16)
                
                if lines is None:
                    errors.append(f"Block '{block_id}' ({block_type}) missing 'lines'")
                elif not isinstance(lines, list):
                    errors.append(f"Block '{block_id}' 'lines' must be a list")
                else:
                    if not is_numeric(font_size) or font_size <= 0:
                        errors.append(f"Block '{block_id}' 'fontSize' must be a positive number: {font_size}")
                    else:
                        # total text height check (lines * font_size * 1.25)
                        total_text_height = len(lines) * font_size * 1.25
                        if total_text_height > height:
                            errors.append(f"Block '{block_id}' text lines height ({total_text_height}) exceeds block height ({height})")
                            
            # Type-specific table checks
            elif block_type == "table":
                columns = block.get("columns")
                rows = block.get("rows")
                
                if columns is None:
                    errors.append(f"Table '{block_id}' missing 'columns'")
                elif not isinstance(columns, list):
                    errors.append(f"Table '{block_id}' 'columns' must be a list")
                    
                if rows is None:
                    errors.append(f"Table '{block_id}' missing 'rows'")
                elif not isinstance(rows, list):
                    errors.append(f"Table '{block_id}' 'rows' must be a list")
                    
                # Validate columns and rows details
                if isinstance(columns, list) and isinstance(rows, list):
                    # Check column widths
                    col_width_errors = False
                    sum_col_widths = 0
                    for c_idx, col in enumerate(columns):
                        if not isinstance(col, dict):
                            errors.append(f"Table '{block_id}' column at index {c_idx} is not a dictionary")
                            col_width_errors = True
                            continue
                        w = col.get("width")
                        if w is None or not is_numeric(w) or w <= 0:
                            errors.append(f"Table '{block_id}' column at index {c_idx} has invalid width: {w}")
                            col_width_errors = True
                        else:
                            sum_col_widths += w
                            
                    # Check row heights
                    row_height_errors = False
                    sum_row_heights = 0
                    for r_idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            errors.append(f"Table '{block_id}' row at index {r_idx} is not a dictionary")
                            row_height_errors = True
                            continue
                        h = row.get("height")
                        if h is None or not is_numeric(h) or h <= 0:
                            errors.append(f"Table '{block_id}' row at index {r_idx} has invalid height: {h}")
                            row_height_errors = True
                        else:
                            sum_row_heights += h
                            
                    # Validate width/height sum match if no individual errors occurred
                    if not col_width_errors:
                        if abs(sum_col_widths - width) > 10:
                            errors.append(f"Table '{block_id}' sum of column widths ({sum_col_widths}) deviates too much from block width ({width})")
                            
                    if not row_height_errors:
                        if abs(sum_row_heights - height) > 10:
                            errors.append(f"Table '{block_id}' sum of row heights ({sum_row_heights}) deviates too much from block height ({height})")
                            
                    # Check cells structure per row
                    for r_idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            continue
                        cells = row.get("cells")
                        if cells is None:
                            errors.append(f"Table '{block_id}' row {r_idx} missing 'cells'")
                        elif not isinstance(cells, list):
                            errors.append(f"Table '{block_id}' row {r_idx} 'cells' must be a list")
                        elif len(cells) != len(columns):
                            errors.append(f"Table '{block_id}' row {r_idx} cells count ({len(cells)}) must match columns count ({len(columns)})")
                            
        # Validations for arrows
        elif block_type == "arrow":
            x1 = block.get("x1")
            y1 = block.get("y1")
            x2 = block.get("x2")
            y2 = block.get("y2")
            
            missing_arrow_keys = []
            if x1 is None: missing_arrow_keys.append("x1")
            if y1 is None: missing_arrow_keys.append("y1")
            if x2 is None: missing_arrow_keys.append("x2")
            if y2 is None: missing_arrow_keys.append("y2")
            
            if missing_arrow_keys:
                errors.append(f"Arrow '{block_id}' missing coordinates: {', '.join(missing_arrow_keys)}")
                continue
                
            if not all(is_numeric(val) for val in (x1, y1, x2, y2)):
                errors.append(f"Arrow '{block_id}' coordinates must be numeric")
                continue
                
            # Check within page bounds
            if x1 < 0 or x1 > page_width or x2 < 0 or x2 > page_width or y1 < 0 or y1 > page_height or y2 < 0 or y2 > page_height:
                errors.append(f"Arrow '{block_id}' coordinates [({x1}, {y1}) -> ({x2}, {y2})] exceed page dimensions [{page_width}x{page_height}]")
                
        else:
            errors.append(f"Block '{block_id}' has unknown type: {block_type}")
            
    return errors


def is_severe_error(err_msg: str) -> bool:
    """
    Checks if a validation error message is severe (not just deviation/size warnings).
    """
    non_severe_keywords = [
        "deviates too much",
        "exceeds block height",
        "exceed page dimensions"
    ]
    return not any(kw in err_msg for kw in non_severe_keywords)


def validate_layout_classified(layout: dict) -> tuple[list[str], list[str]]:
    """
    Validates a JSON layout schema and classifies checks into:
    - severe: critical errors preventing rendering or causing severe bugs.
    - warnings: minor alignment deviations or font adjustments.
    Returns (severe_errors, warnings).
    """
    severe = []
    warnings = []
    
    if not isinstance(layout, dict):
        return ["Layout must be a dictionary"], []
        
    page = layout.get("page")
    if not page or not isinstance(page, dict):
        return ["Layout missing 'page' configuration or it is not a dictionary"], []
        
    page_width = page.get("width")
    page_height = page.get("height")
    
    if page_width is None:
        severe.append("Page 'width' is missing")
    elif not is_numeric(page_width) or page_width <= 0:
        severe.append(f"Page 'width' must be a positive number: {page_width}")
        
    if page_height is None:
        severe.append("Page 'height' is missing")
    elif not is_numeric(page_height) or page_height <= 0:
        severe.append(f"Page 'height' must be a positive number: {page_height}")
        
    if severe:
        return severe, warnings
        
    blocks = layout.get("blocks")
    if blocks is None:
        severe.append("Layout missing 'blocks' list")
        return severe, warnings
    elif not isinstance(blocks, list):
        severe.append("'blocks' must be a list")
        return severe, warnings
        
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            severe.append(f"Block at index {idx} is not a dictionary")
            continue
            
        block_id = block.get("id", f"index_{idx}")
        block_type = block.get("type")
        
        if not block_type:
            severe.append(f"Block '{block_id}' missing 'type'")
            continue
            
        block_type = str(block_type).lower()
        
        if block_type in ("title", "paragraph", "caption", "formula", "text", "table"):
            x = block.get("x")
            y = block.get("y")
            width = block.get("width")
            height = block.get("height")
            
            missing_box_keys = []
            if x is None: missing_box_keys.append("x")
            if y is None: missing_box_keys.append("y")
            if width is None: missing_box_keys.append("width")
            if height is None: missing_box_keys.append("height")
            
            if missing_box_keys:
                severe.append(f"Block '{block_id}' ({block_type}) missing bounding box attributes: {', '.join(missing_box_keys)}")
                continue
                
            if not all(is_numeric(val) for val in (x, y, width, height)):
                severe.append(f"Block '{block_id}' bounding box coordinates and sizes must be numeric")
                continue
                
            if width <= 0 or height <= 0:
                severe.append(f"Block '{block_id}' width and height must be positive numbers")
                continue
                
            # Block exceeds page bounds -> severe
            if x < 0 or y < 0 or (x + width) > page_width or (y + height) > page_height:
                severe.append(f"Block '{block_id}' ({block_type}) boundaries [x={x}, y={y}, w={width}, h={height}] exceed page dimensions [{page_width}x{page_height}]")
                
            if block_type in ("title", "paragraph", "caption", "formula", "text"):
                lines = block.get("lines")
                font_size = block.get("fontSize", 16)
                
                if lines is None:
                    if block.get("text") is None:
                        severe.append(f"Block '{block_id}' ({block_type}) missing both 'lines' and 'text'")
                elif not isinstance(lines, list):
                    severe.append(f"Block '{block_id}' 'lines' must be a list")
                else:
                    if not is_numeric(font_size) or font_size <= 0:
                        severe.append(f"Block '{block_id}' 'fontSize' must be a positive number: {font_size}")
                            
            elif block_type == "table":
                columns = block.get("columns")
                rows = block.get("rows")
                
                if columns is None:
                    severe.append(f"Table '{block_id}' missing 'columns'")
                elif not isinstance(columns, list):
                    severe.append(f"Table '{block_id}' 'columns' must be a list")
                    
                if rows is None:
                    severe.append(f"Table '{block_id}' missing 'rows'")
                elif not isinstance(rows, list):
                    severe.append(f"Table '{block_id}' 'rows' must be a list")
                    
                if isinstance(columns, list) and isinstance(rows, list):
                    col_width_errors = False
                    sum_col_widths = 0
                    for c_idx, col in enumerate(columns):
                        if not isinstance(col, dict):
                            severe.append(f"Table '{block_id}' column at index {c_idx} is not a dictionary")
                            col_width_errors = True
                            continue
                        w = col.get("width")
                        if w is None or not is_numeric(w) or w <= 0:
                            severe.append(f"Table '{block_id}' column at index {c_idx} has invalid width: {w}")
                            col_width_errors = True
                        else:
                            sum_col_widths += w
                            
                    row_height_errors = False
                    sum_row_heights = 0
                    for r_idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            severe.append(f"Table '{block_id}' row at index {r_idx} is not a dictionary")
                            row_height_errors = True
                            continue
                        h = row.get("height")
                        if h is None or not is_numeric(h) or h <= 0:
                            severe.append(f"Table '{block_id}' row at index {r_idx} has invalid height: {h}")
                            row_height_errors = True
                        else:
                            sum_row_heights += h
                            
                    # Deviations are warnings
                    if not col_width_errors:
                        if abs(sum_col_widths - width) > 10:
                            warnings.append(f"Table '{block_id}' sum of column widths ({sum_col_widths}) deviates too much from block width ({width})")
                            
                    if not row_height_errors:
                        if abs(sum_row_heights - height) > 10:
                            warnings.append(f"Table '{block_id}' sum of row heights ({sum_row_heights}) deviates too much from block height ({height})")
                            
                    for r_idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            continue
                        cells = row.get("cells")
                        if cells is None:
                            severe.append(f"Table '{block_id}' row {r_idx} missing 'cells'")
                        elif not isinstance(cells, list):
                            severe.append(f"Table '{block_id}' row {r_idx} 'cells' must be a list")
                        elif len(cells) != len(columns):
                            severe.append(f"Table '{block_id}' row {r_idx} cells count ({len(cells)}) must match columns count ({len(columns)})")
                            
        elif block_type == "arrow":
            x1 = block.get("x1")
            y1 = block.get("y1")
            x2 = block.get("x2")
            y2 = block.get("y2")
            
            missing_arrow_keys = []
            if x1 is None: missing_arrow_keys.append("x1")
            if y1 is None: missing_arrow_keys.append("y1")
            if x2 is None: missing_arrow_keys.append("x2")
            if y2 is None: missing_arrow_keys.append("y2")
            
            if missing_arrow_keys:
                severe.append(f"Arrow '{block_id}' missing coordinates: {', '.join(missing_arrow_keys)}")
                continue
                
            if not all(is_numeric(val) for val in (x1, y1, x2, y2)):
                severe.append(f"Arrow '{block_id}' coordinates must be numeric")
                continue
                
            if x1 < 0 or x1 > page_width or x2 < 0 or x2 > page_width or y1 < 0 or y1 > page_height or y2 < 0 or y2 > page_height:
                severe.append(f"Arrow '{block_id}' coordinates [({x1}, {y1}) -> ({x2}, {y2})] exceed page dimensions [{page_width}x{page_height}]")
                
        else:
            severe.append(f"Block '{block_id}' has unknown type: {block_type}")
            
    return severe, warnings
