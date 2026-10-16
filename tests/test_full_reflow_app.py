import json
from pathlib import Path
from unittest.mock import patch
import pytest

from layout_full_reflow import load_saved_dataset, reflow_saved_folder
from translation_evidence import file_hash
from desktop.web_api import WebApi
from desktop.webview_app import WebBridge
import test_web_api as helpers

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "output/task2g-live-resume-20261010-192802/capture/capture-50a0ac2d28e3424c9f8a40befdcab1c1/dataset/dataset.json"


def test_raster_only_never_starts_renderer(tmp_path):
    (tmp_path / "a.png").write_bytes(b"not structured evidence")
    with pytest.raises(ValueError, match="dataset.json"):
        reflow_saved_folder(tmp_path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_changed_dataset_rejected(tmp_path):
    if not DATASET.exists():
        pytest.skip("Saved evidence unavailable")
    data = json.loads(DATASET.read_text(encoding="utf-8"));data["pairing_status"] = "MODIFIED"
    target = tmp_path / "dataset.json";target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Dataset hash mismatch"):
        load_saved_dataset(target)


def test_actual_capture_preserved_and_outputs_unique(tmp_path):
    if not DATASET.exists():
        pytest.skip("Saved evidence unavailable")
    before = file_hash(DATASET)
    result = reflow_saved_folder(DATASET.parent, tmp_path)
    assert result["succeeded"] == 1, result
    assert result["failed"] == 0 and result["network_attempts"] == []
    assert result["book_order_verified"] is False and result["pilot_C_run"] is False
    report = json.loads((Path(result["output"]) / "capture-0001/report.json").read_text(encoding="utf-8"))
    assert report["text_exact"] and report["math"]["math_nodes"] == 66
    assert report["math"]["technical_preserved"] == 66
    for key,name in report["reference_copies"].items():
        assert file_hash(Path(result["output"]) / "capture-0001" / name) == report["source_references"][key]["sha256"]
    assert report["geometry_inserted"] == 0 and report["eligible_for_final_page"] is False
    assert len(report["exported_pages"]) >= 1 and file_hash(DATASET) == before
    assert all(n["latex_exact"] and n["render_occurrences"] == 1 for n in report["math"]["nodes"])


def test_api_cancel_and_no_worker_or_settings_write(tmp_path):
    import types
    api = WebApi(app_dir=ROOT, data_dir=tmp_path, scheduler=helpers.FakeScheduler())
    api.window = types.SimpleNamespace(create_file_dialog=lambda *a, **kw: None)
    with patch.dict("sys.modules", {"webview": types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER=1))}):
        assert WebBridge(api).full_reflow_saved(str(tmp_path))["data"]["cancelled"] is True
    assert not api._reflow_lock.locked()
    assert not (tmp_path / "app_settings.json").exists()
    assert api.controller.process is None


def test_api_rejects_duplicate_job_and_batch_launch(tmp_path):
    api = WebApi(app_dir=ROOT, data_dir=tmp_path, scheduler=helpers.FakeScheduler())
    api._reflow_lock.acquire()
    try:
        assert api.full_reflow_saved()["ok"] is False
        with pytest.raises(RuntimeError, match="Full Reflow"):
            api._start("main")
    finally:
        api._reflow_lock.release()


def test_api_render_runs_outside_worker_and_keeps_settings(tmp_path):
    import types
    from copy import deepcopy
    api = WebApi(app_dir=ROOT, data_dir=tmp_path, scheduler=helpers.FakeScheduler())
    api.window = types.SimpleNamespace(create_file_dialog=lambda *a, **kw: [str(tmp_path / "saved")])
    before = deepcopy(api.settings)
    mock_result = {"succeeded":1,"pages":2,"failed":0,"output":str(tmp_path / "result")}
    with patch.dict("sys.modules", {"webview": types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER=1))}), patch("layout_full_reflow.reflow_saved_folder", return_value=mock_result) as render, patch("desktop.web_api.os.startfile", create=True):
        result = WebBridge(api).full_reflow_saved(str(tmp_path / "out"))
    assert result["ok"] and result["data"]["pages"] == 2
    render.assert_called_once_with(str(tmp_path / "saved"), tmp_path / "out/full_reflow_results")
    assert api.settings == before and not api._reflow_lock.locked()
    assert api.controller.process is None


def test_batch_failure_continues_other_saved_captures(tmp_path):
    if not DATASET.exists():
        pytest.skip("Saved evidence unavailable")
    import shutil
    inputs = tmp_path / "inputs"
    for name in ("good", "bad"):
        (inputs / name).mkdir(parents=True)
    shutil.copyfile(DATASET, inputs / "good/dataset.json")
    (inputs / "bad/dataset.json").write_text("{}", encoding="utf-8")
    result = reflow_saved_folder(inputs, tmp_path / "out")
    assert result["succeeded"] == 1 and result["failed"] == 1
    assert result["network_attempts"] == []
    assert any(not r["ok"] and "Dataset hash mismatch" in r["error"] for r in result["results"])


def test_session_manager_routes_reflow_to_selected_book(tmp_path):
    from desktop.workflow_sessions import SessionManager
    manager = SessionManager(app_dir=ROOT, data_dir=tmp_path)
    try:
        with patch.object(manager.sessions['book-2'], 'full_reflow_saved', return_value={'ok':True,'data':{'cancelled':True}}) as target, patch.object(manager.sessions['book-1'], 'full_reflow_saved') as other:
            result = WebBridge(manager).full_reflow_saved('D:/book-B', 'book-2')
        assert result['ok']
        target.assert_called_once_with('D:/book-B')
        other.assert_not_called()
    finally:
        manager._shutdown()
