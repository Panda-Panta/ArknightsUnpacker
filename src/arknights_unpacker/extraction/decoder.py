"""Loss-aware FlatBuffers adapter for pinned PC schemas, plus JSON/AES text assets."""
from __future__ import annotations
import importlib
import json
import math
import inspect
import re
from functools import lru_cache
from pathlib import Path
import sys

from arknights_unpacker.paths import resource_root
VENDOR_ROOT = resource_root() / 'vendor'
if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))
DECODER_VERSION = 'pc-fbs-161d5e2-normalize-v1'

@lru_cache(maxsize=256)
def schema(name):
    if not name.replace('_', '').isalnum():
        raise ValueError('Invalid schema name')
    return importlib.import_module('ark_fbs.CN.' + name)

@lru_cache(maxsize=1024)
def _fields(cls):
    result=[]
    for name in dir(cls):
        if name.startswith('_') or name.startswith('GetRootAs') or name in ('Init','Clear','IsNone') or name.endswith(('Length','IsNone','AsNumpy')):
            continue
        fun=getattr(cls,name)
        if callable(fun):
            result.append(name)
    return tuple(result)

@lru_cache(maxsize=4096)
def _field_slot(cls,name):
    try:
        match=re.search(r'\.Offset\((\d+)\)',inspect.getsource(getattr(cls,name)))
        return int(match[1]) if match else None
    except (OSError,TypeError):return None

def normalize_flatbuffer(obj):
    """Keep empty vectors and absent/null fields distinct; dictionary keys stay exact.

    Evidence uses wildcard vector paths to remain bounded even on large tables.
    Numeric enum values remain numeric because generated schemas have no enum symbols.
    """
    evidence={}
    def literal(value,path):
        if isinstance(value,bytes): return value.decode('utf-8',errors='surrogateescape')
        if value is None or isinstance(value,(str,int,bool)): return value
        if isinstance(value,float):
            # Seven significant decimal digits recover the serialized float32 meaning.
            return float(format(value,'.7g')) if math.isfinite(value) else None
        if hasattr(value,'_tab') or _fields(type(value)):
            if type(value).__name__.startswith('dict__') and hasattr(value,'Key') and hasattr(value,'Value'):
                key=literal(value.Key(),path)
                if hasattr(value,'ValueLength'):
                    val=[literal(value.Value(i),path+'/*') for i in range(value.ValueLength())]
                else: val=literal(value.Value(),path)
                return key,val
            result={}
            for name in _fields(type(value)):
                key=name[0].lower()+name[1:]
                fieldpath=path+'/'+key
                getter=getattr(value,name)
                length=getattr(value,name+'Length',None)
                absent=getattr(value,name+'IsNone',None)
                if length:
                    count=length()
                    is_dict=any(n.startswith('dict__') for n in getattr(getter,'__func__',getter).__code__.co_names)
                    state='absent_vector' if absent and absent() else ('empty_vector' if count==0 else 'vector')
                    evidence.setdefault(fieldpath,{'getter':type(value).__name__+'.'+name,'states':[],'state':state,'dictionary':is_dict})
                    if state not in evidence[fieldpath]['states']: evidence[fieldpath]['states'].append(state)
                    if state=='absent_vector': result[key]=None
                    elif is_dict:
                        mapped={}
                        for i in range(count):
                            k,v=literal(getter(i),fieldpath+'/*')
                            if str(k) in mapped: raise ValueError('Duplicate FlatBuffers dictionary key at '+fieldpath+': '+str(k))
                            mapped[str(k)]=v
                        result[key]=mapped
                    else: result[key]=[literal(getter(i),fieldpath+'/*') for i in range(count)]
                else:
                    raw=getter()
                    slot=_field_slot(type(value),name)
                    present=bool(value._tab.Offset(slot)) if slot is not None and hasattr(value,'_tab') else None
                    state='null' if raw is None else 'present' if present else 'default_from_absent_field' if present is False else 'value'
                    entry=evidence.setdefault(fieldpath,{'getter':type(value).__name__+'.'+name,'slot':slot,'states':[],'state':state})
                    if state not in entry['states']:entry['states'].append(state)
                    result[key]=literal(raw,fieldpath)
            return result
        raise TypeError('Unsupported FlatBuffers value '+str(type(value)))
    return literal(obj,''), evidence

def decode_table_bytes(raw:bytes,name:str):
    stripped=raw.lstrip()
    if stripped[:1] in (b'{',b'['):
        try: return json.loads(raw), {'format':'json','fieldCase':'native'}
        except (UnicodeError,json.JSONDecodeError): pass
    module=schema(name)
    if len(raw)<132: raise ValueError('TextAsset too short for signed FlatBuffers')
    root=module.ROOT_TYPE.GetRootAs(raw[128:],0)
    profile=None
    if name=='building_data':
        root,profile=_adapt_pc_building(root)
    data,evidence=normalize_flatbuffer(root)
    if profile: evidence['$schemaProfile']=profile
    wrappers={'character_table':'characters','skill_table':'skills','battle_equip_table':'equips','token_table':'characters'}
    if name in wrappers:
        key=wrappers[name]
        if key not in data:
            if len(data)!=1: raise ValueError('Unexpected root fields '+str(list(data)))
            key=next(iter(data))
        data=data[key]
    return data, {'format':'flatbuffers','schemaCommit':'161d5e229916d7193364983396076556fbeaa549','fields':evidence,'enumRepresentation':'raw-integer'}

def decode_text_bytes(raw:bytes,name:str):
    try:
        return decode_table_bytes(raw,name)
    except ModuleNotFoundError:
        pass
    stripped=raw.lstrip()
    if stripped[:1] in (b'{',b'['):
        try: return json.loads(raw),{'format':'json'}
        except (UnicodeError,json.JSONDecodeError): pass
    # Ark-Unpacker fixed MASK_V2 algorithm; this branch has no schema guess.
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    mask=b'UITpAi82pHAWwnzqHRMCwPonJLIB3WCl'
    signed=raw[128:]
    if len(signed)<32 or (len(signed)-16)%16: raise ValueError('Not an AES-CBC signed TextAsset')
    iv=bytes(a^b for a,b in zip(signed[:16],mask[16:]))
    decoded=unpad(AES.new(mask[:16],AES.MODE_CBC,iv).decrypt(signed[16:]),16)
    try: return json.loads(decoded),{'format':'aes-json'}
    except (UnicodeError,json.JSONDecodeError):
        import bson
        return bson.loads(decoded),{'format':'aes-bson'}


class _PCBuildingRootTable:
    """PC V078 inserts one root slot before Chars relative to pinned CN schema."""
    def __init__(self,table): self.table=table
    def __getattr__(self,name): return getattr(self.table,name)
    def Offset(self,slot): return self.table.Offset(slot+2 if slot>=124 else slot)

def _adapt_pc_building(root):
    # Validate semantic signatures at both shifted dictionary slots before applying.
    import flatbuffers.table
    def first_key(slot):
        t=root._tab;o=t.Offset(slot)
        if not o or not 0<t.VectorLen(o)<10000: return ''
        entry=flatbuffers.table.Table(t.Bytes,t.Indirect(t.Vector(o)))
        return entry.String(entry.Pos+entry.Offset(4)).decode('utf-8')
    try:
        if first_key(124).startswith('char_'): return root,None
    except Exception: pass
    try:
        if not first_key(126).startswith('char_') or not any(c in first_key(128) for c in ('[','_')):
            raise ValueError('PC building schema signature is not recognized')
    except Exception as e:
        raise ValueError('PC building schema signature is not recognized') from e
    root._tab=_PCBuildingRootTable(root._tab)
    return root,{'profile':'PC-V078-building-root-v1','validation':'chars@126 char_ key and buffs@128 buff key','rootOffsetMapping':'known CN root slots >=124 use PC slot +2','unknownPcRootSlots':[124,172,174,176,178],'unknownFieldsPreservedInRawSource':True}
