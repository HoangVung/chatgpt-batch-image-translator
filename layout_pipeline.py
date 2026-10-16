"""Offline layout reports and an exception-isolated, opt-in worker adapter."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from layout_profile import LayoutProfile, load_profile
from layout_qc import check_layout
from progress_utils import read_latest_progress


def _log(logger, message):
    try:
        logger(message)
    except Exception:
        # A closed GUI log pipe must not retry an already successful translation.
        pass


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_reports(directory, report):
    # directory is exclusively created for this invocation, never an input path.
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    with (directory / "report.json").open("x", encoding="utf-8") as handle:
        handle.write(payload + "\n")
    qc = report.get("qc", {})
    normalization = report.get("normalization", {})
    row = {
        "source": report["source"],
        "generated": report["generated"],
        "processing_status": report["processing_status"],
        "qc_status": qc.get("status", "SKIPPED"),
        "normalization_status": normalization.get("status", "SKIPPED"),
        "findings": "|".join(f["code"] for f in qc.get("findings", [])),
        "reasons": "|".join(normalization.get("reasons", [])),
        "original_sha256": report.get("original_sha256", ""),
        "normalized": report.get("normalized", ""),
        "error": report.get("error", ""),
        "page_number": report.get("metadata", {}).get("page_number", ""),
        "source_aware_status": qc.get("source_aware", {}).get("status", "SKIPPED"),
        "remediation": "|".join(sorted({str(f.get("remediation", "")) for f in qc.get("findings", []) if f.get("remediation")})),
    }
    with (directory / "report.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _annotate(snapshot, directory, qc):
    regions = [finding for finding in qc.get("findings", []) if finding.get("region")]
    if not regions:
        return None
    with Image.open(snapshot) as source:
        if source.mode == "RGBA":
            canvas = Image.new("RGBA", source.size, "white")
            canvas.alpha_composite(source)
            annotated = canvas.convert("RGB")
        else:
            annotated = source.convert("RGB")
    draw = ImageDraw.Draw(annotated)
    for finding in regions:
        left, top, right, bottom = finding["region"]
        draw.rectangle((left, top, max(left, right - 1), max(top, bottom - 1)),
                       outline="red" if finding["severity"] == "FAIL" else "orange",
                       width=max(1, min(annotated.size) // 250))
    folder = directory / "annotations"
    folder.mkdir()
    path = folder / "suspects.png"
    with path.open("xb") as handle:
        annotated.save(handle, format="PNG")
    annotated.close()
    return str(path)


def _check_page(source, generated, profile, metadata):
    if profile.source_aware_enabled:
        return check_layout(source, generated, profile, metadata=metadata)
    return check_layout(source, generated, profile)


def _source_visuals(report, directory, snapshot, qc):
    """Compare contained images with uniform per-image scaling; never warp pixels."""
    cell_width, cell_height = 640, 900
    gap, top, bottom = 24, 42, 94
    base = Image.new("RGB", (cell_width * 2 + gap * 3, cell_height + top + bottom), "#e8e8e8")
    draw = ImageDraw.Draw(base)
    transforms = {}
    sources = [("SOURCE", report.get("source_copy"), gap),
               ("TRANSLATED", str(snapshot), cell_width + gap * 2)]
    for label, path, cell_x in sources:
        draw.text((cell_x, 12), label, fill="black")
        draw.rectangle((cell_x, top, cell_x + cell_width, top + cell_height), fill="white")
        if not path:
            draw.text((cell_x + 20, top + 20), "Source unavailable - QC unverified; continuing", fill="#315a9a")
            continue
        try:
            with Image.open(path) as raw:
                rgba = raw.convert("RGBA")
                paper = Image.new("RGBA", raw.size, "white")
                paper.alpha_composite(rgba)
                page = paper.convert("RGB")
                scale = min(cell_width / page.width, cell_height / page.height)
                size = (max(1, round(page.width * scale)), max(1, round(page.height * scale)))
                resized = page.resize(size, Image.Resampling.LANCZOS)
                x = cell_x + (cell_width - size[0]) // 2
                y = top + (cell_height - size[1]) // 2
                base.paste(resized, (x, y))
                # Use actual rounded dimensions to map both coordinates accurately.
                transforms[label] = (x, y, size[0] / page.width, size[1] / page.height)
                rgba.close()
                paper.close()
                page.close()
                resized.close()
        except (OSError, ValueError):
            draw.text((cell_x + 20, top + 20), "Image unavailable - QC unverified; continuing", fill="#315a9a")
    footer = top + cell_height + 12
    draw.text((gap, footer), "Uniform contain scaling; aspect ratios preserved. Coordinates are relative to each page.", fill="black")
    colors = {"confirmed": "#c62727", "suspected": "#b77500", "unassessed": "#315a9a"}
    draw.text((gap, footer + 21), "Red: confirmed deviation   Amber: suspected   Blue: insufficient evidence", fill="black")
    draw.text((gap, footer + 42), "Raster QC does not verify mathematical content, diagram labels, or translation accuracy.", fill="black")
    comparison = directory / "comparison.png"
    with comparison.open("xb") as handle:
        base.save(handle, format="PNG")
    overlay = base.copy()
    marked = ImageDraw.Draw(overlay)
    for finding in qc.get("findings", []):
        evidence = finding.get("evidence", "suspected")
        color = colors.get(evidence, colors["unassessed"])
        for label, field in (("SOURCE", "source_region"), ("TRANSLATED", "region")):
            box = finding.get(field)
            transform = transforms.get(label)
            if not box or len(box) != 4 or transform is None:
                continue
            x, y, sx, sy = transform
            coords = (x + box[0] * sx, y + box[1] * sy,
                      x + box[2] * sx, y + box[3] * sy)
            if coords[2] <= coords[0] or coords[3] <= coords[1]:
                continue
            marked.rectangle(coords, outline=color, width=3)
            marked.text((coords[0] + 3, max(top, coords[1] - 12)), finding["code"], fill=color)
    annotation = directory / "evidence-overlay.png"
    with annotation.open("xb") as handle:
        overlay.save(handle, format="PNG")
    base.close()
    overlay.close()
    return {"comparison": str(comparison), "evidence_overlay": str(annotation)}


def process_page(source, generated, profile: LayoutProfile, *, logger=print, metadata=None):
    """Never write to either input. Each run has a fresh, exclusive directory."""
    report = {
        "schema_version": 1,
        "source": str(Path(source).resolve()) if source is not None else "",
        "generated": str(Path(generated).resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_status": "SKIPPED",
        "qc": {"status": "SKIPPED", "findings": []},
        "normalization": {"status": "SKIPPED", "reasons": []},
    }
    if metadata is not None:
        report["metadata"] = dict(metadata)
    if profile.source_aware_enabled:
        # REVIEW_REQUIRED describes measurement uncertainty, never a pause,
        # approval request or instruction to rerun the provider workflow.
        report["automation"] = {
            "mode": "unattended", "blocks_batch": False,
            "manual_action_required": False, "next_action": "continue",
            "uncertain_result_policy": "retain_original_and_record_findings",
            "automatic_correction": "canvas_only_when_pixel_preserving",
        }
    if not profile.enabled:
        return report

    directory = None
    try:
        root = profile.output_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        directory = root / ("page-" + uuid4().hex)
        directory.mkdir()  # No exist_ok: never reuse/overwrite a previous run.
        report["run_dir"] = str(directory)
        report["profile"] = asdict(profile)
        original_dir = directory / "original"
        original_dir.mkdir()
        snapshot = original_dir / ("chatgpt" + Path(generated).suffix.lower())
        # Keep a byte-exact copy, including original format and metadata.
        with Path(generated).open("rb") as src, snapshot.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        report["original_copy"] = str(snapshot)
        report["original_sha256"] = _sha256(snapshot)
        if _sha256(generated) != report["original_sha256"]:
            raise ValueError("Generated image changed while making the snapshot")
        qc_source = source
        if profile.source_aware_enabled and profile.qc_enabled:
            source_path = Path(source) if source is not None else None
            if source_path is not None and source_path.is_file():
                source_snapshot = original_dir / ("source" + source_path.suffix.lower())
                with source_path.open("rb") as src, source_snapshot.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                report["source_copy"] = str(source_snapshot)
                report["source_sha256"] = _sha256(source_snapshot)
                if _sha256(source_path) != report["source_sha256"]:
                    raise ValueError("Source image changed while making the snapshot")
                qc_source = source_snapshot
            elif qc_source is None:
                qc_source = directory / "source-unavailable"
        qc = _check_page(qc_source, snapshot, profile, metadata)
        report["qc"] = qc
        if profile.source_aware_enabled and profile.qc_enabled:
            # Additive evidence only; failures and HIGH_RISK never escape to worker.
            try:
                from layout_regions import compare_regions
                report["region_qc"] = compare_regions(qc, profile, metadata=metadata)
                report["qc_accepted"] = report["region_qc"]["qc_accepted"]
            except Exception as exc:
                report["region_qc"] = {"status": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}",
                                       "blocks_batch": False, "next_action": "continue"}
                report["qc_accepted"] = False
        invalid = [f for f in qc.get("findings", []) if f["code"].startswith("INVALID_")]
        if invalid:
            raise ValueError("; ".join(f["code"] + ": " + f["message"] for f in invalid))
        if profile.qc_enabled:
            if not profile.source_aware_enabled:
                report["source_sha256"] = _sha256(source)
            if profile.approved_sample:
                if profile.source_aware_enabled:
                    try:
                        report["sample_sha256"] = _sha256(profile.approved_sample)
                    except OSError as exc:
                        report["sample_hash_error"] = f"{type(exc).__name__}: {exc}"
                else:
                    report["sample_sha256"] = _sha256(profile.approved_sample)
        if profile.normalize_enabled:
            from layout_normalizer import normalize_image
            result, image = normalize_image(snapshot, profile, qc)
            report["normalization"] = result
            if profile.source_aware_enabled and result.get("status") == "NEEDS_RELAYOUT":
                source_aware = qc.setdefault("source_aware", {})
                source_aware.setdefault("measured_status", qc.get("status", "WARNING"))
                source_aware["status"] = "NEEDS_RELAYOUT"
                source_aware["remediation_status"] = "NEEDS_RELAYOUT"
            if image is not None:
                try:
                    normalized_dir = directory / "normalized"
                    normalized_dir.mkdir()
                    normalized = normalized_dir / "page.png"
                    image_metadata = {key: image.info[key] for key in ("icc_profile", "dpi")
                                      if key in image.info}
                    temporary = normalized.with_suffix(".png.part")
                    with temporary.open("xb") as handle:
                        image.save(handle, format="PNG", **image_metadata)
                    temporary.replace(normalized)
                    report["normalized"] = str(normalized)
                    report["normalized_sha256"] = _sha256(normalized)
                    if profile.qc_enabled:
                        report["normalized_qc"] = _check_page(qc_source, normalized, profile, metadata)
                finally:
                    image.close()
        if profile.annotate:
            # Invalid images have no generated metrics and must not be reopened.
            if qc.get("metrics", {}).get("generated"):
                report["annotation"] = _annotate(snapshot, directory, qc)
        if profile.source_aware_enabled and profile.qc_enabled:
            report.update(_source_visuals(report, directory, snapshot, qc))
        report["processing_status"] = "COMPLETED"
        if report["normalization"]["status"] == "ERROR":
            report["processing_status"] = "ERROR"
            report["error"] = report["normalization"].get("error", "Normalization error")
    except Exception as exc:
        report["processing_status"] = "ERROR"
        report["error"] = f"{type(exc).__name__}: {exc}"

    if directory is not None:
        try:
            _write_reports(directory, report)
        except Exception as exc:
            report["processing_status"] = "ERROR"
            report["report_error"] = f"{type(exc).__name__}: {exc}"
            _log(logger, f"[layout] Cannot write report: {report['report_error']}")
    if report["processing_status"] == "ERROR":
        _log(logger, f"[layout] Post-processing error; downloaded image retained: "
                     f"{report.get('error', report.get('report_error', 'unknown'))}")
    else:
        _log(logger, f"[layout] QC={report['qc']['status']}; "
                     f"normalize={report['normalization']['status']}; {directory}")
    return report


def process_download_safely(source, generated, profile_path, *, logger=print):
    """Worker boundary: even invalid configuration/logging cannot escape."""
    try:
        profile = load_profile(profile_path)
        if profile.source_aware_enabled:
            # The worker supplies the exact source of this download. A manifest
            # and printed page number are optional, not prerequisites to QC.
            return process_page(source, generated, profile, logger=logger,
                                metadata={"pairing_method": "worker",
                                          "pairing_basis": "source_used_for_this_download"})
        return process_page(source, generated, profile, logger=logger)
    except Exception as exc:
        _log(logger, f"[layout] Post-processing unavailable; downloaded image retained "
                     f"({type(exc).__name__}: {exc})")
        return {"processing_status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def _child(folder, name):
    # progress.csv is data. Refuse absolute/traversing or symlink escape paths.
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError(f"Expected a filename in progress.csv: {name!r}")
    root = Path(folder).resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise ValueError(f"Image path escapes its input folder: {name!r}")
    return path


def _exit_code(report):
    if report["processing_status"] == "ERROR":
        return 2
    if report.get("normalization", {}).get("status") == "NEEDS_RELAYOUT":
        return 1
    statuses = [report.get("qc", {}).get("status"),
                report.get("normalized_qc", {}).get("status")]
    return 1 if any(status in ("WARNING", "FAIL") for status in statuses) else 0


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def _page_number(value, label="page number"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _filename_page(path, *, strict=False):
    numbers = re.findall(r"[0-9]+", Path(path).stem)
    if len(numbers) != 1:
        if strict:
            raise ValueError(f"Ambiguous or absent page number in {Path(path).name!r}; use a manifest")
        return None
    return _page_number(int(numbers[0]), f"page number in {Path(path).name}")


def collect_directory_pairs(source_dir, generated_dir):
    """Pair explicit single-number filenames; never silently choose a duplicate."""
    indexed = []
    for folder in (source_dir, generated_dir):
        root = Path(folder)
        if not root.is_dir():
            raise ValueError(f"Image directory does not exist: {root}")
        pages = {}
        for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            page = _filename_page(path, strict=True)
            if page in pages:
                raise ValueError(f"Duplicate page {page} in {root}: {pages[page].name}, {path.name}")
            pages[page] = path.resolve()
        indexed.append(pages)
    source_pages, generated_pages = indexed
    if not source_pages and not generated_pages:
        raise ValueError("No images found in the selected directories")
    return [{"source": source_pages.get(page), "generated": generated_pages.get(page),
             "metadata": {"page_number": page, "source_page_number": page,
                          "generated_page_number": page, "pairing_method": "filename"}}
            for page in sorted(source_pages.keys() | generated_pages.keys())]


def load_manifest(path):
    """Explicit printed page numbers override storage filename numbering."""
    manifest = Path(path).resolve()
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if (not isinstance(data, dict) or type(data.get("version", 1)) is not int
            or data.get("version", 1) != 1):
        raise ValueError("Manifest must be an object with version 1")
    rows = data.get("pages")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Manifest pages must be a non-empty list")
    def image_path(value, label):
        if value is None and label == "source":
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Manifest {label} must be a non-empty path string")
        candidate = Path(value)
        return candidate.resolve() if candidate.is_absolute() else (manifest.parent / candidate).resolve()
    pairs, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Every manifest page must be an object")
        page = _page_number(row.get("page", row.get("page_number")))
        if "page" in row and "page_number" in row and row["page"] != row["page_number"]:
            raise ValueError("Manifest page and page_number disagree")
        if page in seen:
            raise ValueError(f"Duplicate page {page} in manifest")
        seen.add(page)
        metadata = {"page_number": page, "pairing_method": "manifest"}
        for name in ("source_page_number", "generated_page_number"):
            value = _page_number(row.get(name, page), name)
            if value != page:
                raise ValueError(f"Page pairing mismatch: {name}={value}, page={page}")
            metadata[name] = value
        for name in ("running_header", "canonical_header", "page_type"):
            if name in row:
                if not isinstance(row[name], str) or not row[name].strip():
                    raise ValueError(f"Manifest {name} must be a non-empty string")
                metadata[name] = row[name]
        if "trusted_header_text" in row:
            if not isinstance(row["trusted_header_text"], bool):
                raise ValueError("trusted_header_text must be a boolean")
            metadata["trusted_header_text"] = row["trusted_header_text"]
        pairs.append({"source": image_path(row.get("source"), "source"),
                      "generated": image_path(row.get("generated", row.get("translated")), "generated"),
                      "metadata": metadata})
    return pairs


def process_batch(pairs, profile, *, logger=print):
    """Write independent page reports and one immutable aggregate per invocation."""
    batch = {"schema_version": 1, "processing_status": "SKIPPED", "pages": []}
    if not profile.enabled:
        return batch
    root = profile.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / ("batch-" + uuid4().hex)
    directory.mkdir()
    batch["summary_dir"] = str(directory)
    batch["processing_status"] = "COMPLETED"
    rows = []
    typography_references = {}
    for pair in pairs:
        metadata = dict(pair.get("metadata", {}))
        page = metadata.get("page_number")
        parity = page % 2 if isinstance(page, int) and not isinstance(page, bool) else None
        reference_key = (parity, metadata.get("page_type", "unspecified"))
        reference = typography_references.get(reference_key)
        if profile.source_aware_enabled and profile.approved_sample is None and reference:
            metadata["typography_reference"] = dict(reference["typography"])
            metadata["typography_reference_page"] = reference["page"]
            metadata["typography_reference_path"] = reference["path"]
            metadata["typography_reference_basis"] = "First usable translated page of the same parity/page_type; provisional visual baseline, not a font standard"
        if pair.get("generated") is None:
            result = {"source": str(pair.get("source") or ""), "generated": "",
                      "metadata": metadata, "processing_status": "SKIPPED",
                      "qc": {"status": "WARNING", "source_aware": {"status": "REVIEW_REQUIRED"},
                             "findings": [{"code": "TRANSLATION_MISSING", "severity": "WARNING",
                                           "message": "No translated image is paired with this source page"}]}}
        else:
            result = process_page(pair.get("source"), pair["generated"], profile,
                                  logger=logger, metadata=metadata)
        batch["pages"].append(result)
        if result["processing_status"] == "ERROR":
            batch["processing_status"] = "ERROR"
        qc = result.get("qc", {})
        typography = qc.get("metrics", {}).get("generated", {}).get("typography", {})
        if (profile.source_aware_enabled and profile.approved_sample is None
                and reference is None and typography
                and typography.get("confidence", 0) >= profile.source_thresholds["min_confidence"]
                and result["processing_status"] == "COMPLETED"):
            typography_references[reference_key] = {
                "typography": dict(typography), "page": page, "path": result["generated"]}
        rows.append({"page_number": metadata.get("page_number", ""),
                     "source": result["source"], "generated": result["generated"],
                     "processing_status": result["processing_status"],
                     "qc_status": qc.get("status", "SKIPPED"),
                     "source_aware_status": qc.get("source_aware", {}).get("status", "SKIPPED"),
                     "findings": "|".join(f["code"] for f in qc.get("findings", [])),
                     "remediation": "|".join(sorted({str(f.get("remediation", "")) for f in qc.get("findings", []) if f.get("remediation")})),
                     "report": str(Path(result["run_dir"]) / "report.json") if result.get("run_dir") else "",
                     "error": result.get("error", "")})
    if profile.source_aware_enabled:
        batch["typography_baseline"] = {
            "method": "approved_sample" if profile.approved_sample else "first_usable_page_by_parity_and_page_type",
            "limitation": "Visual heuristic, not font recognition. Unspecified page types may differ; approve representative samples before calibration.",
            "references": list(typography_references.values()),
        }
    batch["counts"] = {status: sum(row["qc_status"] == status for row in rows)
                       for status in ("PASS", "WARNING", "FAIL", "SKIPPED")}
    with (directory / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(batch, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
    fields = ["page_number", "source", "generated", "processing_status", "qc_status",
              "source_aware_status", "findings", "remediation", "report", "error"]
    with (directory / "summary.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    _log(logger, f"[layout] Batch summary: {directory}")
    return batch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", type=Path)
    group.add_argument("--progress", type=Path)
    group.add_argument("--manifest", type=Path)
    group.add_argument("--pair-by-page", action="store_true")
    parser.add_argument("--generated", type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--generated-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--page-number", type=int)
    parser.add_argument("--source-aware", action="store_true")
    parser.add_argument("--qc-only", action="store_true")
    args = parser.parse_args(argv)
    if args.source and not args.generated:
        parser.error("--source requires --generated")
    if (args.progress or args.pair_by_page) and (not args.source_dir or not args.generated_dir):
        parser.error("--progress/--pair-by-page requires --source-dir and --generated-dir")
    if args.page_number is not None and not args.source:
        parser.error("--page-number is only valid with --source")
    try:
        profile = load_profile(args.profile)
        if args.qc_only:
            profile = replace(profile, normalize_enabled=False)
        if args.source_aware:
            profile = replace(profile, source_aware_enabled=True)
        if args.output_dir:
            profile = replace(profile, output_dir=args.output_dir.resolve())
        if not profile.enabled:
            print("[layout] Disabled in profile; no images processed")
            return 0
        if args.source:
            metadata = None
            if profile.source_aware_enabled:
                if args.page_number is not None:
                    page = _page_number(args.page_number)
                    # Explicit printed page metadata overrides storage indices.
                    source_number = generated_number = page
                else:
                    source_number = _filename_page(args.source)
                    generated_number = _filename_page(args.generated)
                    page = source_number
                metadata = {"page_number": page, "source_page_number": source_number,
                            "generated_page_number": generated_number,
                            "pairing_method": "explicit" if args.page_number else "filename"}
            return _exit_code(process_page(args.source, args.generated, profile, metadata=metadata))
        if args.manifest or args.pair_by_page:
            pairs = (load_manifest(args.manifest) if args.manifest else
                     collect_directory_pairs(args.source_dir, args.generated_dir))
            batch = process_batch(pairs, profile)
            return max((_exit_code(result) for result in batch["pages"]), default=0)
        # Snapshot latest rows before writing any layout results.
        with args.progress.open("r", encoding="utf-8-sig", newline="") as handle:
            fields = csv.DictReader(handle).fieldnames or []
            if not {"file", "output", "status"}.issubset(fields):
                raise ValueError("progress.csv must contain file, output and status columns")
        rows = read_latest_progress(args.progress)
        status = 0
        pairs = []
        for row in rows.values():
            if row.get("status", "").strip().lower() != "done":
                continue
            try:
                source = _child(args.source_dir, row.get("file", ""))
                generated = _child(args.generated_dir, row.get("output", ""))
                if profile.source_aware_enabled:
                    # progress.csv pairs are authoritative; its index is not a printed page number.
                    pairs.append({"source": source, "generated": generated,
                                  "metadata": {"pairing_method": "progress"}})
                else:
                    result = process_page(source, generated, profile)
                    status = max(status, _exit_code(result))
            except Exception as exc:
                print(f"[layout] Invalid progress row; continuing: {type(exc).__name__}: {exc}")
                status = 2
        if pairs:
            batch = process_batch(pairs, profile)
            status = max(status, max((_exit_code(result) for result in batch["pages"]), default=0))
        return status
    except Exception as exc:
        print(f"[layout] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
