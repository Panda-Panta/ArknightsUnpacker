"""Read-only scans with stable full streaming digests and explicit coverage."""
from __future__ import annotations
import hashlib
import math
import os
import time
import uuid
from pathlib import Path
from arknights_unpacker.contracts import GameInstallation,ScanSnapshot,ScanOptions,FileRecord,CancelToken,CancelledError,null_progress,as_jsonable
from .discover import discover_installation,is_reparse
from .classifications import classify
from .resolver import collect_manifests

CHUNK_SIZE=1024*1024

def validate_hours(hours:float)->float:
    if not math.isfinite(hours) or hours<=0:raise ValueError('时间窗口必须是有限的正数')
    return hours

def _location(path:Path,installation:GameInstallation):
    for layer,folder in installation.source_roots.items():
        if path.is_relative_to(folder):return layer,path.relative_to(folder).as_posix()
    return 'other',path.relative_to(installation.root).as_posix()

def _digest(path:Path,token:CancelToken,emit)->tuple[str,os.stat_result]:
    for attempt in range(2):
        before=path.stat();digest=hashlib.sha256()
        with path.open('rb') as stream:
            while data:=stream.read(CHUNK_SIZE):
                token.check();digest.update(data);emit({'phase':'hash','path':str(path),'bytes_read':len(data)})
        after=path.stat()
        if (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns):return digest.hexdigest(),after
    raise OSError(f'unstable: 文件在读取期间变化: {path}')

def scan_installation(source:GameInstallation|ScanSnapshot,options:ScanOptions|None=None,emit=null_progress,cancel:CancelToken|None=None,*,baseline:ScanSnapshot|None=None)->ScanSnapshot:
    options=options or ScanOptions();validate_hours(options.window_hours)
    if isinstance(source,ScanSnapshot):baseline=baseline or source;installation=discover_installation(source.root)
    else:installation=source
    if baseline is not None and (baseline.profile_id!=installation.profile_id or not baseline.complete):
        raise ValueError('基线必须来自同一安装位置的完整扫描')
    token=cancel or CancelToken();started=time.time()
    snapshot=ScanSnapshot(uuid.uuid4().hex,installation.profile_id,str(installation.root),started,started,baseline_id=baseline.snapshot_id if baseline else None,options=as_jsonable(options))
    old={f.path.casefold():f for f in baseline.files} if baseline else {}
    manifests,errors=collect_manifests(installation)
    snapshot.manifest_versions={'manifests':manifests,'installation':{'base_root':str(installation.base_root) if installation.base_root else None,'hot_root':str(installation.hot_root) if installation.hot_root else None,'locale':installation.locale}}
    snapshot.errors.extend(errors)
    changed_logicals=set()
    if baseline is not None:
        prior_manifests=baseline.manifest_versions.get('manifests',{})
        for layer,manifest in manifests.items():
            previous={x.get('name'):x for x in prior_manifests.get(layer,{}).get('abInfos',[])}
            for item in manifest.get('abInfos',[]):
                if previous.get(item.get('name'))!=item:
                    changed_logicals.add(str(item.get('name','')).replace('\\','/'))
    # Core data is carried by anonymous bundles/IDX; manifest and config are
    # also hashed on every quick scan. Other newly discovered files are hashed
    # after an established baseline; the first inventory is explicitly unknown.
    roots=list(installation.source_roots.values()) if options.resource_only else [installation.root]
    stack=list(roots)
    try:
        token.check()
        while stack:
            folder=stack.pop();token.check()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        token.check();path=Path(entry.path)
                        try:
                            if is_reparse(path):
                                snapshot.errors.append(f'已跳过链接/reparse: {path}');continue
                            if entry.is_dir(follow_symlinks=False):stack.append(path);continue
                            if not entry.is_file(follow_symlinks=False):continue
                            info=entry.stat(follow_symlinks=False)
                            layer,logical=_location(path,installation)
                            relative=path.relative_to(installation.root).as_posix()
                            before=old.get(relative.casefold())
                            record=FileRecord(relative,info.st_size,info.st_mtime_ns,path.suffix.lower(),layer,classify(logical,layer),first_seen_at=(before.first_seen_at if before and before.first_seen_at is not None else started))
                            metadata_changed=before is not None and (before.size,before.mtime_ns)!=(info.st_size,info.st_mtime_ns)
                            core=layer in ('base','hot') and (path.suffix.lower() in ('.idx','.json') or logical.startswith(('anon/','config/')))
                            # No digest on an unchanged ordinary file is an intentional
                            # fast-inventory state, not failed work to retry. Otherwise
                            # scan two silently turns a metadata baseline into a full
                            # installation hash. Only explicit failed digest states retry.
                            retry_hash=before is not None and before.hash_status in ('error','unstable')
                            needs_hash=options.strict or core or metadata_changed or logical in changed_logicals or (baseline is not None and before is None) or retry_hash
                            # SDK/account/log files are metadata-only even in strict
                            # scans: strict hashes all selected game resource files.
                            if layer=='other':needs_hash=False
                            if needs_hash:
                                try:
                                    record.sha256,after=_digest(path,token,emit)
                                    record.size=after.st_size;record.mtime_ns=after.st_mtime_ns;record.hash_status='verified'
                                except OSError as exc:record.error=str(exc);record.hash_status='unstable' if 'unstable:' in str(exc) else 'error';snapshot.errors.append(str(exc))
                            elif before:
                                record.sha256=before.sha256;record.hash_status='metadata_unchanged'
                            snapshot.files.append(record)
                            emit({'phase':'scan','files':len(snapshot.files),'path':relative})
                        except OSError as exc:snapshot.errors.append(f'{path}: {exc}')
            except OSError as exc:snapshot.errors.append(f'{folder}: {exc}')
        end_manifests,end_errors=collect_manifests(installation)
        snapshot.errors.extend(end_errors)
        if {k:v['_source']['sha256'] for k,v in manifests.items()}!={k:v['_source']['sha256'] for k,v in end_manifests.items()}:
            snapshot.errors.append('unstable: 资源清单在扫描期间变化')
    except CancelledError:snapshot.errors.append('任务已取消')
    snapshot.complete=not snapshot.errors
    snapshot.finished_at=time.time();snapshot.files.sort(key=lambda r:r.path.casefold())
    return snapshot

def recent_files(snapshot:ScanSnapshot,hours:float=24)->list[FileRecord]:
    validate_hours(hours);end_ns=int(snapshot.started_at*1e9);start_ns=end_ns-int(hours*3600*1e9)
    return [f for f in snapshot.files if start_ns<=f.mtime_ns<=end_ns]
