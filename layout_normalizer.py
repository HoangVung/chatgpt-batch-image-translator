"""Pixel-preserving canvas padding and translation; never resize or crop page pixels."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from layout_profile import LayoutProfile
from layout_qc import measure_image


def normalize_image(
    image_path: str | Path,
    profile: LayoutProfile,
    qc_result: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Image.Image | None]:
    """Return a report and an in-memory derivative, without writing any file.

    The caller owns/closes a returned image and controls feature flags. RGB/RGBA
    source pixels are copied exactly, including alpha; no mask or resampling is
    used. Only ICC profile and DPI metadata are carried to the derivative.
    NEEDS_RELAYOUT and ERROR never return an image to publish.
    """
    result: dict[str, Any] = {
        "status": "ERROR", "reasons": [], "input_size": None,
        "target_size": list(profile.target_size), "offset": None,
        "content_bbox": None, "target_content_bbox": None,
    }

    def needs_relayout(*reasons: str) -> tuple[dict[str, Any], None]:
        result.update(status="NEEDS_RELAYOUT", reasons=list(reasons))
        return result, None

    try:
        with Image.open(image_path) as source:
            width, height = source.size
            result["input_size"] = [width, height]
            if width * height > profile.max_pixels:
                raise ValueError("image exceeds max_pixels")
            if getattr(source, "n_frames", 1) != 1:
                return needs_relayout("multiple_frames_require_review")
            if source.getexif().get(274, 1) != 1:
                return needs_relayout("exif_orientation_requires_review")
            if source.mode not in ("RGB", "RGBA"):
                return needs_relayout("image_mode_requires_conversion_review")
            # A color-key transparency on RGB cannot be carried to a white canvas
            # without making its added margin transparent too.
            if "transparency" in source.info:
                return needs_relayout("color_key_transparency_requires_review")
            source.load()
            metrics = measure_image(image_path, profile)
            if metrics["size"] != [width, height]:
                raise ValueError("image dimensions changed during measurement")
            bbox = metrics["content_bbox"]
            result["content_bbox"] = bbox
            if qc_result is not None:
                if not isinstance(qc_result, Mapping):
                    raise ValueError("qc_result must be a mapping")
                invalid = [str(finding.get("code", ""))
                           for finding in qc_result.get("findings", [])
                           if str(finding.get("code", "")).startswith("INVALID_")]
                if invalid:
                    result.update(status="ERROR", reasons=["qc_invalid_input:" + code for code in invalid],
                                  error="QC could not validate a required input image")
                    return result, None
                blockers = [
                    "qc_requires_relayout:" + str(finding.get("code", "unknown"))
                    for finding in qc_result.get("findings", [])
                    if finding.get("requires_relayout")
                ]
                if blockers:
                    return needs_relayout(*blockers)
            if bbox is None:
                return needs_relayout("no_detectable_content_requires_review")
            if profile.page_number_region is not None:
                return needs_relayout("page_number_template_requires_review")
            target_width, target_height = profile.target_size
            if width > target_width or height > target_height:
                return needs_relayout("source_raster_exceeds_target_canvas")
            left, top, right, bottom = profile.content_box
            bx0, by0, bx1, by1 = bbox
            # Intersect offsets that retain the ENTIRE source raster with offsets
            # that keep its detected content within the configured content box.
            min_x, max_x = max(0, left - bx0), min(target_width - width, right - bx1)
            min_y, max_y = max(0, top - by0), min(target_height - height, bottom - by1)
            if min_x > max_x or min_y > max_y:
                return needs_relayout("content_cannot_fit_without_editing_source")
            desired_x = (left + right - bx0 - bx1) // 2
            desired_y = (top + bottom - by0 - by1) // 2
            offset_x = max(min_x, min(max_x, desired_x))
            offset_y = max(min_y, min(max_y, desired_y))
            result["offset"] = [offset_x, offset_y]
            result["target_content_bbox"] = [
                bx0 + offset_x, by0 + offset_y, bx1 + offset_x, by1 + offset_y,
            ]
            color = (255, 255, 255, 255) if source.mode == "RGBA" else (255, 255, 255)
            canvas = Image.new(source.mode, profile.target_size, color)
            # Omitting a mask preserves all source RGBA values, even hidden RGB.
            canvas.paste(source, (offset_x, offset_y))
            canvas.info.update({key: source.info[key] for key in ("icc_profile", "dpi")
                                if key in source.info})
            unchanged = source.size == profile.target_size and offset_x == offset_y == 0
            result["status"] = "UNCHANGED" if unchanged else "NORMALIZED"
            result["reasons"] = ["source_pixels_preserved"]
            return result, canvas
    except Exception as exc:
        result.update(status="ERROR", reasons=["normalization_error"], error=str(exc))
        return result, None