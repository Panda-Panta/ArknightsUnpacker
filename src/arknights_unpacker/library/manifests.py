"""Stable JSON manifest reads preserving all source fields."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .discover import is_reparse

def read_manifest(path:Path)->dict:
    if is_reparse(path):raise ValueError(f'不跟随清单链接: {path}')
    before=path.stat();raw=path.read_bytes();after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise OSError(f'清单扫描期间发生变化: {path}')
    data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,dict) or not isinstance(data.get('abInfos'),list):raise ValueError(f'无效资源清单: {path}')
    if any(not isinstance(item,dict) or not isinstance(item.get('name'),str) for item in data['abInfos']):
        raise ValueError(f'资源清单包含无效条目: {path}')
    data=dict(data);data['_source']={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'mtime_ns':after.st_mtime_ns}
    return data
