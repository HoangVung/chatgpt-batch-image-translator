"""Validated, opt-in configuration for independent raster page layout checks."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

DEFAULT_THRESHOLDS = {
    "dimension_warning": 0.05,
    "aspect_warning": 0.025,
    "aspect_fail": 0.15,
    "margin_warning": 0.04,
    "sample_margin_warning": 0.04,
    "edge_warning": 0.015,
    "edge_fail": 0.002,
    "min_ink_fraction": 0.001,
    "ink_difference_warning": 0.12,
    "whitespace_band_warning": 0.18,
    "title_height_warning": 0.025,
    "header_footer_occupancy_warning": 0.02,
}


# Provisional visual warning thresholds; calibration needs real source/VN pairs.
DEFAULT_SOURCE_THRESHOLDS = {
    "aspect_warning": 0.04,
    "margin_warning": 0.06,
    "position_warning": 0.06,
    "width_warning": 0.10,
    "header_footer_warning": 0.045,
    "density_warning": 0.10,
    "whitespace_warning": 0.16,
    "geometry_size_warning": 0.25,
    "geometry_structure_warning": 0.30,
    "typography_warning": 0.35,
    "edge_warning": 0.01,
    "min_confidence": 0.70,
}


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _coordinates(value: Any, name: str, count: int) -> tuple[int, ...]:
    if not isinstance(value, (tuple, list)) or len(value) != count:
        raise ValueError(f"{name} must contain {count} integers")
    return tuple(_integer(item, name) for item in value)


@dataclass(frozen=True)
class LayoutProfile:
    enabled: bool = False
    qc_enabled: bool = True
    normalize_enabled: bool = True
    target_size: tuple[int, int] = (1600, 2400)
    margins: tuple[int, int, int, int] = (100, 100, 100, 140)
    content_region: tuple[int, int, int, int] | None = None
    page_number_region: tuple[int, int, int, int] | None = None
    approved_sample: Path | None = None
    output_dir: Path = Path("layout_results")
    annotate: bool = False
    thresholds: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    max_pixels: int = 40_000_000
    ink_luma_threshold: int = 225
    source_aware_enabled: bool = False
    source_thresholds: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SOURCE_THRESHOLDS))
    mirrored_layout: bool = True
    header_alignment: str = "mirrored"
    footer_alignment: str = "mirrored"
    canonical_header: str | None = None
    sample_page_number: int | None = None

    def __post_init__(self) -> None:
        for name in ("enabled", "qc_enabled", "normalize_enabled", "annotate",
                     "source_aware_enabled", "mirrored_layout"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        size = _coordinates(self.target_size, "target_size", 2)
        if not all(size):
            raise ValueError("target_size dimensions must be positive")
        object.__setattr__(self, "target_size", size)
        max_pixels = _integer(self.max_pixels, "max_pixels", minimum=1)
        if max_pixels > 60_000_000 or size[0] * size[1] > max_pixels:
            raise ValueError("target_size exceeds max_pixels (absolute limit: 60000000)")
        margins = _coordinates(self.margins, "margins", 4)
        if margins[0] + margins[2] >= size[0] or margins[1] + margins[3] >= size[1]:
            raise ValueError("margins must leave a positive content area")
        object.__setattr__(self, "margins", margins)
        for name in ("content_region", "page_number_region"):
            value = getattr(self, name)
            if value is not None:
                region = _coordinates(value, name, 4)
                x0, y0, x1, y1 = region
                if not (x0 < x1 <= size[0] and y0 < y1 <= size[1]):
                    raise ValueError(f"{name} must be a positive rectangle inside target_size")
                if name == "content_region":
                    allowed = (margins[0], margins[1], size[0] - margins[2], size[1] - margins[3])
                    if not (allowed[0] <= x0 < x1 <= allowed[2]
                            and allowed[1] <= y0 < y1 <= allowed[3]):
                        raise ValueError("content_region must lie inside the configured margins")
                object.__setattr__(self, name, region)
        if self.page_number_region is not None:
            if self.page_number_region[1] < self.content_box[3]:
                raise ValueError("page_number_region must be in the footer below content_region")
        if not isinstance(self.thresholds, Mapping):
            raise ValueError("thresholds must be an object")
        unknown = set(self.thresholds) - set(DEFAULT_THRESHOLDS)
        if unknown:
            raise ValueError(f"unknown thresholds: {', '.join(sorted(unknown))}")
        thresholds = dict(DEFAULT_THRESHOLDS)
        for name, value in self.thresholds.items():
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"threshold {name} must be a finite number between 0 and 1")
            thresholds[name] = float(value)
        if thresholds["aspect_fail"] < thresholds["aspect_warning"]:
            raise ValueError("aspect_fail must be >= aspect_warning")
        if thresholds["edge_fail"] > thresholds["edge_warning"]:
            raise ValueError("edge_fail must be <= edge_warning")
        object.__setattr__(self, "thresholds", thresholds)
        if not isinstance(self.source_thresholds, Mapping):
            raise ValueError("source_thresholds must be an object")
        unknown = set(self.source_thresholds) - set(DEFAULT_SOURCE_THRESHOLDS)
        if unknown:
            raise ValueError(f"unknown source thresholds: {', '.join(sorted(unknown))}")
        source_thresholds = dict(DEFAULT_SOURCE_THRESHOLDS)
        for name, value in self.source_thresholds.items():
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"source threshold {name} must be a finite number between 0 and 1")
            source_thresholds[name] = float(value)
        object.__setattr__(self, "source_thresholds", source_thresholds)
        for name in ("header_alignment", "footer_alignment"):
            if getattr(self, name) not in ("mirrored", "center", "unconstrained"):
                raise ValueError(f"{name} must be mirrored, center or unconstrained")
        if self.canonical_header is not None:
            if not isinstance(self.canonical_header, str) or not self.canonical_header.strip():
                raise ValueError("canonical_header must be a non-empty string or null")
        if self.sample_page_number is not None:
            _integer(self.sample_page_number, "sample_page_number", minimum=1)
        _integer(self.ink_luma_threshold, "ink_luma_threshold", minimum=1)
        if self.ink_luma_threshold > 254:
            raise ValueError("ink_luma_threshold must be <= 254")
        for name in ("approved_sample", "output_dir"):
            value = getattr(self, name)
            if value is None and name == "approved_sample":
                continue
            if not isinstance(value, (str, Path)) or not str(value).strip():
                raise ValueError(f"{name} must be a non-empty path")
            object.__setattr__(self, name, Path(value))

    @property
    def content_box(self) -> tuple[int, int, int, int]:
        if self.content_region is not None:
            return self.content_region
        left, top, right, bottom = self.margins
        width, height = self.target_size
        return left, top, width - right, height - bottom


def load_profile(path: str | Path) -> LayoutProfile:
    """Load JSON; resolve image/output paths relative to the profile file."""
    profile_path = Path(path).resolve()
    data = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("layout profile must be a JSON object")
    unknown = set(data) - set(LayoutProfile.__dataclass_fields__)
    if unknown:
        raise ValueError(f"unknown profile fields: {', '.join(sorted(unknown))}")
    data.setdefault("output_dir", "layout_results")
    for name in ("approved_sample", "output_dir"):
        value = data.get(name)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty path string")
            candidate = Path(value)
            data[name] = candidate if candidate.is_absolute() else profile_path.parent / candidate
    return LayoutProfile(**data)
