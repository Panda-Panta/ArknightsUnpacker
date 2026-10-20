from __future__ import annotations

import json
import os
from contextlib import closing
import hashlib
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
import uuid


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def default_data_root() -> Path:
    """Keep portable state beside the program, independent of its launch cwd."""
    program_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    return program_root / "data"


def legacy_data_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ArknightsUnpacker"


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _resume_legacy_import(target: Path, journal: Path) -> None:
    """Finish a prepared import without replacing any independently changed file."""
    plan = json.loads(journal.read_text(encoding='utf-8'))
    stage_name = plan.get('staging', '')
    if plan.get('version') != 1 or not re.fullmatch(r'\.legacy-import-[0-9a-f]{32}', stage_name):
        raise ValueError('旧数据迁入记录格式无效，请保留该目录并使用 --data-dir 选择另一目录。')
    staging = target / stage_name
    files = plan.get('files')
    if not isinstance(files, dict):
        raise ValueError('旧数据迁入记录缺少文件清单。')
    for name, expected in files.items():
        relative = Path(name)
        allowed = name in {'settings.json', 'catalog.sqlite3'} or (
            len(relative.parts) == 2 and relative.parts[0] in {'queue', 'history'}
            and relative.suffix.casefold() in {'.json', '.jsonl'})
        if not allowed or relative.is_absolute() or '..' in relative.parts:
            raise ValueError('旧数据迁入记录包含无效路径。')
        destination, prepared = target / relative, staging / relative
        if destination.exists():
            if destination.is_file() and _file_digest(destination) == expected:
                continue
            raise FileExistsError(f'旧数据迁入尚未完成，目标文件已有不同内容，已保留且停止迁入：{destination}。请保留原目录或使用 --data-dir。')
        if not prepared.is_file() or _file_digest(prepared) != expected:
            raise OSError(f'旧数据迁入暂存文件缺失或变化，已停止迁入并保留原数据：{prepared}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # On Windows rename fails if a destination already exists. A complete
        # file is visible on either side of a process exit, never a partial copy.
        os.rename(prepared, destination)
    journal.unlink()
    if staging.exists():
        shutil.rmtree(staging)  # This is the private directory created for this import.


def migrate_legacy_data(target: Path) -> bool:
    """Import old user state once; never overwrite portable state or remove old files.

    SQLite's backup API includes committed WAL pages. Large worker scratch and
    decoded-table caches stay in the old directory; task records retain their
    original explicit receipt/output locations.
    """
    target = target.expanduser().resolve()
    journal = target / '.legacy-import.json'
    if journal.exists():
        _resume_legacy_import(target, journal)
        return True
    source = legacy_data_root().expanduser().resolve()
    if source == target or not source.is_dir():
        return False
    state_names = ("settings.json", "catalog.sqlite3", "queue", "history")
    if any((target / name).exists() for name in state_names):
        return False
    if not any((source / name).exists() for name in state_names):
        return False
    def copy_new(old: Path, new: Path):
        new.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with old.open("rb") as incoming, new.open("xb") as outgoing:
                created = True
                shutil.copyfileobj(incoming, outgoing)
        except BaseException:
            if created:
                new.unlink(missing_ok=True)
            raise

    def prepare(staging: Path):
        old_db = source / "catalog.sqlite3"
        if old_db.is_file():
            with closing(sqlite3.connect(old_db.as_uri() + "?mode=ro", uri=True)) as old:
                with closing(sqlite3.connect(staging / old_db.name)) as new:
                    old.backup(new)
        settings = source / "settings.json"
        if settings.is_file():
            copy_new(settings, staging / settings.name)
        for name in ("queue", "history"):
            folder = source / name
            if folder.is_dir():
                for old in folder.iterdir():
                    if old.is_file() and old.suffix.casefold() in {".json", ".jsonl"}:
                        copy_new(old, staging / name / old.name)

    # The normal first launch publishes the complete prepared directory in one
    # rename, so a killed process cannot expose only the database or settings.
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.legacy-import-', dir=target.parent) as private:
            staging = Path(private)
            prepare(staging)
            os.rename(staging, target)
        return True

    # Existing directories may contain user files. Preserve them in place and
    # retain a prepared manifest before publishing any state. A later launch
    # resumes exact, hashed files; a changed destination is never overwritten.
    staging = target / ('.legacy-import-' + uuid.uuid4().hex)
    staging.mkdir()
    try:
        prepare(staging)
        files = {path.relative_to(staging).as_posix(): _file_digest(path)
                 for path in staging.rglob('*') if path.is_file()}
        atomic_json(journal, {'version': 1, 'staging': staging.name, 'source': str(source), 'files': files})
        _resume_legacy_import(target, journal)
    except BaseException:
        if not journal.exists() and staging.exists():
            shutil.rmtree(staging)
        raise
    return True


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
