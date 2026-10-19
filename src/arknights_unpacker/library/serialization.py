"""Explicit JSON snapshots. Large decoded tables are serialized once per save."""
from __future__ import annotations
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from arknights_unpacker.contracts import ScanSnapshot,FileRecord,GameDataSnapshot

def scan_from_dict(value:dict)->ScanSnapshot:
    value=dict(value);value['files']=[FileRecord(**item) for item in value.get('files',[])]
    return ScanSnapshot(**value)

def data_from_dict(value:dict)->GameDataSnapshot:
    return GameDataSnapshot(**value)

def _encode(value):
    if is_dataclass(value):return {f.name:getattr(value,f.name) for f in fields(value)}
    if isinstance(value,Path):return str(value)
    if isinstance(value,Enum):return value.value
    raise TypeError(f'不能序列化 {type(value).__name__}')

def dumps_snapshot(snapshot:ScanSnapshot|GameDataSnapshot)->str:
    # The encoder walks the original tables; dataclasses.asdict would deepcopy
    # the entire table graph before encoding it.
    return json.dumps({'kind':'scan' if isinstance(snapshot,ScanSnapshot) else 'data','version':1,'snapshot':snapshot},default=_encode,ensure_ascii=False,separators=(',',':'))

def loads_snapshot(raw:str)->ScanSnapshot|GameDataSnapshot:
    envelope=json.loads(raw)
    if envelope.get('version')!=1:raise ValueError('不支持的快照协议版本')
    if envelope.get('kind')=='scan':return scan_from_dict(envelope['snapshot'])
    if envelope.get('kind')=='data':return data_from_dict(envelope['snapshot'])
    raise ValueError('未知快照类型')

def dump_snapshot(snapshot:ScanSnapshot|GameDataSnapshot,path:str|Path)->Path:
    destination=Path(path);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(dumps_snapshot(snapshot),encoding='utf8');return destination

def load_snapshot(path:str|Path)->ScanSnapshot|GameDataSnapshot:
    return loads_snapshot(Path(path).read_text(encoding='utf-8-sig'))
