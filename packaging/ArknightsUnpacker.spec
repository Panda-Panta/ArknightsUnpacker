# -*- mode: python ; coding: utf-8 -*-
"""Directory-only Windows build; include runtime assets, never the project tree."""
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

root = Path(SPECPATH).parent
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
for name in ("USER_GUIDE.md", "THIRD_PARTY_NOTICES.md"):
    datas.append((str(root / "docs" / name), "docs"))
for name in ("scene.html", "scene.js", "battle_lighting.js"):
    datas.append((str(root / "scripts" / "level_preview" / name), "scripts/level_preview"))

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
hiddenimports += collect_submodules("arknights_unpacker.ui")
hiddenimports += collect_submodules("fontTools.ttLib.tables")
hiddenimports += ["PIL.PngImagePlugin", "PIL.JpegImagePlugin", "PIL.BmpImagePlugin", "PIL.TgaImagePlugin", "Crypto.Cipher.AES", "bson", "flatbuffers", "numpy", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"]
preflight = os.environ.get("ARKNIGHTS_BUILD_PREFLIGHT") == "1"
entrypoint = root / "packaging" / ("preflight.py" if preflight else "entrypoint.py")
a = Analysis([str(entrypoint)], pathex=[str(root / "src")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports,
             excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "tkinter", "pytest"],
             hookspath=[], hooksconfig={}, runtime_hooks=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ArknightsUnpacker",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False, contents_directory="_internal",
          icon=str(root / "resources/ui/app-icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ArknightsUnpacker")
