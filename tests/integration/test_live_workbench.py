"""Opt-in end-to-end Qt flow against the user's installed read-only resources."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = [pytest.mark.local, pytest.mark.skipif(
    not os.environ.get("ARKNIGHTS_GAME_ROOT"), reason="Set ARKNIGHTS_GAME_ROOT for real local resources")]


def test_live_gui_scan_extract_profiles_and_reports(qtbot, tmp_path):
    from PySide6.QtCore import QTimer
    from arknights_unpacker.application import AppServices
    from arknights_unpacker.ui.main_window import MainWindow

    root = Path(os.environ["ARKNIGHTS_GAME_ROOT"])
    evidence = Path(os.environ.get("ARKNIGHTS_LIVE_EVIDENCE", str(tmp_path / "evidence"))).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    services = AppServices(tmp_path / "profile")
    services.config["output_root"] = str(evidence / "exports")
    window = MainWindow(services)
    qtbot.addWidget(window)
    window.show()
    pulses = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: pulses.append(1))
    timer.start(20)

    def idle():
        qtbot.waitUntil(lambda: not window.queue.busy and all(j.status != "排队中" for j in window.queue.jobs), timeout=180000)
        failures = [(j.title, j.status) for j in window.queue.jobs if j.status != "成功"]
        assert not failures, failures

    try:
        window.root_edit.setText(str(root))
        window.scan()
        idle()
        assert services.scan_snapshot.complete
        assert len(services.scan_snapshot.files) > 10000
        window.explorer.recursive.setChecked(True)
        window.explorer.ab_only.setChecked(True)
        window.explorer.search.setText("chararts/char_002_amiya.ab")
        assert window.explorer.model.rowCount() >= 1
        window.explorer.table.selectRow(0)
        paths = window.explorer.selected_paths()
        assert len(paths) == 1 and paths[0].lower().endswith("char_002_amiya.ab")
        window.tabs.setCurrentWidget(window.explorer)
        assert window.grab().save(str(evidence / "01-resource-browser.png"))
        for kind, checkbox in window.settings.kinds.items():
            checkbox.setChecked(kind == "image")
        window.explorer.extract_selected()
        idle()
        assert list((evidence / "exports").rglob("*.png")), "Real image extraction must produce PNGs"

        window.load_data()
        idle()
        assert services.gamedata.complete
        assert len(services.operators()) > 400
        assert len(services.modules()) > 500
        window.tabs.setCurrentWidget(window.operators)
        window.operators.search.setText("char_4231_clemnt")
        assert window.operators.model.rowCount() == 1
        window.operators.table.selectRow(0)
        idle()
        profile = window.operators.current_profile
        assert profile.name == "克莱门莎"
        attributes = {item["key"]: item["value"] for item in profile.attributes}
        assert attributes["atk"] == 1065
        assert attributes["cost"] == 21
        assert len(profile.skills) == 3
        assert len(profile.building_skills) == 2
        assert window.grab().save(str(evidence / "02-operator-profile.png"))

        window.operators.request_export(False)
        idle()
        operator_artifacts = window.queue.jobs[-1].artifacts
        assert {"png", "html", "json", "txt"} <= {a.format for a in operator_artifacts}
        dialog = window._dialogs[-1]
        assert dialog.pages.count() >= 1 and not dialog._pixmap.isNull()
        assert dialog.grab().save(str(evidence / "03-report-preview.png"))
        dialog.close()

        window.tabs.setCurrentWidget(window.modules)
        window.modules.search.setText("uniequip_003_mgllan")
        assert window.modules.model.rowCount() == 1
        window.modules.table.selectRow(0)
        idle()
        assert len(window.modules.current_profile.phases) == 3
        assert window.grab().save(str(evidence / "04-module-profile.png"))
        window.modules.request_export(False)
        idle()
        module_artifacts = window.queue.jobs[-1].artifacts
        assert {"png", "html"} <= {a.format for a in module_artifacts}
        for artifact in operator_artifacts + module_artifacts:
            assert Path(artifact.path).is_file()
        manifests = list((evidence / "exports").glob("report-*/manifest.json"))
        assert len(manifests) == 2
        assert all(json.loads(path.read_text(encoding="utf-8"))["complete"] for path in manifests)
        # Reopen the actual saved queue with no core data in memory. Previously
        # generated reports must remain available without rerunning extraction.
        for existing in window._dialogs:
            existing.close()
        window.close()
        services.shutdown()
        restored_services = AppServices(services.data_root)
        restored_services.config["game_root"] = ""  # Suppress the ordinary startup rescan in this check.
        restored = MainWindow(restored_services)
        qtbot.addWidget(restored)
        restored.show()
        try:
            assert len(restored.queue.jobs) == len(window.queue.jobs)
            assert not restored.queue.busy
            assert restored_services.gamedata is None
            report_index = next(i for i, job in enumerate(restored.queue.jobs)
                                if any((a.get("format") if isinstance(a, dict) else a.format) == "png" for a in job.artifacts)
                                and "资料" in job.title)
            restored.tabs.setCurrentWidget(restored.jobs)
            restored.jobs.table.selectRow(report_index)
            restored.jobs.preview_artifacts()
            assert not restored._dialogs[-1]._pixmap.isNull()
            assert restored.grab().save(str(evidence / "05-restored-task-history.png"))
            restarted_count = len(restored.queue.jobs)
        finally:
            for existing in restored._dialogs:
                existing.close()
            restored.close()
            restored_services.shutdown()
        (evidence / "receipt.json").write_text(json.dumps({
            "evidence": "Real Qt signals, queue, isolated extraction/table workers and report preview; no browser opened",
            "data_version": services.gamedata.version, "resource_version": services.gamedata.resource_version,
            "files": len(services.scan_snapshot.files), "operators": len(services.operators()),
            "modules": len(services.modules()), "event_loop_pulses": len(pulses),
            "restored_history_jobs": restarted_count,
            "jobs": [{"title": j.title, "status": j.status} for j in window.queue.jobs],
            "operator_artifacts": [a.path for a in operator_artifacts],
            "module_artifacts": [a.path for a in module_artifacts],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        assert len(pulses) > 10, "Qt event loop must remain active during real workers"
    finally:
        timer.stop()
        for dialog in window._dialogs:
            dialog.close()
        window.close()
        services.shutdown()
