"""Packaging-only probe. This is never the production application entry point."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    output = Path(sys.argv[1])
    result = {"purpose": "frozen dependency preflight, not final application acceptance", "checks": {}}
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from arknights_unpacker.paths import resource_root
        from arknights_unpacker.extraction.decoder import schema
        from PySide6.QtWidgets import QApplication, QWidget
        from PIL import Image
        import fmod_toolkit.importer
        import UnityPy
        app = QApplication.instance() or QApplication([])
        widget = QWidget()
        widget.resize(320, 200)
        widget.show()
        app.processEvents()
        result["checks"]["qt_widgets"] = widget.isVisible()
        result["checks"]["resource_root"] = str(resource_root())
        result["checks"]["templates"] = (resource_root() / "resources/html/operator.html").is_file()
        result["checks"]["schema"] = schema("character_table").__name__
        result["checks"]["unitypy"] = UnityPy.__version__
        result["checks"]["fmod_dll"] = Path(fmod_toolkit.importer.get_fmod_path_for_system()).is_file()
        result["checks"]["fmod_loaded"] = fmod_toolkit.importer.import_pyfmodex() is not None
        import lz4ak.Block
        result["checks"]["lz4ak"] = True
        image_path = output.with_suffix(".png")
        Image.new("RGBA", (2, 2), (255, 0, 0, 128)).save(image_path)
        result["checks"]["pillow_png"] = image_path.is_file()
        widget.close()
        for key in ("qt_widgets", "templates", "fmod_dll", "fmod_loaded", "lz4ak", "pillow_png"):
            if not result["checks"][key]:
                raise RuntimeError("Required frozen preflight check failed: " + key)
        result["status"] = "passed"
    except BaseException:
        result.update(status="failed", traceback=traceback.format_exc())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
