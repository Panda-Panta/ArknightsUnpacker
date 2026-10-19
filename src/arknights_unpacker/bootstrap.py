from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
import traceback

from . import __version__
from .contracts import ExportFormat, as_jsonable
from .paths import atomic_json, validate_data_root, validate_output


def verify_installation(services, root: str, target: Path) -> dict:
    """Exercise production services with real inputs; records no browser claims."""
    target = validate_output(validate_data_root(target), root)
    target.mkdir(parents=True, exist_ok=True)
    events = []
    def progress(event):
        events.append(as_jsonable(event))
    start = time.monotonic()
    scan = services.scan(root, emit=progress)
    data = services.load_data(root, emit=progress)
    rows = services.operators()
    char_id = "char_4231_clemnt" if any(r["id"] == "char_4231_clemnt" for r in rows) else rows[0]["id"]
    profile = services.operator_profile(char_id)
    modules = services.modules()
    module_id = "uniequip_002_chen" if any(r["id"] == "uniequip_002_chen" for r in modules) else modules[0]["id"] if modules else None
    artifacts = services.export([char_id], [module_id] if module_id else [], str(target / "reports"),
                                {ExportFormat.PNG, ExportFormat.HTML}, emit=progress)
    extraction_checks = []
    def sample_path(relative):
        for layer in ("hot", "base"):
            source = services.installation.source_roots.get(layer)
            if source and (Path(source) / relative).is_file():
                return Path(source) / relative
        return None
    # These are opt-in local acceptance samples, not a source selection rule.
    samples = [("chararts/char_002_amiya.ab", ["image", "spine"]),
               ("arts/dynchars/char_003_kalts_boc#6.ab", ["audio"]),
               ("raw/video/01.usm", ["video"])]
    for relative, kinds in samples:
        source = sample_path(relative)
        if source is None:
            extraction_checks.append({"sample": relative, "status": "not_installed"})
            continue
        object_ids = {}
        if kinds == ["audio"]:
            objects = services.objects(str(source), emit=progress)
            clips = [item for item in objects if item["type"] == "AudioClip"]
            if not clips:
                raise RuntimeError("音频验收样本不含 AudioClip")
            object_ids[str(source)] = [clips[0]["id"]]
        result = services.extract([str(source)], str(target / "extraction" / kinds[0]),
                                  kinds=kinds, object_ids=object_ids, emit=progress)
        if result.errors or not result.outputs:
            raise RuntimeError(f"资源验收失败 {relative}: {result.errors or result.skipped}")
        checks = {"sample": relative, "status": result.status, "result": as_jsonable(result)}
        if "image" in kinds:
            from PIL import Image
            alpha_ranges = []
            for output in result.outputs:
                if Path(output["path"]).suffix.lower() == ".png":
                    with Image.open(output["path"]) as picture:
                        picture.load()
                        alpha_ranges.append(picture.convert("RGBA").getchannel("A").getextrema())
            if (0, 255) not in alpha_ranges:
                raise RuntimeError("图片验收未发现明确配对的透明通道")
            checks["alpha_ranges"] = alpha_ranges
        if "audio" in kinds:
            import wave
            waves = [out for out in result.outputs if Path(out["path"]).suffix.lower() == ".wav"]
            if not waves:
                raise RuntimeError("音频验收没有生成 WAV")
            with wave.open(waves[0]["path"], "rb") as stream:
                checks["wav"] = {"channels": stream.getnchannels(), "sample_rate": stream.getframerate(),
                                 "frames": stream.getnframes()}
        if "video" in kinds and not any(out["kind"] == "video_stream" for out in result.outputs):
            raise RuntimeError("视频验收没有分离视频流")
        extraction_checks.append(checks)
    receipt = {"version": __version__, "scan_complete": scan["snapshot"].complete,
               "files": len(scan["snapshot"].files), "resource_count": len(scan["catalog"].resources),
               "data_complete": data.complete, "data_version": data.version,
               "resource_version": data.resource_version, "operators": len(rows), "modules": len(modules),
               "profile": as_jsonable(profile), "artifacts": as_jsonable(artifacts),
               "extraction_checks": extraction_checks,
               "elapsed_seconds": round(time.monotonic() - start, 2), "events": events,
               "evidence": "Production service and isolated worker flow; browser offline rendering not exercised."}
    atomic_json(target / "verification.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="明日方舟 PC 资源与资料工作台")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--game-root", default="")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--smoke-test", metavar="JSON", help=argparse.SUPPRESS)
    parser.add_argument("--headless-verify", metavar="DIR", help=argparse.SUPPRESS)
    args = parser.parse_args()
    from .application import AppServices
    services = AppServices(args.data_dir)
    if args.output_dir:
        services.config["output_root"] = str(Path(args.output_dir).resolve())
    if args.headless_verify:
        safe_target = None
        try:
            root = args.game_root or services.config.get("game_root")
            if not root:
                raise ValueError("验证需要 --game-root")
            safe_target = validate_output(validate_data_root(Path(args.headless_verify)), root)
            verify_installation(services, root, safe_target)
            return 0
        except Exception as exc:
            failure_path = (safe_target / "failure.json") if safe_target else (services.data_root / "verification-failure.json")
            atomic_json(failure_path, {"error": str(exc), "traceback": traceback.format_exc()})
            return 1
        finally:
            services.shutdown()
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ArknightsUnpacker")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("ArknightsUnpacker")
    window = MainWindow(services, initial_root=args.game_root)
    app.aboutToQuit.connect(services.shutdown)
    window.show()
    if args.smoke_test:
        receipt = validate_output(validate_data_root(Path(args.smoke_test)),
                                  args.game_root or services.config.get("game_root"))
        def record():
            try:
                image_path = receipt.with_suffix(".png")
                image_path.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(image_path))
                atomic_json(receipt, {"version": __version__, "qt_version": qVersion(),
                                      "visible": window.isVisible(), "width": window.width(), "height": window.height(),
                                      "tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())],
                                      "screenshot": str(image_path), "frozen": bool(getattr(sys, "frozen", False))})
            finally:
                window.close()
        QTimer.singleShot(1800, record)
        QTimer.singleShot(30000, app.quit)
    return app.exec()
