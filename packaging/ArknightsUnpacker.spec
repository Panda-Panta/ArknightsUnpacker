# -*- mode: python ; coding: utf-8 -*-
"""Directory-only Windows build; include runtime assets, never the project tree."""
from importlib import metadata
from importlib.util import find_spec
import hashlib
import json
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

root = Path(SPECPATH).parent
preview_only = os.environ.get("ARKNIGHTS_LEVEL_PREVIEW_ONLY") == "1"
bundle_name = "ArknightsMapViewer" if preview_only else "ArknightsUnpacker"
datas = []
binaries = []

def add_tree(folder, destination, pattern="*"):
    for path in sorted(folder.rglob(pattern)):
        if path.is_file() and "__pycache__" not in path.parts:
            datas.append((str(path), str(Path(destination) / path.relative_to(folder).parent)))

add_tree(root / "resources", "resources")
add_tree(root / "vendor" / "ark_fbs", "vendor/ark_fbs", "*.py")
add_tree(root / "vendor" / "lz4ak", "vendor/lz4ak", "*.py")
add_tree(root / "packaging" / "licenses", "licenses")
datas.append((str(root / "vendor" / "Ark-Unpacker-LICENSE"), "licenses/Ark-Unpacker"))
guide = "LEVEL_PREVIEW_GUIDE.md" if preview_only else "USER_GUIDE.md"
for name in (guide, "THIRD_PARTY_NOTICES.md"):
    datas.append((str(root / "docs" / name), "docs"))
godot_runtime = os.environ.get("ARKNIGHTS_GODOT_RUNTIME") if preview_only else None
if preview_only and not godot_runtime:
    raise SystemExit("The level preview bundle requires ARKNIGHTS_GODOT_RUNTIME")
if godot_runtime:
    godot = Path(godot_runtime).resolve(strict=True)
    godot_source = root / "packaging" / "godot"
    expected = json.loads((godot_source / "source.json").read_text(encoding="utf-8"))
    with godot.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected["executable_sha256"]:
            raise SystemExit("ARKNIGHTS_GODOT_RUNTIME must point to the pinned official Godot 4.7.2 x64 executable")
    add_tree(godot_source, "licenses/Godot")
    for folder, names in (
        ("native_player", ("project.godot", "replay.tscn", "replay.gd", "battle_static.gdshader")),
        ("native_bake", ("bake.html", "bake.js")),
    ):
        destination = f"scripts/level_preview/{folder}"
        for name in names:
            datas.append((str(root / destination / name), destination))

# Data-driven class imports and embedded typetrees are essential to UnityPy.
datas += collect_data_files("UnityPy")
datas += collect_data_files("archspec", excludes=["**/tests/**"])
datas += collect_data_files("tpk_ar")
binaries += collect_dynamic_libs("fmod_toolkit")
binaries += collect_dynamic_libs("astc_encoder")

# Preserve actual wheel license text and metadata; do not infer one package's
# license for native DLLs or generated Ark-FBS schemas.
runtime_distributions = (
    "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "UnityPy", "flatbuffers",
    "Pillow", "fonttools", "numpy", "pycryptodome", "bson", "lz4", "spine-asset",
    "WannaCRI", "ffmpeg-python", "fmod-toolkit", "pyfmodex", "texture2ddecoder",
    "etcpak", "astc-encoder-py", "archspec", "brotli", "fsspec", "tpk-ar",
    "attrs", "python-dateutil", "six", "future", "typing-extensions", "tqdm",
    "python-json-logger", "colorama", "packaging", "pyinstaller",
)
for name in runtime_distributions:
    distribution = metadata.distribution(name)
    for file in distribution.files or ():
        parts = Path(str(file)).parts
        if not any(part.endswith(".dist-info") for part in parts):
            continue
        if file.name == "METADATA" or any(token in file.name.lower() for token in ("license", "licence", "copying", "notice", "copyright")):
            path = distribution.locate_file(file)
            if path.is_file():
                datas.append((str(path), "licenses/" + name + "/" + str(Path(str(file)).parent)))
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    datas.append((str(python_license), "licenses/Python"))

fmod_root = Path(next(iter(find_spec("fmod_toolkit").submodule_search_locations)))
os.environ.setdefault("PYFMODEX_DLL_PATH", str(fmod_root / "libfmod/Windows/x64/fmod.dll"))
hiddenimports = collect_submodules("UnityPy") + collect_submodules("pyfmodex")
# Page factories import optional views by name so the shell can omit them.
if not preview_only:
    hiddenimports += collect_submodules(
        "arknights_unpacker.ui", filter=lambda name: not name.startswith("arknights_unpacker.ui.level_"))
hiddenimports += collect_submodules("fontTools.ttLib.tables")
hiddenimports += ["PIL.PngImagePlugin", "PIL.JpegImagePlugin", "PIL.BmpImagePlugin", "PIL.TgaImagePlugin", "Crypto.Cipher.AES", "bson", "flatbuffers", "numpy", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"]
preflight = os.environ.get("ARKNIGHTS_BUILD_PREFLIGHT") == "1"
if preflight and preview_only:
    raise SystemExit("The level preview and decoder preflight build profiles are separate")
entrypoint = root / "packaging" / ("level_preview_entrypoint.py" if preview_only
                                 else "preflight.py" if preflight else "entrypoint.py")
excluded = ["PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel", "tkinter", "pytest"]
a = Analysis([str(entrypoint)], pathex=[str(root / "src")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports,
             excludes=excluded,
             hookspath=[], hooksconfig={}, runtime_hooks=[], noarchive=False, optimize=0)
if godot_runtime:
    # It is launched as a separate process. Preserve the vendor executable byte for byte.
    a.datas.append(("scripts/level_preview/native_player/Godot.exe", str(godot), "DATA"))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=bundle_name,
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False, contents_directory="_internal",
          icon=str(root / "resources/ui/app-icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=bundle_name)
