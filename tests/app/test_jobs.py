import json
import subprocess
import sys
from pathlib import Path


def test_worker_failure_returns_nonzero_and_structured_error(tmp_path):
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"operation": "invalid-operation", "result_file": str(result)}), encoding="utf-8")
    process = subprocess.run([sys.executable, "-m", "arknights_unpacker", "--worker", str(request)], capture_output=True, text=True)
    assert process.returncode != 0
    assert result.exists(), process.stderr
    data = json.loads(result.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert "invalid-operation" in data["error"]


def test_output_cannot_be_in_game_even_through_link(tmp_path):
    from arknights_unpacker.paths import validate_output
    game = tmp_path / "game"
    game.mkdir()
    import pytest
    with pytest.raises(ValueError, match="游戏"):
        validate_output(game / "new" / "reports", game)
    assert validate_output(tmp_path / "output", game) == (tmp_path / "output").resolve()


def test_windowed_worker_does_not_require_console_streams(tmp_path, monkeypatch):
    import types
    from arknights_unpacker.jobs import worker_entry
    engine = types.ModuleType("arknights_unpacker.extraction.engine")
    engine.list_bundle_objects = lambda path: []
    monkeypatch.setitem(sys.modules, engine.__name__, engine)
    request = tmp_path / "request.json"
    result = tmp_path / "result.json"
    request.write_text(json.dumps({"operation": "objects", "args": {"path": "empty"},
                                  "result_file": str(result)}), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert worker_entry(str(request)) == 0
    assert json.loads(result.read_text(encoding="utf-8"))["value"] == []
    assert (tmp_path / "events.jsonl").exists()


def test_relative_profile_path_is_valid_for_child_working_directory(tmp_path, monkeypatch):
    import pytest
    from arknights_unpacker.jobs import WorkerRunner
    monkeypatch.chdir(tmp_path)
    runner = WorkerRunner(Path("jobs"))
    with pytest.raises(RuntimeError, match="invalid-operation"):
        runner.run("invalid-operation", {})


def test_runtime_database_never_created_in_detectable_game_root(tmp_path):
    import pytest
    from arknights_unpacker.application import AppServices
    game = tmp_path / "game"
    (game / "Arknights_Data").mkdir(parents=True)
    profile = game / "profile"
    with pytest.raises(ValueError, match="游戏"):
        AppServices(profile)
    assert not profile.exists()


def test_runtime_database_not_created_in_supported_loose_resource_directory(tmp_path):
    import pytest
    from arknights_unpacker.application import AppServices
    raw = tmp_path / "loose-resources"
    raw.mkdir()
    (raw / "sample.ab").write_bytes(b"UnityFS-fixture")
    profile = raw / "tool-data"
    with pytest.raises(ValueError, match="游戏"):
        AppServices(profile)
    assert not profile.exists()


def test_stale_selection_outside_current_game_is_rejected(tmp_path):
    import pytest
    from arknights_unpacker.application import AppServices
    from arknights_unpacker.contracts import GameInstallation
    service = AppServices(tmp_path / "profile")
    game = tmp_path / "game"
    game.mkdir()
    other = tmp_path / "other.ab"
    other.write_bytes(b"unrelated")
    service.installation = GameInstallation(game, "id")
    with pytest.raises(ValueError, match="当前游戏"):
        service.extract([str(other)], str(tmp_path / "output"))


def test_service_export_cancellation_stops_later_formats_and_records_manifest(tmp_path, monkeypatch):
    import pytest
    from arknights_unpacker.application import AppServices
    from arknights_unpacker.contracts import (CancelToken, CancelledError, ExportFormat,
                                               GameDataSnapshot, OperatorProfile)
    service = AppServices(tmp_path / "profile")
    service.gamedata = GameDataSnapshot("fixture", "1", "1", {})
    game = tmp_path / "game"
    game.mkdir()
    service.config["game_root"] = str(game)
    monkeypatch.setattr(service, "operator_profile", lambda *args: OperatorProfile("char_fixture", "取消测试"))
    token = CancelToken()
    events = []
    def progress(event):
        events.append(event)
        if event.get("stage") == "report_export":
            token.cancel()
    with pytest.raises(CancelledError):
        service.export(["char_fixture"], [], tmp_path / "output", {ExportFormat.HTML},
                       cancel=token, emit=progress)
    manifests = list((tmp_path / "output").glob("report-*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "cancelled"
    assert manifest["complete"] is False
    assert [artifact["format"] for artifact in manifest["artifacts"]] == ["json"]
    assert not list((tmp_path / "output").rglob("*.html"))
    assert any(event.get("stage") == "report_export" for event in events)


def test_local_verifier_rejects_game_output_before_any_write(tmp_path):
    import types
    import pytest
    from arknights_unpacker.bootstrap import verify_installation
    game = tmp_path / "game"
    (game / "Arknights_Data").mkdir(parents=True)
    output = game / "verification"
    with pytest.raises(ValueError, match="游戏"):
        verify_installation(types.SimpleNamespace(), str(game), output)
    assert not output.exists()


def test_extraction_receipts_are_isolated_across_tasks(tmp_path, monkeypatch):
    from arknights_unpacker.application import AppServices
    from arknights_unpacker.contracts import GameInstallation
    service = AppServices(tmp_path / "profile")
    game = tmp_path / "game"
    game.mkdir()
    source = game / "sample.ab"
    source.write_bytes(b"fixture")
    service.installation = GameInstallation(game, "id")
    def run(operation, request, *args):
        receipt = Path(request["output_root"]) / "extraction-result.json"
        receipt.write_text(json.dumps({"request_id": request["request_id"]}), encoding="utf-8")
        return {"request_id": request["request_id"], "status": "succeeded"}
    monkeypatch.setattr(service.runner, "run", run)
    first = service.extract([str(source)], str(tmp_path / "output"))
    second = service.extract([str(source)], str(tmp_path / "output"))
    assert first.output_root != second.output_root
    assert (Path(first.output_root) / "extraction-result.json").exists()
    assert (Path(second.output_root) / "extraction-result.json").exists()
    assert service.config["output_root"] == str((tmp_path / "output").resolve())
