"""Offline Full Reflow of immutable saved datasets; no worker/provider imports."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from html import escape
import json
import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

from layout_rebuilder import RebuildProfile, build_content
from layout_calibration import run_layout, math_integrity
from translation_evidence import audit_fallback, digest, file_hash

PROFILE = RebuildProfile(width=1200, height=1668, body_size=24, title_size=28,
                         line_height=1.25, paragraph_gap=6, indent=24, math_gap=6)


def load_saved_dataset(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if digest({k: v for k, v in data.items() if k != "dataset_sha256"}) != data.get("dataset_sha256"):
        raise ValueError("Dataset hash mismatch")
    for key in ("source_image", "translated_image"):
        item = data[key]
        image = Path(item["path"])
        if not image.is_absolute():
            image = path.parent / image
        if file_hash(image) != item["sha256"]:
            raise ValueError("Input image hash mismatch: " + key)
    evidence = data["translation"]
    audit = evidence.get("capture_audit")
    candidate = audit_fallback(audit, evidence=evidence).get("candidate")
    if not candidate or audit["source_sha256"] != data["source_image"]["sha256"]:
        raise ValueError("Missing bound saved translation; an image alone cannot supply Full Reflow text/math")
    return data, candidate


def discover_datasets(folder):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("Select a saved-data folder")
    # Filename identifies a dataset container, never printed page order or pairing.
    return sorted(p for p in folder.rglob("dataset.json") if p.is_file())


def render_saved_dataset(page, dataset, output, profile=PROFILE):
    data, candidate = load_saved_dataset(dataset)
    content, rows, structure = build_content(candidate)
    expected_text = "".join(n["text"] for n in structure["nodes"] if n["kind"] == "text")
    metrics, measurement = run_layout(page, content, profile,
                                      (profile.width, profile.height), calibrated_style=True)
    if metrics["content_text"] != expected_text:
        raise ValueError("Reflow text preservation failed")
    integrity = math_integrity(structure, rows, measurement)
    native = [row for row in rows if row["status"] == "NATIVE_MATHML"]
    if integrity["technical_preserved"] != len(native):
        raise ValueError("MathML preservation failed")
    # Unsupported formulas remain literal LaTeX, never reconstructed or dropped.
    if any(not node["latex_exact"] or node["render_occurrences"] != 1 for node in integrity["nodes"]):
        raise ValueError("Formula inventory/LaTeX preservation failed")
    output = Path(output)
    output.mkdir(exist_ok=False)
    html = page.content()
    (output / "full-reflow.html").write_text(html, encoding="utf-8")
    exported = []
    for index in range(metrics["page_count"]):
        name = f"page-{index+1:03d}.png"
        page.locator(".page").nth(index).screenshot(path=str(output / name))
        exported.append(name)
    overlaps = [issue for pg in measurement["pages"] for issue in pg["overlaps"]]
    safe = not metrics["issues"] and not metrics["oversized"] and not overlaps and len(native) == len(rows)
    references = {}
    for key in ("source_image", "translated_image"):
        reference = Path(data[key]["path"])
        if not reference.is_absolute():
            reference = Path(dataset).resolve().parent / reference
        target = "reference-" + key + reference.suffix.lower()
        shutil.copyfile(reference, output / target)
        if file_hash(output / target) != data[key]["sha256"]:
            raise ValueError("Reference copy hash mismatch")
        references[key] = target
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Full Reflow comparison</title>'
        '<style>body{font:17px system-ui;margin:24px}img{max-width:100%}.refs{display:flex;gap:12px}.refs figure{width:50%;margin:0}</style>'
        '<h1>Full Reflow</h1><p>EXPERIMENTAL_UNVERIFIED — hình nguồn giữ trong ảnh tham chiếu, chưa ghép vào reflow.</p>'
        '<p><a href="full-reflow.html">Xem toàn bộ trang đã dàn</a> · <a href="report.json">Số đo và LaTeX giữ nguyên</a></p>'
        '<div class="refs"><figure><figcaption>Nguồn nguyên bản</figcaption><a href="' + references["source_image"] + '"><img src="' + references["source_image"] + '"></a></figure>'
        '<figure><figcaption>Ảnh dịch đã lưu</figcaption><a href="' + references["translated_image"] + '"><img src="' + references["translated_image"] + '"></a></figure></div>', encoding="utf-8")
    report = {"status": "EXPERIMENTAL_UNVERIFIED", "layout_status": "TECHNICAL_FIT_UNVERIFIED" if safe else "REVIEW_REQUIRED",
              "eligible_for_final_page": False, "source_dataset": str(Path(dataset).resolve()),
              "source_dataset_sha256": file_hash(dataset), "profile": asdict(profile), "reference_copies": references,
              "text_exact": True, "math": integrity, "metrics": metrics, "overlaps": overlaps,
              "exported_pages": exported, "geometry_inserted": 0,
              "source_references": {k: data[k] for k in ("source_image", "translated_image")},
              "saved_geometry_references": data.get("geometry_crops", []),
              "readiness_unchanged": data.get("readiness"),
              "limits": "Saved content order retained; no semantic/boundary verification or source-figure insertion. Oversized pages retain their full extent."}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def reflow_saved_folder(folder, output_root, *, browser_executable=None):
    datasets = discover_datasets(folder)
    if not datasets:
        raise ValueError("Không có dataset.json trong thư mục đã chọn. Full Reflow cần dữ liệu dịch đã lưu, không thể dựng công thức từ ảnh PNG.")
    output = Path(output_root).resolve() / ("full-reflow-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    # Packaged app bundles browser binaries beside the executable.
    bundled = Path(sys.executable).resolve().parent / "ms-playwright"
    if getattr(sys, "frozen", False) and bundled.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled))
    from playwright.sync_api import sync_playwright, Error
    results = []; network_attempts = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True, **({"executable_path": browser_executable} if browser_executable else {}))
        except Error:
            if browser_executable:
                raise
            browser = playwright.chromium.launch(channel="msedge", headless=True)
        try:
            context = browser.new_context(offline=True, viewport={"width": 1280, "height": 1748}, device_scale_factor=1)
            def deny(route):
                network_attempts.append(route.request.url); route.abort()
            context.route("**/*", deny)
            for index, dataset in enumerate(datasets, 1):
                page = context.new_page()
                try:
                    name = f"capture-{index:04d}"
                    report = render_saved_dataset(page, dataset, output / name)
                    results.append({"dataset": str(dataset), "output": name, "layout_status": report["layout_status"], "pages": len(report["exported_pages"]), "ok": True})
                except Exception as exc:
                    results.append({"dataset": str(dataset), "ok": False, "error": str(exc)})
                finally:
                    page.close()
        finally:
            browser.close()
    summary = {"status": "EXPERIMENTAL_UNVERIFIED", "output": str(output), "results": results,
               "succeeded": sum(r["ok"] for r in results), "failed": sum(not r["ok"] for r in results),
               "pages": sum(r.get("pages", 0) for r in results), "network_attempts": network_attempts,
               "book_order_verified": False, "pilot_C_run": False, "profile": asdict(PROFILE)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    links = "".join("<li>" + escape(r["dataset"]) + (f' — <a href="{r["output"]}/index.html">Xem reflow</a> · {r["pages"]} trang · {r["layout_status"]}' if r["ok"] else " — Lỗi: " + escape(r["error"])) + "</li>" for r in results)
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Full Reflow</title><style>body{font:17px system-ui;margin:24px}li{margin:12px 0}</style><h1>Full Reflow từ dữ liệu đã lưu</h1><p>EXPERIMENTAL_UNVERIFIED. Các capture xuất riêng; chưa xác minh thứ tự toàn sách. Hình nguồn chưa được ghép; đường dẫn chứng cứ giữ trong report.json.</p><ul>' + links + '</ul>', encoding="utf-8")
    return summary
