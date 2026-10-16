"""Conservative white-paper raster layout checks; no OCR or content validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError

from layout_profile import LayoutProfile

LIMITATIONS = [
    "PASS only means no configured layout anomaly was detected; it does not validate translation or mathematics.",
    "Dark-pixel geometry assumes a light paper background; figures, shadows and decoration may trigger warnings.",
    "No OCR: titles, page numbers, font size and missing semantic content cannot be identified reliably.",
]


def _ink_mask(path: str | Path, profile: LayoutProfile) -> Image.Image:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width * height > profile.max_pixels:
                raise ValueError("image exceeds max_pixels")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("multi-frame images are unsupported")
            if image.getexif().get(274, 1) != 1:
                raise ValueError("non-identity EXIF orientation requires explicit preprocessing")
            image.load()
            if "A" in image.getbands() or "transparency" in image.info:
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", image.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = image.convert("RGB")
            return rgb.convert("L").point(
                [255 if value < profile.ink_luma_threshold else 0 for value in range(256)]
            )
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError(f"cannot read image: {exc}") from exc


def _region_box(region: tuple[int, ...], size: list[int], target: tuple[int, int]) -> list[int]:
    return [round(region[index] * size[index % 2] / target[index % 2]) for index in range(4)]


def _occupancy(mask: Image.Image, region: list[int]) -> float:
    x0, y0, x1, y1 = region
    area = (x1 - x0) * (y1 - y0)
    return mask.crop(region).histogram()[255] / area if area > 0 else 0.0


def measure_image(path: str | Path, profile: LayoutProfile) -> dict[str, Any]:
    """Read one raster; all regions use its pixel coordinates, rectangles are half-open."""
    with _ink_mask(path, profile) as mask:
        width, height = mask.size
        size = [width, height]
        bbox = mask.getbbox()
        rows = mask.getprojection()[1]
        runs = []
        start = None
        for y, occupied in enumerate(rows + [0]):
            if occupied and start is None:
                start = y
            elif not occupied and start is not None:
                runs.append([start, y])
                start = None
        gaps = [[a[1], b[0]] for a, b in zip(runs, runs[1:])]
        gap = max(gaps, key=lambda item: item[1] - item[0], default=[0, 0])
        content = _region_box(profile.content_box, size, profile.target_size)
        header = [0, 0, width, content[1]]
        footer = [0, content[3], width, height]
        bands = {
            "header": {"occupancy": _occupancy(mask, header), "region": header},
            "footer": {"occupancy": _occupancy(mask, footer), "region": footer},
            "largest_interior_gap": {"fraction": (gap[1] - gap[0]) / height,
                                     "region": [0, gap[0], width, gap[1]]},
            "first_ink_band": runs[0] if runs else None,
            "ink_band_count": len(runs),
        }
        if profile.page_number_region:
            number = _region_box(profile.page_number_region, size, profile.target_size)
            bands["page_number"] = {"occupancy": _occupancy(mask, number), "region": number}
            outside = mask.crop(footer)
            if number[0] < number[2] and number[1] < number[3]:
                ImageDraw.Draw(outside).rectangle(
                    (number[0], number[1] - footer[1], number[2] - 1, number[3] - footer[1] - 1), fill=0
                )
            bands["footer_outside_page_number"] = {
                "occupancy": outside.histogram()[255] / max(1, outside.width * outside.height),
                "region": footer,
            }
            outside.close()
        return {
            "size": size,
            "content_bbox": list(bbox) if bbox else None,
            "normalized_margins": ([bbox[0] / width, bbox[1] / height,
                                    (width - bbox[2]) / width, (height - bbox[3]) / height]
                                   if bbox else None),
            "ink_fraction": mask.histogram()[255] / (width * height),
            "bands": bands,
        }


def check_layout(source_path: str | Path, generated_path: str | Path,
                 profile: LayoutProfile, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Measure layout independently of translation state and return a JSON-safe report."""
    if profile.source_aware_enabled and profile.qc_enabled:
        return check_source_layout(source_path, generated_path, profile, metadata=metadata)
    result: dict[str, Any] = {"status": "PASS", "findings": [], "metrics": {},
                              "limitations": list(LIMITATIONS)}
    if not profile.qc_enabled:
        result["status"] = "SKIPPED"
        return result

    def add(code: str, severity: str, message: str, region: list[int] | None = None,
            relayout: bool = False) -> None:
        result["findings"].append({"code": code, "severity": severity, "message": message,
                                   "region": region, "requires_relayout": relayout})
        if severity == "FAIL" or result["status"] == "PASS":
            result["status"] = severity

    paths = {"source": source_path, "generated": generated_path}
    if profile.approved_sample is not None:
        paths["sample"] = profile.approved_sample
    for name, path in paths.items():
        try:
            result["metrics"][name] = measure_image(path, profile)
        except (ValueError, TypeError) as exc:
            add(f"INVALID_{name.upper()}", "FAIL", str(exc))
    if len(result["metrics"]) != len(paths):
        return result

    generated = result["metrics"]["generated"]
    source = result["metrics"]["source"]
    sample = result["metrics"].get("sample")
    thresholds = profile.thresholds
    width, height = generated["size"]
    # Translation changes line breaks and density. The source is a structural
    # reference, while the book profile defines the Vietnamese output canvas.
    source_w, source_h = source["size"]
    result["metrics"]["source_comparison"] = {
        "dimension_difference": max(abs(width / source_w - 1), abs(height / source_h - 1)),
        "aspect_difference": abs((width / height) / (source_w / source_h) - 1),
        "ink_fraction_difference": abs(generated["ink_fraction"] - source["ink_fraction"]),
        "affects_status": False,
    }
    target_w, target_h = profile.target_size
    difference = max(abs(width / target_w - 1), abs(height / target_h - 1))
    if difference > thresholds["dimension_warning"]:
        add("TARGET_SIZE_DRIFT", "WARNING", f"Dimensions differ from the book target by {difference:.1%}.")
    aspect = abs((width / height) / (target_w / target_h) - 1)
    if aspect > thresholds["aspect_warning"]:
        severity = "FAIL" if aspect > thresholds["aspect_fail"] else "WARNING"
        add("TARGET_ASPECT_DRIFT", severity, f"Aspect ratio differs from the book target by {aspect:.1%}.")

    bbox = generated["content_bbox"]
    if bbox is None:
        add("EMPTY_PAGE", "FAIL", "No dark content detected on the generated page.", relayout=True)
        return result
    if generated["ink_fraction"] < thresholds["min_ink_fraction"]:
        add("VERY_SPARSE_PAGE", "WARNING", "Very little dark content detected.", bbox, True)
    if sample and abs(generated["ink_fraction"] - sample["ink_fraction"]) > thresholds["ink_difference_warning"]:
        add("INK_DENSITY_DRIFT", "WARNING", "Dark-content density differs substantially from the approved sample; review the page type and text length.", bbox)

    left, top, right, bottom = profile.content_box
    target_w, target_h = profile.target_size
    expected = [left / target_w, top / target_h, (target_w - right) / target_w,
                (target_h - bottom) / target_h]
    margins = generated["normalized_margins"]
    if any(b - a > thresholds["margin_warning"] for a, b in zip(margins, expected)):
        add("TARGET_MARGIN_DRIFT", "WARNING", "Dark content extends into the configured safe margins.", bbox)
    # A short final page may leave a large bottom margin. Check horizontal
    # balance without requiring every page to fill the available content box.
    balance = abs((margins[0] - margins[2]) - (expected[0] - expected[2]))
    if balance > 2 * thresholds["margin_warning"]:
        add("HORIZONTAL_IMBALANCE", "WARNING", "Dark-content bounds are shifted horizontally relative to the configured content region; decoration and figures may contribute.", bbox)
    if sample and sample["normalized_margins"] is not None:
        sample_margins = sample["normalized_margins"]
        mirrored = [sample_margins[2], sample_margins[1], sample_margins[0], sample_margins[3]]
        # Extra white space below a shorter translation is legitimate, even
        # with an approved sample. Keep upper/horizontal placement checks.
        difference = min(max(abs(margins[0] - candidate[0]),
                             abs(margins[1] - candidate[1]),
                             abs(margins[2] - candidate[2]),
                             candidate[3] - margins[3])
                         for candidate in (sample_margins, mirrored))
        if difference > thresholds["sample_margin_warning"]:
            add("SAMPLE_MARGIN_DRIFT", "WARNING", "Content margins differ from both the approved sample and its mirrored page layout.", bbox)
    for name, margin in zip(("LEFT", "TOP", "RIGHT", "BOTTOM"), margins):
        if margin <= thresholds["edge_fail"]:
            add(f"{name}_EDGE_CONTENT", "FAIL", "Dark content touches the edge or violates the minimum safe margin; clipping is possible.", bbox, True)
        elif margin < thresholds["edge_warning"]:
            add(f"{name}_NEAR_EDGE", "WARNING", "Dark content is close to the page edge.", bbox)

    gap = generated["bands"]["largest_interior_gap"]
    reference_gap = max(reference["bands"]["largest_interior_gap"]["fraction"]
                        for reference in (source, sample) if reference is not None)
    if (gap["fraction"] > thresholds["whitespace_band_warning"] and
            gap["fraction"] - reference_gap > thresholds["whitespace_band_warning"] / 2):
        add("INTERIOR_WHITESPACE", "WARNING", "Large interior white band exceeds the reference pattern.", gap["region"])
    for name in ("header", "footer"):
        band = generated["bands"][name]
        if sample:
            delta = abs(band["occupancy"] - sample["bands"][name]["occupancy"])
            if delta > thresholds["header_footer_occupancy_warning"]:
                add(f"{name.upper()}_SAMPLE_DRIFT", "WARNING", f"{name.title()} occupancy differs from the approved sample.", band["region"], True)
        elif band["occupancy"] > thresholds["header_footer_occupancy_warning"]:
            add(f"{name.upper()}_CONTENT", "WARNING", f"Dark content detected in configured {name} margin.", band["region"])
    if sample:
        first = generated["bands"]["first_ink_band"]
        sample_first = sample["bands"]["first_ink_band"]
        sample_h = sample["size"][1]
        if (first and sample_first and generated["bands"]["ink_band_count"] >= 2
                and sample["bands"]["ink_band_count"] >= 2
                and first[0] / height < 0.25 and sample_first[0] / sample_h < 0.25
                and (first[1] - first[0]) / height - (sample_first[1] - sample_first[0]) / sample_h
                > thresholds["title_height_warning"]):
            add("TITLE_HEIGHT_SUSPECT", "WARNING", "The first upper ink band is taller than the sample; it may be a title, figure or merged text lines.", [bbox[0], first[0], bbox[2], first[1]], True)
    if profile.page_number_region:
        band = generated["bands"]["footer_outside_page_number"]
        if band["occupancy"] > thresholds["header_footer_occupancy_warning"]:
            add("FOOTER_OUTSIDE_NUMBER_TEMPLATE", "WARNING", "Footer ink extends outside the page-number template; its meaning is unknown and cannot be moved automatically.", band["region"], True)
        number = generated["bands"]["page_number"]
        if sample and sample["bands"]["page_number"]["occupancy"] > 0 and number["occupancy"] == 0:
            add("NUMBER_TEMPLATE_EMPTY", "WARNING", "The sample has ink in the number template but this page has none; no page number has been inferred.", number["region"], True)
    return result

# The optional image-analysis dependency is loaded only in source-aware mode.
def _source_dependencies():
    import cv2
    import numpy as np
    return cv2, np


def _norm_box(box, width, height):
    return [float(box[0]) / width, float(box[1]) / height,
            float(box[2]) / width, float(box[3]) / height]


def _pixel_box(box, metrics):
    if box is None:
        return None
    frame = metrics['page_frame']
    return [round(frame[i % 2] + box[i] * (frame[2 + i % 2] - frame[i % 2])) for i in range(4)]


def _center(box):
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]


def _box_distance(a, b):
    return max(abs(x - y) for x, y in zip(_center(a), _center(b)))


def measure_source_page(path: str | Path, profile: LayoutProfile) -> dict[str, Any]:
    """Bounded raster measurements; normalized boxes refer to the detected page.

    Components are candidates, not semantic identifications. No OCR, mathematical
    correctness, figure labels or exact font sizes are inferred. Originals remain
    untouched. Analysis thumbnails retain aspect ratio.
    """
    cv2, np = _source_dependencies()
    from statistics import median
    with _ink_mask(path, profile) as full_mask:
        original_size = list(full_mask.size)
        import hashlib
        full_bbox = full_mask.getbbox()
        ink_digest = None
        if full_bbox:
            with full_mask.crop(full_bbox) as content_mask:
                ink_digest = hashlib.sha256(str(content_mask.size).encode('ascii') + content_mask.tobytes()).hexdigest()
        scale = min(1.0, 1600 / max(full_mask.size))
        small = full_mask.resize((max(1, round(full_mask.width * scale)),
                                  max(1, round(full_mask.height * scale))), Image.Resampling.BOX)
    data = (np.asarray(small) >= 64).astype('uint8')
    small.close()
    full_h, full_w = data.shape
    # Remove only nearly solid outer scan strips, at most 6% per side. All
    # other edge marks remain for review; a detected paper frame is not a crop.
    x0, y0, x1, y1 = 0, 0, full_w, full_h
    while x0 < full_w * .06 and np.mean(data[:, x0]) > .80:
        x0 += 1
    while x1 > full_w * .94 and np.mean(data[:, x1 - 1]) > .80:
        x1 -= 1
    while y0 < full_h * .06 and np.mean(data[y0, x0:x1]) > .80:
        y0 += 1
    while y1 > full_h * .94 and np.mean(data[y1 - 1, x0:x1]) > .80:
        y1 -= 1
    data = data[y0:y1, x0:x1].copy()
    height, width = data.shape
    frame = [round(x0 / full_w * original_size[0]), round(y0 / full_h * original_size[1]),
             round(x1 / full_w * original_size[0]), round(y1 / full_h * original_size[1])]
    border_removed = frame != [0, 0, *original_size]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(data, connectivity=8)
    clean = np.zeros_like(data)
    components = []
    for label in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[label]]
        if area < max(3, width * height * .000002):
            continue
        clean[y:y+h, x:x+w][labels[y:y+h, x:x+w] == label] = 1
        components.append({'box': _norm_box([x, y, x+w, y+h], width, height),
                           'pixels': [x, y, x+w, y+h], 'area': area, 'fill': area / (w * h)})
    # Detect slight skew without changing source pixels. Bounds remain in the
    # original frame and comparison thresholds gain an explicit angle tolerance.
    base_score = float(np.var(clean.mean(axis=1)))
    best_angle, best_score = 0.0, base_score
    for angle in (-2., -1., -.5, .5, 1., 2.):
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
        rotated = cv2.warpAffine(clean, matrix, (width, height), flags=cv2.INTER_NEAREST)
        score = float(np.var(rotated.mean(axis=1)))
        if score > best_score * 1.08:
            best_angle, best_score = angle, score
    ink_y, ink_x = np.nonzero(clean)
    bbox = ([int(ink_x.min()), int(ink_y.min()), int(ink_x.max()+1), int(ink_y.max()+1)]
            if len(ink_x) else None)
    confidence = .92 if bbox and len(components) >= 3 else .45
    if min(width, height) < 150:
        confidence = min(confidence, .50)
    if abs(best_angle) == 2:
        confidence = min(confidence, .65)
    geometry = []
    for comp in components:
        b = comp['box']
        bw, bh = b[2] - b[0], b[3] - b[1]
        if b[1] >= .12 and _center(b)[1] < .91 and bw >= .065 and bh >= .045 and .006 < comp['fill'] < .42:
            px = comp['pixels']
            patch = clean[px[1]:px[3], px[0]:px[2]]
            signature = cv2.resize(patch.astype('float32'), (12, 12), interpolation=cv2.INTER_AREA)
            mass = float(signature.sum())
            geometry.append({'box': b, 'confidence': min(confidence, .82), 'fill': comp['fill'],
                             'signature': (signature / max(mass, .00001)).ravel().tolist()})
    def bounds(items):
        if not items:
            return None
        return [min(c['box'][0] for c in items), min(c['box'][1] for c in items),
                max(c['box'][2] for c in items), max(c['box'][3] for c in items)]
    # A displaced running rule can cross the default band boundary. Extend
    # that band only for a thin, long rule, not for arbitrary upper body text.
    rules = [c['box'] for c in components if c['box'][2]-c['box'][0] > .45
             and c['box'][3]-c['box'][1] < .01 and c['box'][1] < .18]
    header_end = max(.115, min((b[3]+.01 for b in rules), default=.115))
    bands = {}
    for name, low, high in (('header', 0., header_end), ('body', header_end, .92), ('footer', .92, 1.)):
        selected = [c for c in components if low <= _center(c['box'])[1] < high
                    and (name != 'body' or c['area'] >= max(6, width * height * .00001))]
        band_confidence = min(confidence, .84) if selected else .4
        if name != 'body':
            # Prefer connected rules/ornaments over a union of every glyph in a
            # fixed band: body formulas may legitimately enter the footer band.
            anchors = [c for c in selected if c['box'][2]-c['box'][0] > .12
                       and c['box'][3]-c['box'][1] < .16]
            if anchors:
                anchor = (max(anchors, key=lambda c: c['box'][3]) if name == 'footer'
                          else min(anchors, key=lambda c: c['box'][1]))
                selected = [anchor]
            elif len(selected) > 12:
                band_confidence = min(band_confidence, .55)
        bands[name] = {'box': bounds(selected), 'confidence': band_confidence}
    geometry_boxes = [g['box'] for g in geometry]
    def inside_geometry(b):
        x, y = _center(b)
        return any(g[0] <= x <= g[2] and g[1] <= y <= g[3] for g in geometry_boxes)
    glyphs = [c for c in components if header_end <= _center(c['box'])[1] and c['box'][3] < .92
              and .004 <= c['box'][3]-c['box'][1] <= .038
              and .002 <= c['box'][2]-c['box'][0] <= .045
              and not inside_geometry(c['box'])]
    text_mask = np.zeros_like(clean)
    for comp in glyphs:
        x, y, right, bottom = comp['pixels']
        text_mask[y:bottom, x:right] = clean[y:bottom, x:right]
    joined = cv2.dilate(text_mask, np.ones((1, max(3, round(width * .015))), np.uint8))
    _, _, line_stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    lines = []
    for x, y, w, h, area in line_stats[1:]:
        if w > width * .06 and h >= 2:
            lines.append(_norm_box([x, y, x+w, y+h], width, height))
    lines.sort(key=lambda b: (b[1], b[0]))
    # Merge fragments on the same baseline before evaluating a title; comparing
    # one Chinese/Vietnamese word fragment would fabricate horizontal drift.
    rows = []
    for b in lines:
        if rows and min(rows[-1][3], b[3])-max(rows[-1][1], b[1]) > .5 * min(rows[-1][3]-rows[-1][1], b[3]-b[1]):
            a = rows[-1]
            rows[-1] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        else:
            rows.append(b)
    lines = rows
    line_centers = sorted(set(round(_center(b)[1], 3) for b in lines))
    spacings = [b-a for a, b in zip(line_centers, line_centers[1:]) if .008 <= b-a <= .07]
    glyph_height = median([g['box'][3]-g['box'][1] for g in glyphs]) if glyphs else None
    typography = {'glyph_height': glyph_height,
                  'line_spacing': median(spacings) if len(spacings) >= 3 else None,
                  'header_height': ((bands['header']['box'][3] - bands['header']['box'][1])
                                    if bands['header']['box'] else None),
                  'confidence': min(confidence, .78) if len(glyphs) >= 25 else .45,
                  'kind': 'visual_proxy_not_font_size'}
    title = None
    for b in [b for b in lines if header_end <= _center(b)[1] < .4]:
        next_y = min((o[1] for o in lines if o[1] > b[3] + .002), default=.92)
        previous_y = max((o[3] for o in lines if o[3] < b[1] - .002), default=max(0., header_end-.04))
        isolated = min(next_y-b[3], b[1]-previous_y) > .025
        prominent = glyph_height and b[3]-b[1] >= glyph_height * 1.12
        if isolated and prominent and .06 < b[2]-b[0] < .72 and abs(_center(b)[0]-.5) < .16:
            title = {'box': b, 'confidence': min(confidence, .74 if b[3]-b[1] >= glyph_height*1.4 else .55)}
            break
    formulas = []
    for b in lines:
        if .28 < b[1] < .9 and .08 < b[2]-b[0] < .65:
            before = max((o[3] for o in lines if o[3] < b[1]), default=.115)
            after = min((o[1] for o in lines if o[1] > b[3]), default=.92)
            if min(b[1]-before, after-b[3]) > .010:
                formulas.append({'box': b, 'confidence': min(confidence, .55), 'kind': 'unidentified_standalone_text'})
    occupied = clean.mean(axis=1) > .002
    gaps, start = [], None
    for row in range(round(height * .115), round(height * .92)+1):
        blank = row < round(height * .92) and not occupied[row]
        if blank and start is None:
            start = row
        if not blank and start is not None:
            if row - start > height * .04:
                gaps.append([0., start / height, 1., row / height])
            start = None
    norm = _norm_box(bbox, width, height) if bbox else None
    edge_regions = [c['box'] for c in components
                    if min(c['box'][0], c['box'][1], 1-c['box'][2], 1-c['box'][3]) <= profile.source_thresholds['edge_warning']
                    and c['area'] >= max(6, width * height * .00001)]
    result = {'size': original_size, 'analysis_size': [width, height], 'page_frame': frame,
              'frame_confidence': .80 if border_removed else confidence,
              'ink_content_digest': ink_digest,
              'scan_border_removed_for_measurement': border_removed,
              'skew_degrees': best_angle, 'skew_tolerance': abs(best_angle) / 90,
              'confidence': confidence, 'normalized_bbox': norm,
              'normalized_margins': [norm[0], norm[1], 1-norm[2], 1-norm[3]] if norm else None,
              'ink_fraction': float(clean.mean()), 'bands': bands,
              'geometry_regions': sorted(geometry, key=lambda g: (g['box'][1], g['box'][0])),
              'formula_candidates': formulas, 'title_candidate': title,
              'text_line_regions': lines, 'header_band_end': header_end,
              'typography': typography, 'blank_bands': gaps, 'edge_regions': edge_regions,
              'component_count': len(components)}
    result['content_bbox'] = _pixel_box(norm, result)
    # Absence of body content is assessed separately from page numbers, outer
    # ornaments and small scan specks. These are raster proxies, never OCR.
    body = [c for c in components if .08 <= _center(c['box'])[0] <= .92
            and .12 <= _center(c['box'])[1] <= .90]
    substantial = [c for c in body if c['area'] >= max(12, width * height * .00004)]
    interior = clean[round(height*.12):round(height*.90),
                     round(width*.08):round(width*.92)]
    result['content_evidence'] = {
        'body_ink_fraction': float(interior.mean()) if interior.size else None,
        'substantial_body_components': len(substantial),
        'body_text_lines': sum(.12 <= _center(b)[1] <= .90 and b[2]-b[0] >= .08
                               for b in lines),
        'body_geometry_candidates': sum(.12 <= _center(g['box'])[1] <= .90
                                        for g in geometry),
        'substantial_body_box': bounds(substantial),
        'method': 'bounded_connected_components_not_semantic_content',
    }
    return result


def check_source_layout(source_path, generated_path, profile, *, metadata=None):
    """Compare source and translation without changing legacy report statuses."""
    metadata = metadata or {}
    thresholds = profile.source_thresholds
    result = {'status': 'PASS', 'findings': [], 'metrics': {}, 'limitations': list(LIMITATIONS),
              'source_aware': {'status': 'REVIEW_REQUIRED', 'metrics': [],
                               'calibration': 'PROVISIONAL_NOT_VALIDATED_THRESHOLDS',
                               'geometry_verification': 'REVIEW_REQUIRED',
                               'formula_verification': 'REVIEW_REQUIRED',
                               'header_text_verification': 'REVIEW_REQUIRED'}}
    block = result['source_aware']
    canvas_only = False
    def add(code, message, *, severity='WARNING', confidence=0., region=None, source_region=None,
            evidence='suspected', remediation='manual_review', relayout=False):
        result['findings'].append({'code': code, 'severity': severity, 'message': message,
                                  'confidence': confidence, 'region': region, 'source_region': source_region,
                                  'evidence': evidence, 'remediation': remediation,
                                  'requires_relayout': relayout})
        if severity == 'FAIL' or result['status'] == 'PASS':
            result['status'] = severity
    def metric(name, value, threshold, confidence, code, reason, *, region=None, source_region=None,
               remediation='manual_review', confirmed=False, relayout=False):
        reliable = confidence >= thresholds['min_confidence']
        deviation = None if value is None else max(0., value-threshold)
        canvas_explained = canvas_only and name not in ('aspect_difference', 'edge_clearance', 'running_header_text_difference') and not name.startswith(('typography_', 'sample_'))
        state = 'REVIEW_REQUIRED' if value is None or not reliable else ('WARNING' if value > threshold and not canvas_explained else 'PASS')
        block['metrics'].append({'name': name, 'value': value, 'threshold': threshold,
                                 'deviation': deviation, 'confidence': confidence, 'status': state,
                                 'reason': reason, 'remediation': remediation, 'canvas_explained': canvas_explained})
        if value is not None and value > threshold and reliable and not canvas_explained:
            add(code, reason, confidence=confidence, region=region, source_region=source_region,
                evidence='confirmed' if confirmed else 'suspected', remediation=remediation,
                relayout=relayout)
    pages = [metadata.get(k) for k in ('page_number', 'source_page_number', 'generated_page_number')]
    known_pages = [p for p in pages if p is not None]
    if any(isinstance(p, bool) or not isinstance(p, int) or p < 1 for p in known_pages) or len(set(known_pages)) > 1:
        add('PAIRING_MISMATCH', 'Conflicting or invalid printed page identifiers; no images compared.',
            severity='FAIL', confidence=1., evidence='confirmed', remediation='repair_pairing')
        block['status'] = 'FAIL'
        return calibrate_source_result(result, profile, metadata=metadata)
    for name, path in (('generated', generated_path), ('source', source_path)):
        try:
            if path is None:
                raise ValueError('image path is not provided')
            result['metrics'][name] = measure_source_page(path, profile)
        except ImportError as exc:
            add('SOURCE_QC_DEPENDENCY_UNAVAILABLE', f'Optional source analysis dependency unavailable: {exc}', evidence='unassessed')
            return calibrate_source_result(result, profile, metadata=metadata)
        except (OSError, ValueError, TypeError) as exc:
            if name == 'source':
                add('SOURCE_UNAVAILABLE', f'Source comparison unavailable; output retained: {exc}', evidence='unassessed')
            else:
                add('INVALID_GENERATED', f'Cannot measure translated image: {exc}', severity='FAIL', evidence='confirmed', confidence=1.)
                block['status'] = 'FAIL'
            return calibrate_source_result(result, profile, metadata=metadata)
    source, generated = result['metrics']['source'], result['metrics']['generated']
    canvas_only = bool(source['ink_content_digest'] and source['ink_content_digest'] == generated['ink_content_digest'])
    block['identical_ink_with_canvas_changes'] = canvas_only
    confidence = min(source['confidence'], generated['confidence'], source['frame_confidence'], generated['frame_confidence'])
    tolerance = source['skew_tolerance'] + generated['skew_tolerance']
    sw, sh = source['size']
    gw, gh = generated['size']
    metric('aspect_difference', abs((gw/gh)/(sw/sh)-1), thresholds['aspect_warning'], 1.,
           'SOURCE_ASPECT_DRIFT', 'Canvas aspect differs; padding may help, but cannot repair internal reflow.',
           remediation='canvas_normalization_candidate', confirmed=True)
    if not source['normalized_bbox'] or not generated['normalized_bbox']:
        metric('content_presence', None, 0., .0, 'CONTENT_UNASSESSED', 'Insufficient detectable ink for source comparison.')
        add('CONTENT_UNASSESSED', 'An empty or unreadable raster cannot establish preservation.', evidence='unassessed')
        return calibrate_source_result(result, profile, metadata=metadata)
    if confidence < thresholds['min_confidence']:
        add('LOW_CONFIDENCE', 'Segmentation, resolution or skew is insufficient for a reliable verdict.', confidence=confidence, evidence='unassessed')
    sb, gb = source['bands']['body']['box'], generated['bands']['body']['box']
    if sb and gb:
        metric('relative_margins', max(abs(sb[i]-gb[i]) for i in (0, 2)), thresholds['margin_warning']+tolerance,
               confidence, 'SOURCE_MARGIN_DRIFT', 'Horizontal body margins differ in page-relative coordinates.', remediation='layout_review')
        metric('content_position', max(abs(sb[0]-gb[0]), abs(sb[1]-gb[1])), thresholds['position_warning']+tolerance,
               confidence, 'SOURCE_CONTENT_POSITION', 'Body origin moved; translated text length may explain reflow.', remediation='layout_review')
        metric('content_width', abs((sb[2]-sb[0])-(gb[2]-gb[0])), thresholds['width_warning'], confidence,
               'SOURCE_CONTENT_WIDTH', 'Relative body width differs.', remediation='layout_review')
    for name in ('header', 'footer'):
        sband, gband = source['bands'][name], generated['bands'][name]
        sbox, gbox = sband['box'], gband['box']
        c = min(sband['confidence'], gband['confidence'])
        value = _box_distance(sbox, gbox) if sbox and gbox else None
        metric(name+'_position', value, thresholds['header_footer_warning']+tolerance, c,
               'SOURCE_'+name.upper()+'_POSITION', f'{name.title()} candidate position differs from its corresponding source.',
               region=_pixel_box(gbox, generated), source_region=_pixel_box(sbox, source), remediation='layout_review')
        if value is None:
            add(name.upper()+'_UNASSESSED', f'Cannot locate both {name} candidates confidently.', evidence='unassessed')
        alignment = getattr(profile, name+'_alignment')
        page = metadata.get('page_number')
        if gbox and page is not None and alignment != 'unconstrained':
            cx = _center(gbox)[0]
            target = (.65 if page % 2 else .35) if alignment == 'mirrored' and profile.mirrored_layout else .5
            if gbox[2]-gbox[0] < .55:
                metric(name+'_alignment', abs(cx-target), .25, c, name.upper()+'_ALIGNMENT',
                       f'{name.title()} alignment reviewed using printed page parity.', region=_pixel_box(gbox, generated))
    st, gt = source['title_candidate'], generated['title_candidate']
    metric('title_position', abs(_center(st['box'])[1]-_center(gt['box'])[1]) if st and gt else None,
           thresholds['position_warning']+tolerance, min(st['confidence'], gt['confidence']) if st and gt else .0,
           'SOURCE_TITLE_POSITION', 'Isolated upper text region moved; its textual identity is not recognized.',
           region=_pixel_box(gt['box'], generated) if gt else None,
           source_region=_pixel_box(st['box'], source) if st else None, remediation='layout_review')
    metric('content_density', abs(source['ink_fraction']-generated['ink_fraction']), thresholds['density_warning'],
           confidence, 'SOURCE_DENSITY_DRIFT', 'Ink density differs; language length and stroke weight can legitimately change it.')
    unexplained_blank = 0.
    for gap in generated['blank_bands']:
        overlap = sum(max(0., min(gap[3], other[3])-max(gap[1], other[1])) for other in source['blank_bands'])
        unexplained_blank = max(unexplained_blank, gap[3]-gap[1]-overlap)
    metric('new_blank_band', unexplained_blank, thresholds['whitespace_warning'], confidence,
           'SOURCE_WHITESPACE_DRIFT', 'New blank span exceeds the source pattern; existing source whitespace is accepted.')
    for b in generated['edge_regions']:
        metric('edge_clearance', thresholds['edge_warning']-min(b[0], b[1], 1-b[2], 1-b[3]), 0.,
               generated['confidence'], 'EDGE_CONTENT', 'Detected ink enters the edge safety band; cropping or scan debris needs review.',
               region=_pixel_box(b, generated), remediation='inspect_clipping')
    available = set(range(len(generated['geometry_regions'])))
    for index, sg in enumerate(source['geometry_regions']):
        scores = []
        for j in available:
            gg = generated['geometry_regions'][j]
            score = _box_distance(sg['box'], gg['box'])
            score += .10 * abs((sg['box'][2]-sg['box'][0])-(gg['box'][2]-gg['box'][0]))
            scores.append((score, j))
        scores.sort()
        if not scores or scores[0][0] > .30:
            metric('geometry_presence_'+str(index+1), 1., 0., sg['confidence'], 'SOURCE_GEOMETRY_MISSING',
                   'No confident counterpart for a large connected line region; missing geometry is suspected.',
                   source_region=_pixel_box(sg['box'], source), remediation='inspect_geometry')
            continue
        score, j = scores[0]
        gg = generated['geometry_regions'][j]
        match_confidence = min(sg['confidence'], gg['confidence'])
        if len(scores) > 1 and scores[1][0]-score < .025:
            match_confidence = min(match_confidence, .5)
        available.remove(j)
        kwargs = {'region': _pixel_box(gg['box'], generated), 'source_region': _pixel_box(sg['box'], source)}
        metric('geometry_position_'+str(index+1), _box_distance(sg['box'], gg['box']), thresholds['position_warning']+tolerance,
               match_confidence, 'SOURCE_GEOMETRY_POSITION', 'Matched line-region position differs; correspondence is heuristic.',
               remediation='inspect_geometry', **kwargs)
        size_difference = max(abs((gg['box'][i+2]-gg['box'][i])/(sg['box'][i+2]-sg['box'][i])-1) for i in (0, 1))
        metric('geometry_size_'+str(index+1), size_difference, thresholds['geometry_size_warning'], match_confidence,
               'SOURCE_GEOMETRY_SIZE', 'Relative line-region size differs; no geometry correctness is inferred.', **kwargs)
        structure = sum(abs(a-b) for a, b in zip(sg['signature'], gg['signature'])) / 2
        metric('geometry_structure_'+str(index+1), structure, thresholds['geometry_structure_warning'], match_confidence,
               'SOURCE_GEOMETRY_STRUCTURE', 'Coarse stroke distribution differs; labels and exact incidence require manual review.', **kwargs)
    metric('geometry_count_difference', abs(len(source['geometry_regions'])-len(generated['geometry_regions'])), 0.,
           min(confidence, .65), 'GEOMETRY_COUNT_REVIEW', 'Candidate count is not a verified figure count.')
    for index, sf in enumerate(source['formula_candidates']):
        distance = min((_box_distance(sf['box'], gf['box']) for gf in generated['formula_candidates']), default=1.)
        metric('formula_region_'+str(index+1), distance, thresholds['position_warning'], .55,
               'FORMULA_REGION_MISSING', 'Standalone text/formula candidate moved or lacks a counterpart; identity unverified.',
               remediation='inspect_formula')
        counterpart = min(generated['formula_candidates'], key=lambda gf: _box_distance(sf['box'], gf['box']), default=None)
        size_change = None
        if counterpart is not None:
            size_change = max(abs((counterpart['box'][i+2]-counterpart['box'][i])/(sf['box'][i+2]-sf['box'][i])-1) for i in (0, 1))
        metric('formula_size_'+str(index+1), size_change, thresholds['geometry_size_warning'], .55,
               'FORMULA_REGION_SIZE', 'Standalone text/formula size changed; candidate identity is not verified.', remediation='inspect_formula')
    for gf in generated['formula_candidates']:
        b = gf['box']
        safe = _norm_box(profile.content_box, *profile.target_size)
        outside = max(safe[0]-b[0], safe[1]-b[1], b[2]-safe[2], b[3]-safe[3], 0.)
        metric('formula_outside_content', outside, 0., gf['confidence'], 'FORMULA_OUTSIDE_CONTENT',
               'Standalone text/formula candidate extends outside the configured content area; manual identification required.',
               remediation='inspect_formula')
        if any(min(b[2], g['box'][2]) > max(b[0], g['box'][0]) and min(b[3], g['box'][3]) > max(b[1], g['box'][1])
               for g in generated['geometry_regions']):
            add('FORMULA_GEOMETRY_OVERLAP', 'Unidentified standalone text overlaps a line region; inspect formula/figure placement.',
                confidence=.5, evidence='unassessed', remediation='inspect_formula')
    standard = metadata.get('canonical_header', profile.canonical_header)
    header = metadata.get('running_header')
    if metadata.get('trusted_header_text') is True and isinstance(standard, str) and isinstance(header, str):
        import unicodedata
        normalize = lambda text: ' '.join(unicodedata.normalize('NFC', text).split())
        different = normalize(standard) != normalize(header)
        metric('running_header_text_difference', float(different), 0., 1., 'RUNNING_HEADER_TEXT_DRIFT',
               'Trusted transcribed running header differs from the declared canonical wording.', confirmed=True, remediation='standardize_header')
        block['header_text_verification'] = 'WARNING' if different else 'PASS'
    else:
        add('RUNNING_HEADER_UNVERIFIED', 'No trusted transcription and canonical header pair; raster text is not compared.', evidence='unassessed')
    sample = None
    reference_typography = metadata.get('typography_reference')
    if profile.approved_sample:
        try:
            sample = measure_source_page(profile.approved_sample, profile)
            result['metrics']['sample'] = sample
            reference_typography = sample['typography']
        except (ValueError, OSError, ImportError) as exc:
            add('SAMPLE_UNAVAILABLE', f'Approved sample unavailable: {exc}', evidence='unassessed')
    if isinstance(reference_typography, dict):
        current = generated['typography']
        for name in ('glyph_height', 'line_spacing', 'header_height'):
            a, b = reference_typography.get(name), current.get(name)
            c = min(reference_typography.get('confidence', 0.), current['confidence'])
            value = abs(b/a-1) if isinstance(a, (int, float)) and a > 0 and b else None
            metric('typography_'+name, value, thresholds['typography_warning'], c,
                   'TYPOGRAPHY_'+name.upper(), 'Visual text-band proxy differs from the Vietnamese book reference; not an exact font size.')
    if sample:
        for name in ('header', 'footer'):
            a, b = sample['bands'][name]['box'], generated['bands'][name]['box']
            if a and b:
                sample_page = profile.sample_page_number
                page = metadata.get('page_number')
                if profile.mirrored_layout and getattr(profile, name+'_alignment') == 'mirrored':
                    if sample_page is None or page is None:
                        continue
                    if sample_page % 2 != page % 2:
                        a = [1-a[2], a[1], 1-a[0], a[3]]
                metric('sample_'+name+'_position', _box_distance(a, b), thresholds['header_footer_warning'],
                       min(sample['confidence'], generated['confidence']), 'SAMPLE_'+name.upper()+'_POSITION',
                       'Running-region position differs from the approved sample after explicit parity handling.')
    block['measured_status'] = result['status']
    block['status'] = ('FAIL' if result['status'] == 'FAIL' else
                       'NEEDS_RELAYOUT' if any(f['requires_relayout'] for f in result['findings']) else 'REVIEW_REQUIRED')
    block['review_reasons'] = ['Raster analysis cannot verify formula contents, point labels or exact figure count.',
                               'Translation reflow may legitimately change positions, line breaks and density.']
    return calibrate_source_result(result, profile, metadata=metadata)



def calibrate_source_result(result, profile, *, metadata=None):
    """Add independent dimensions to a source-aware report, including cached QC.

    Legacy status, metric values and finding codes are retained. Trusted local
    annotations can adjudicate specific edge contacts; no location or size alone
    makes a figure decorative. Missing annotation leaves a conservative risk.
    """
    import copy
    calibrated = copy.deepcopy(result)
    metadata = metadata or {}
    metrics = calibrated.get('metrics', {})
    source, generated = metrics.get('source', {}), metrics.get('generated', {})
    findings = calibrated.setdefault('findings', [])
    minimum = profile.source_thresholds['min_confidence']
    covered = bool(source and generated)
    supported = (covered and min(source.get('confidence', 0), generated.get('confidence', 0),
                                 source.get('frame_confidence', 0), generated.get('frame_confidence', 0)) >= minimum)
    # A declared cover with almost solid dark-pixel occupancy is outside the
    # white-paper segmentation model. Abstain on diagram identity, not PASS.
    cover = (metadata.get('page_type') == 'cover' and covered
             and min(source.get('ink_fraction', 0), generated.get('ink_fraction', 0)) > .85)
    review_reasons = []
    if cover:
        review_reasons.append('Declared cover has broad dark/colored background; line components are not verified content diagrams.')
    content_risk = 'UNVERIFIED'
    blank_evidence = {}
    s, g = source.get('content_evidence', {}), generated.get('content_evidence', {})
    resolution = covered and min(source.get('analysis_size', [0, 0]) + generated.get('analysis_size', [0, 0])) >= 150
    if resolution and s and g:
        source_blank = (s.get('body_ink_fraction') is not None and s['body_ink_fraction'] <= .0003
                        and s.get('substantial_body_components') == 0
                        and s.get('body_text_lines') == 0 and s.get('body_geometry_candidates') == 0
                        and source.get('ink_fraction', 1) <= .02)
        generated_blank = (g.get('body_ink_fraction') is not None and g['body_ink_fraction'] <= .0003
                           and g.get('substantial_body_components') == 0
                           and g.get('body_text_lines') == 0 and g.get('body_geometry_candidates') == 0)
        box = g.get('substantial_body_box')
        large_new_body = (g.get('body_ink_fraction', 0) >= .005
                          and g.get('body_text_lines', 0) >= 2
                          and g.get('substantial_body_components', 0) >= 8
                          and box is not None and box[2]-box[0] >= .20 and box[3]-box[1] >= .04)
        blank_evidence = {'source_near_blank_body': source_blank,
                          'generated_near_blank_body': generated_blank,
                          'large_new_body': bool(large_new_body),
                          'confidence': .90 if source_blank and large_new_body else .75 if source_blank else 0.,
                          'scope': 'body-presence only; outer decorations and semantic correctness unverified'}
        if (source_blank and large_new_body and generated.get('confidence', 0) >= minimum
                and generated.get('frame_confidence', 0) >= minimum
                and (source.get('frame_confidence', 0) >= minimum
                     or source.get('page_frame') == [0, 0] + source.get('size', []))):
            if not any(f.get('code') == 'UNEXPECTED_CONTENT_ADDITION' for f in findings):
                findings.append({'code': 'UNEXPECTED_CONTENT_ADDITION', 'severity': 'WARNING',
                                 'message': 'Near-blank source body has substantial new text-like content in the translation; verify before publication.',
                                 'confidence': .90, 'region': _pixel_box(box, generated),
                                 'source_region': None, 'evidence': 'suspected',
                                 'remediation': 'verify_content_before_publication', 'requires_relayout': True})
                if calibrated.get('status') != 'FAIL':
                    calibrated['status'] = 'WARNING'
            content_risk = 'HIGH_RISK'
        elif source_blank and generated_blank:
            content_risk = 'NONE_DETECTED'
    edge_assessments = []
    annotations = metadata.get('edge_verification', [])
    if not isinstance(annotations, list):
        annotations = []
    for box in generated.get('edge_regions', []):
        if min(box[0], box[1], 1-box[2], 1-box[3]) >= profile.source_thresholds['edge_warning']:
            continue
        classification, confidence = 'CONTENT_EDGE_RISK', generated.get('confidence', 0)
        reason = 'Ink enters the safety band; neither clipping nor semantic identity is proven.'
        kind = ('line_geometry_candidate' if any(_boxes_overlap(box, item['box']) for item in generated.get('geometry_regions', []))
                else 'text_or_formula_candidate' if any(_boxes_overlap(box, b) for b in generated.get('text_line_regions', []))
                else 'header_footer_candidate' if box[3] <= .18 or box[1] >= .92 else 'unknown')
        if confidence < minimum or cover:
            classification = 'INSUFFICIENT_EVIDENCE'
            reason = 'Segmentation is unreliable or the declared cover is outside the white-paper model.'
        # A local verified annotation applies only to the matching connected
        # region. Unannotated figures/text at the same page edge remain risks.
        for annotation in annotations:
            if not isinstance(annotation, dict) or annotation.get('verified') is not True:
                continue
            region = annotation.get('region')
            label = annotation.get('classification')
            basis = annotation.get('basis')
            if (label not in ('DECORATIVE_EDGE', 'SCAN_BORDER_NOISE')
                    or not isinstance(basis, str) or not basis.strip()
                    or not isinstance(region, (list, tuple)) or len(region) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in region)
                    or not region[0] < region[2] or not region[1] < region[3]):
                continue
            if max(abs(a-b) for a, b in zip(box, region)) <= .001:
                classification, confidence, reason = label, .95, basis
                break
        edge_assessments.append({'region': list(box), 'pixel_region': _pixel_box(box, generated),
                                 'classification': classification, 'confidence': confidence,
                                 'content_kind': kind, 'reason': reason})
    layout_findings, evidence_findings, content_findings = [], [], []
    uncertain_layout = not supported or cover
    uncertainty_codes = {'SOURCE_UNAVAILABLE', 'SOURCE_QC_DEPENDENCY_UNAVAILABLE', 'CONTENT_UNASSESSED',
                         'LOW_CONFIDENCE', 'HEADER_UNASSESSED', 'FOOTER_UNASSESSED'}
    for finding in findings:
        code = finding.get('code', '')
        if code == 'UNEXPECTED_CONTENT_ADDITION':
            content_findings.append(finding)
            continue
        if code == 'EDGE_CONTENT':
            continue
        if cover and code.startswith('SOURCE_GEOMETRY_'):
            evidence_findings.append(dict(finding, interpretation='DECORATIVE_GEOMETRY_UNASSESSED',
                                          disposition='Outside white-paper diagram-identification scope; raw finding retained.'))
            continue
        if finding.get('evidence') == 'unassessed' or code in uncertainty_codes:
            evidence_findings.append(finding)
            if code in uncertainty_codes:
                uncertain_layout = True
        else:
            layout_findings.append(finding)
    for assessment in edge_assessments:
        if assessment['classification'] == 'CONTENT_EDGE_RISK':
            layout_findings.append({'code': 'CONTENT_EDGE_RISK', 'severity': 'WARNING',
                                    'region': assessment['pixel_region'], 'evidence': 'suspected',
                                    'confidence': assessment['confidence'], 'message': assessment['reason']})
        elif assessment['classification'] == 'INSUFFICIENT_EVIDENCE':
            uncertain_layout = True
    if any(f.get('severity') == 'FAIL' for f in findings):
        layout_status = 'FAIL'
    elif layout_findings:
        layout_status = 'WARNING'
    elif uncertain_layout:
        layout_status = 'REVIEW_REQUIRED'
    else:
        layout_status = 'PASS'
    if content_risk != 'HIGH_RISK' and any(f.get('code', '').startswith(('SOURCE_GEOMETRY_', 'FORMULA_'))
                                          for f in layout_findings):
        content_risk = 'SUSPECTED'
    evidence_status = ('INSUFFICIENT' if not supported or cover or not source.get('normalized_bbox') or not generated.get('normalized_bbox')
                       else 'PARTIAL' if evidence_findings or any(m.get('status') == 'REVIEW_REQUIRED' for m in calibrated.get('source_aware', {}).get('metrics', []))
                       else 'VERIFIED')
    calibrated.update(layout_status=layout_status, evidence_status=evidence_status,
                      content_risk=content_risk, publication_review_required=content_risk == 'HIGH_RISK',
                      layout_findings=layout_findings, evidence_findings=evidence_findings,
                      content_findings=content_findings,
                      edge_assessments=edge_assessments, content_addition_evidence=blank_evidence,
                      calibration_notes=review_reasons,
                      status_scope='Additive raster-layout dimensions; legacy status unchanged except newly detected content risk. VERIFIED never certifies translation or mathematics.')
    return calibrated


def _boxes_overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])
