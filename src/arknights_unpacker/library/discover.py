"""Read-only installation detection. No linked/reparse directories are followed."""
from __future__ import annotations
import hashlib
import os
import stat
from pathlib import Path
from arknights_unpacker.contracts import GameInstallation

BASE_PARTS = ('Arknights_Data','StreamingAssets','AB','Windows')
HOT_PARTS = ('Arknights_Data','PersistentData','Bundles')

def is_reparse(path: Path) -> bool:
    return is_reparse_stat(path.lstat())

def is_reparse_stat(info: os.stat_result) -> bool:
    """Recognize links and Windows junctions from no-follow metadata."""
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0) & 0x400)

def safe_path(root: Path, relative: str, *, check_links: bool = True) -> Path:
    relative=relative.replace('\\','/')
    parts=relative.split('/')
    if not relative or any(p in ('','..','.') or ':' in p for p in parts) or relative.startswith('/'):
        raise ValueError(f'不安全的资源路径: {relative}')
    p=root
    for part in parts:
        p=p/part
        if check_links and p.exists() and is_reparse(p):raise ValueError(f'不跟随链接: {p}')
    return p

def discover_installation(root: str | Path) -> GameInstallation:
    supplied=Path(root).absolute()
    # Check ancestors before resolve: resolving first would hide a link supplied as input.
    for part in [supplied,*supplied.parents]:
        if part.exists() and is_reparse(part):raise ValueError(f'不跟随链接目录: {part}')
    root=supplied.resolve()
    if not root.is_dir():raise ValueError(f'游戏目录不存在: {root}')
    if root.name.casefold() == 'arknights_data' and ((root/'StreamingAssets/AB/Windows').is_dir() or (root/'PersistentData/Bundles').is_dir()):
        root=root.parent
    base=root.joinpath(*BASE_PARTS); hot=root.joinpath(*HOT_PARTS)
    if not base.is_dir() and not hot.is_dir():
        # A resource-only folder is intentionally supported, but an arbitrary folder is not.
        if (root/'hot_update_list.json').is_file() or any(p.is_file() and not is_reparse(p) and p.suffix.lower() in ('.ab','.idx') for p in root.iterdir()):base=root
        else:raise ValueError('未找到资源层；请选择游戏根目录或包含 hot_update_list.json 的资源目录')
    base=base if base.is_dir() else None;hot=hot if hot.is_dir() else None
    for layer in (base,hot):
        if layer is not None:
            rel=layer.relative_to(root)
            safe_path(root,rel.as_posix()) if rel.parts else None
    normalized=os.path.normcase(str(root))
    profile=hashlib.sha256(('pc|unknown|'+normalized).encode('utf8')).hexdigest()[:24]
    return GameInstallation(root,profile,base,hot,locale='unknown',diagnostics=['区服／语言未从可信配置确认'])
