"""Traceable local table location: active manifest -> IDX -> physical UnityFS -> TextAsset."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from arknights_unpacker.contracts import (DecodedTable, SourceRef, TableSourceSet, ResourceCatalog, null_progress)
from .decoder import decode_table_bytes, DECODER_VERSION
from .manifest import read_resource_manifest
from .unity import load_bundle, raw_text
from arknights_unpacker.library.discover import discover_installation, safe_path
CORE_TABLES={'character_table','skill_table','building_data','uniequip_table','battle_equip_table'}
SUPPORT_TABLES={'favor_table','gamedata_const','char_patch_table','char_meta_table','skin_table','handbook_info_table','data_version'}

def _sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def _check(cancel):
    if cancel: cancel.check()

def _table_name(value,names):
    value=Path(str(value).replace('\\','/')).name
    return next((n for n in sorted(names,key=len,reverse=True) if re.fullmatch(re.escape(n)+r'(?:[0-9a-f]+)?(?:\.bytes|\.json|\.txt)?',value)),None)

def _decode_bundle(path,targets,layer,logical_names,emit,cancel,expected=None):
    result={}
    before=path.stat()
    payload=path.read_bytes()
    sha=hashlib.sha256(payload).hexdigest()
    actual_md5=hashlib.md5(payload).hexdigest()
    if expected and (sha!=expected['sha256'] or (before.st_size,before.st_mtime_ns)!=(expected['size'],expected['mtime_ns'])):
        raise OSError('候选校验后源资源变化，拒绝解码: '+str(path))
    expected_md5=(expected or {}).get('expected_md5')
    if expected_md5 and actual_md5.lower()!=expected_md5.lower():
        raise OSError('实际解码字节与活动清单MD5不符: '+str(path))
    # UnityPy sees precisely the immutable bytes whose SHA/MD5 were checked.
    # The path is retained only as diagnostic context for callers/adapters.
    env=load_bundle(path,data=payload)
    for obj in env.objects:
        _check(cancel)
        if obj.type.name!='TextAsset': continue
        data=obj.read(); name=_table_name(data.m_Name,targets)
        if not name: continue
        emit({'kind':'progress','stage':'decode','table':name,'path':str(path)})
        raw=raw_text(data)
        if name=='data_version':
            text=raw.decode('utf-8')
            decoded={'raw':text,**{k:v.strip() for k,v in (line.split(':',1) for line in text.splitlines() if ':' in line)}}
            evidence={'format':'text','encoding':'utf-8'}
        else: decoded,evidence=decode_table_bytes(raw,name)
        evidence['decodedPayloadVerification']={'sha256':sha,'md5':actual_md5,'byteLength':len(payload),'candidateSha256Matched':expected is not None,'expectedMd5Verified':bool(expected_md5)}
        result[name]=DecodedTable(name,decoded,SourceRef(path=str(path),layer=layer,logical_name=logical_names.get(name,''),object_name=data.m_Name,path_id=str(obj.path_id),table=name,sha256=sha,decoder_version=DECODER_VERSION),evidence)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or _sha(path)!=sha:
        raise OSError('源资源在解包期间变化，拒绝采用部分表')
    return result

def locate_tables(catalog:ResourceCatalog,names:set[str])->TableSourceSet:
    """Catalog resources retain the manifest resolver's verification decisions."""
    result=TableSourceSet(version=str(catalog.manifest.get('manifestVersion','unknown')),resource_version=str(catalog.manifest.get('versionId','unknown')))
    grouped={}
    for logical,res in catalog.resources.items():
        n=_table_name(logical,names)
        if not n: continue
        if not res.path or res.status in {'missing','stale','unavailable','corrupt','not_installed','mismatch'}:
            result.diagnostics.append(f'{n}: 当前资源不可用 ({res.status})');continue
        grouped.setdefault((res.path,res.layer),{})[n]=logical
    if not grouped:
        # Catalog can intentionally expose physical resources only. Decode its active
        # IDX from the same installation, never substitute online or stale tables.
        return load_local_tables(catalog.installation.root,Path('.cache/tables'),names=names)
    for (path,layer),logical in grouped.items():
        try: result.tables.update(_decode_bundle(Path(path),set(logical),layer,logical,null_progress,None))
        except Exception as e: result.diagnostics.append(f'{path}: {type(e).__name__}: {e}')
    missing=names-result.tables.keys()
    result.complete=not missing
    result.diagnostics += [f'缺少核心表: {n}' for n in sorted(missing)]
    return result

def load_local_tables(game_root:Path,cache_dir:Path,emit=null_progress,cancel=None,*,names=None)->TableSourceSet:
    game_root=Path(game_root).resolve();cache_dir=Path(cache_dir).resolve()
    if cache_dir==game_root or game_root in cache_dir.parents: raise ValueError('表缓存不得写入游戏目录')
    names=set(names or (CORE_TABLES|SUPPORT_TABLES))
    root=game_root if (game_root/'Arknights_Data').exists() else game_root.parent if game_root.name=='Arknights_Data' else game_root
    if cache_dir==root or root in cache_dir.parents: raise ValueError('表缓存不得写入游戏目录')
    installation=discover_installation(root)
    layers={k:installation.source_roots[k] for k in ('hot','base') if k in installation.source_roots}
    stable_inputs={}
    manifests={}
    for layer,path in layers.items():
        fp=path/'hot_update_list.json'
        if fp.exists():
            before=fp.stat();payload=fp.read_bytes();after=fp.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise OSError('资源清单读取中变化')
            stable_inputs[fp]=(after.st_size,after.st_mtime_ns,hashlib.sha256(payload).hexdigest())
            manifests[layer]=json.loads(payload)
    if not manifests: raise FileNotFoundError('没有本机资源清单 hot_update_list.json')
    active=manifests.get('hot') or manifests['base']
    version=str(active.get('manifestVersion','unknown'));rv=str(active.get('versionId','unknown'))
    result=TableSourceSet(version=version,resource_version=rv)
    entries={x['name']:x for x in active.get('abInfos',[])}
    manifest_name=active.get('manifestName','')
    index_candidates=[safe_path(p,manifest_name) for p in layers.values()]
    index_path=next((p for p in index_candidates if p.is_file()),None)
    if not index_path: raise FileNotFoundError('活动IDX未安装: '+manifest_name)
    emit({'kind':'progress','stage':'index','path':str(index_path)})
    index_stat=index_path.stat();index_sha=_sha(index_path)
    index=read_resource_manifest(index_path)
    stable_inputs[index_path]=(index_stat.st_size,index_stat.st_mtime_ns,index_sha)
    grouped={}
    candidates={}
    for asset in index['assets']:
        logical=asset.get('assetName') or asset.get('path') or asset.get('name') or ''
        name=_table_name(logical,names)
        if not name: continue
        bundle_name=asset['bundle']
        if bundle_name not in entries:
            # Some indices omit suffixes; exact association is still required.
            candidate=bundle_name+'.bin'
            if candidate in entries: bundle_name=candidate
            else:
                result.diagnostics.append(f'{name}: IDX包不在活动清单: {bundle_name}');continue
        expected=entries[bundle_name]
        chosen=None
        for layer,layerpath in layers.items():
            fp=safe_path(layerpath,bundle_name)
            if not fp.is_file(): continue
            candidate_stat=fp.stat()
            size=expected.get('abSize') or expected.get('totalSize')
            if size and candidate_stat.st_size!=size: continue
            md5=expected.get('md5','')
            full_md5=bool(re.fullmatch('[0-9a-fA-F]{32}',md5))
            h=hashlib.md5();h_sha=hashlib.sha256()
            with fp.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):h.update(block);h_sha.update(block)
            candidate_after=fp.stat()
            if (candidate_stat.st_size,candidate_stat.st_mtime_ns)!=(candidate_after.st_size,candidate_after.st_mtime_ns):
                raise OSError('候选资源校验期间变化: '+str(fp))
            if full_md5 and h.hexdigest().lower()!=md5.lower(): continue
            if layer=='base' and not full_md5:
                base_entry=next((x for x in manifests.get('base',{}).get('abInfos',[]) if x['name']==bundle_name),None)
                if not base_entry or any(base_entry.get(k)!=expected.get(k) for k in ('hash','md5','abSize')): continue
            proof={'size':candidate_after.st_size,'mtime_ns':candidate_after.st_mtime_ns,'sha256':h_sha.hexdigest(),'md5':h.hexdigest(),'expected_md5':md5 if full_md5 else None}
            candidates[fp]=proof
            stable_inputs[fp]=(proof['size'],proof['mtime_ns'],proof['sha256'])
            chosen=(fp,layer);break
        if not chosen:
            result.diagnostics.append(f'{name}: 活动版本包缺失或大小/摘要不符: {bundle_name}');continue
        grouped.setdefault(chosen,{})[name]=logical
    for (fp,layer),logical in grouped.items():
        _check(cancel)
        try:
            decoded=_decode_bundle(fp,set(logical),layer,logical,emit,cancel,expected=candidates[fp])
            info=entries[fp.relative_to(layers[layer]).as_posix()]
            for t in decoded.values():
                t.field_evidence['resourceVerification']={'manifestMatch':True,'sizeMatch':True,'hashKind':'md5' if re.fullmatch('[0-9a-fA-F]{32}',info.get('md5','')) else 'short_token','hash':info.get('md5',''),'cryptographicDigestVerified':t.field_evidence['decodedPayloadVerification']['expectedMd5Verified'],'sha256':t.source.sha256}
            result.tables.update(decoded)
        except Exception as e:
            from arknights_unpacker.contracts import CancelledError
            if isinstance(e,CancelledError): raise
            result.diagnostics.append(f'{fp}: {type(e).__name__}: {e}')
    if 'data_version' in result.tables:
        result.version=str(result.tables['data_version'].data.get('VersionControl',version))
        version=result.version
    missing=CORE_TABLES.intersection(names)-result.tables.keys()
    result.complete=not missing
    result.diagnostics += [f'缺少核心表: {n}' for n in sorted(missing)]
    for path,(size,mtime,digest) in stable_inputs.items():
        now=path.stat()
        if (now.st_size,now.st_mtime_ns)!=(size,mtime) or _sha(path)!=digest:
            raise OSError('资源清单、IDX或资源包在整组表解码期间变化，拒绝建立一致快照: '+str(path))
    cache_dir.mkdir(parents=True,exist_ok=True)
    receipt={'version':version,'resource_version':rv,'manifest':str(index_path),'manifest_sha256':index_sha,'version_kind':'data_version.VersionControl' if 'data_version' in result.tables else 'manifestVersion','tables':{n:{'source':vars(t.source),'top_level_count':len(t.data) if hasattr(t.data,'__len__') else None} for n,t in result.tables.items()},'diagnostics':result.diagnostics,'complete':result.complete}
    (cache_dir/'sources.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    for n,t in result.tables.items():
        (cache_dir/(n+'.json')).write_text(json.dumps(t.data,ensure_ascii=False),encoding='utf-8',errors='backslashreplace')
        (cache_dir/(n+'.evidence.json')).write_text(json.dumps(t.field_evidence,ensure_ascii=False,indent=2),encoding='utf-8',errors='backslashreplace')
    return result
