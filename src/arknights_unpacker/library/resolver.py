"""Resolve the active manifest without copying or changing either source layer.

`resolve_resources` accepts a ScanSnapshot (its captured manifest and metadata),
or a GameInstallation (live metadata). `load_catalog` is the latter convenience.
A current candidate is supported by manifest fields and size, not a full MD5
verification. Short manifest tokens are preserved and never called corruption.
"""
from __future__ import annotations
import re
import stat
from pathlib import Path
from arknights_unpacker.contracts import GameInstallation, ScanSnapshot, ResourceCatalog, ResolvedResource
from .discover import safe_path, is_reparse_stat
from .manifests import read_manifest
from .classifications import classify

OPTIONAL_TYPES={'voice_cn','voice_custom','voice_en','voice_kr','voice_jp'}

def collect_manifests(installation:GameInstallation)->tuple[dict,list[str]]:
    manifests={};errors=[]
    for layer,root in installation.source_roots.items():
        path=root/'hot_update_list.json'
        if not path.is_file():continue
        try:manifests[layer]=read_manifest(path)
        except (OSError,ValueError) as exc:errors.append(str(exc))
    return manifests,errors

def _index(manifest):
    return {x['name'].replace('\\','/'):x for x in manifest.get('abInfos',[]) if isinstance(x,dict) and isinstance(x.get('name'),str)}

def _live_file_stat(folder, name, path, directories):
    """Observe each shared parent once; never follow a reparse candidate.

    This cache belongs to one catalog observation, like the captured metadata in
    the snapshot branch. It is not reused when the game is checked again.
    The relative path has already passed safe_path's syntax validation.
    """
    parts=name.split('/')
    parent=''
    for part in parts[:-1]:
        parent=(parent+'/' if parent else '')+part
        if parent not in directories:
            try:directories[parent]=(folder/parent).lstat()
            except (FileNotFoundError,NotADirectoryError):directories[parent]=None
        info=directories[parent]
        if info is not None and is_reparse_stat(info):
            raise ValueError(f'不跟随链接: {folder/parent}')
        if info is None or not stat.S_ISDIR(info.st_mode):return None
    try:info=path.lstat()
    except (FileNotFoundError,NotADirectoryError):return None
    if is_reparse_stat(info):raise ValueError(f'不跟随链接: {path}')
    return info if stat.S_ISREG(info.st_mode) else None

def resolve_resources(source:ScanSnapshot|GameInstallation)->ResourceCatalog:
    if isinstance(source,ScanSnapshot):
        captured=source.manifest_versions.get('installation',{})
        root=Path(source.root)
        installation=GameInstallation(root,source.profile_id,Path(captured['base_root']) if captured.get('base_root') else root/'Arknights_Data/StreamingAssets/AB/Windows',Path(captured['hot_root']) if captured.get('hot_root') else root/'Arknights_Data/PersistentData/Bundles',locale=captured.get('locale','unknown'))
        manifests=source.manifest_versions.get('manifests',{})
        errors=list(source.errors)
        records={f.path.casefold():f for f in source.files}
    else:
        installation=source;manifests,errors=collect_manifests(installation);records=None
    catalog=ResourceCatalog(installation,diagnostics=errors)
    active_layer='hot' if 'hot' in manifests else 'base'
    active=manifests.get(active_layer,{})
    catalog.manifest=active
    if not active:
        catalog.diagnostics.append('没有可用活动清单，版本覆盖未知')
        return catalog
    base_entries=_index(manifests.get('base',{}))
    active_entries=_index(active)
    source_roots=[(layer,folder,folder.relative_to(installation.root).as_posix())
                  for layer,folder in installation.source_roots.items()]
    directories={layer:{} for layer,_,_ in source_roots}
    for name,item in active_entries.items():
        token=str(item.get('md5',''))
        kind='md5' if re.fullmatch('[0-9a-fA-F]{32}',token) else 'short_token' if re.fullmatch('[0-9a-fA-F]{4}',token) else 'unknown'
        result=ResolvedResource(name,None,expected_hash=token,category=classify(name,'base'),metadata={'manifest_entry':item,'active_layer':active_layer,'hash_kind':kind,'content_verified':False,'candidates':[]})
        candidates=[]
        try:
            for layer,folder,prefix in source_roots:
                p=safe_path(folder,name,check_links=False)
                relative=name if prefix=='.' else prefix+'/'+name
                if records is not None:
                    rec=records.get(relative.casefold())
                    if rec is None:continue
                    size=rec.size;error=rec.error
                else:
                    info=_live_file_stat(folder,name,p,directories[layer])
                    if info is None:continue
                    size=info.st_size;error=None
                candidate={'path':str(p),'layer':layer,'size':size,'error':error}
                candidates.append(candidate)
        except (OSError,ValueError) as exc:
            catalog.diagnostics.append(str(exc));continue
        result.metadata['candidates']=candidates
        chosen=None;stale=False;wrong_size=False
        for candidate in sorted(candidates,key=lambda c:c['layer']!='hot'):
            layer=candidate['layer']
            if candidate['error']:continue
            # A base file may only stand for the active version when source
            # manifest evidence agrees. Never silently reuse an old base.
            base_item=base_entries.get(name,{})
            same_base=(layer=='base' and base_item.get('md5')==item.get('md5') and base_item.get('abSize')==item.get('abSize'))
            if layer=='base' and active_layer=='hot' and not same_base:
                stale=True;continue
            expected_size=item.get('abSize')
            if expected_size is not None and candidate['size']!=expected_size:
                wrong_size=True;continue
            chosen=candidate;break
        if chosen:
            result.path=chosen['path'];result.layer=chosen['layer'];result.size=chosen['size']
            result.status='current' if kind=='md5' else 'unverified'
            result.metadata['verification']='manifest_fields_and_size' if kind=='md5' else 'short_token_not_content_digest'
        elif stale:
            result.status='stale'
        elif wrong_size:
            result.status='incomplete'
        elif not candidates and item.get('type') in OPTIONAL_TYPES:
            result.status='not_installed_optional'
        else:result.status='missing'
        catalog.resources[name]=result
    return catalog

def load_catalog(installation:GameInstallation)->ResourceCatalog:
    return resolve_resources(installation)
