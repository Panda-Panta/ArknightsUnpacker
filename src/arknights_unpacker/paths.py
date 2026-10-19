from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def default_data_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArknightsUnpacker"


def validate_output(path: Path | str, game_root: Path | str | None = None) -> Path:
    resolved = Path(path).expanduser().resolve()
    if game_root:
        source = Path(game_root).resolve()
        if resolved == source or source in resolved.parents:
            raise ValueError("输出目录不能位于游戏文件夹内，请选择独立目录。")
    return resolved


def validate_data_root(path: Path | str) -> Path:
    """Reject a game location before creating SQLite, caches or settings there."""
    resolved = Path(path).expanduser().resolve()
    for ancestor in (resolved, *resolved.parents):
        try:
            loose_resources = ancestor.is_dir() and any(
                entry.is_file() and entry.suffix.casefold() in {".ab", ".idx"}
                for entry in ancestor.iterdir())
        except OSError:
            loose_resources = False
        if ((ancestor / "Arknights_Data").is_dir()
                or ancestor.name.casefold() == "arknights_data"
                or (ancestor / "hot_update_list.json").is_file()
                or loose_resources):
            raise ValueError("运行数据目录不能位于游戏文件夹内，请选择独立目录。")
    return resolved


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
