"""Physical changes with uncertainty retained rather than invented history."""
from arknights_unpacker.contracts import ScanSnapshot,FileChangeSet,FileChange

def compare_files(old:ScanSnapshot|None,new:ScanSnapshot)->FileChangeSet:
    result=FileChangeSet(old.snapshot_id if old else None,new.snapshot_id)
    if old is None:
        result.diagnostics.append('首次扫描建立基线，首次发现不等于新增或最近发布');return result
    if old.profile_id!=new.profile_id:
        result.diagnostics.append('安装位置不同，不可比较');return result
    if not old.complete or not new.complete:
        result.diagnostics.append('扫描不完整，不能确认新增、修改或删除；完整基线保持不变');return result
    if old.options.get('resource_only',False)!=new.options.get('resource_only',False):
        result.diagnostics.append('扫描范围不同，不可推断文件删除');return result
    before={f.path.casefold():f for f in old.files};after={f.path.casefold():f for f in new.files}
    for key in sorted(before.keys()|after.keys()):
        a=before.get(key);b=after.get(key)
        if a is None:kind='added'
        elif b is None:kind='removed'
        elif a.error or b.error:
            result.diagnostics.append(f'无法确认文件变化: {b.path}');continue
        elif a.sha256 is not None and b.sha256 is not None and a.sha256!=b.sha256:kind='modified'
        elif (a.size,a.mtime_ns)!=(b.size,b.mtime_ns):
            kind='metadata_only' if a.sha256 is not None and a.sha256==b.sha256 else 'unverified_change'
        else:continue
        result.changes.append(FileChange(kind,(b or a).path,a,b))
    result.diagnostics.append(f'变化在扫描区间 {old.started_at} 至 {new.started_at} 首次观察；实际写入时间可能未知')
    return result
