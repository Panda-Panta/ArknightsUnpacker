"""Versioned display labels; these labels never determine a decoder."""
import json
from arknights_unpacker.paths import resource_root

_RULES_PATH=resource_root()/'resources/folder_rules.json'
_RULES=json.loads(_RULES_PATH.read_text(encoding='utf-8-sig'))

def classify(relative: str, layer: str='other') -> str:
    p=relative.replace('\\','/').lower().strip('/')
    if layer in ('base','hot'):
        if p.endswith('.idx'):return '资源索引（格式待解析）'
        if p in ('hot_update_list.json','persistent_res_list.json'):return '资源清单'
        for prefix,label in sorted(_RULES['specific'].items(),key=lambda x:-len(x[0])):
            if p==prefix or p.startswith(prefix+'/'):return label
        return _RULES['resource'].get(p.split('/')[0],'未知用途')
    first=p.split('/')[0]
    if first in _RULES['system']:return _RULES['system'][first]
    if first=='arknights_data':
        if '/plugins/' in p:return 'Unity原生插件／诊断组件'
        if '/il2cpp_data/' in p:return 'IL2CPP运行数据'
        if '/resources/' in p:return 'Unity内置资源'
        if '/persistentdata/' in p:return '下载状态／缓存'
        return 'Unity运行资源与配置'
    if first in ('arknights.exe','unityplayer.dll','gameassembly.dll'):return '游戏入口／运行库'
    if first.startswith(('game_files','package_files','verify_files','new_game_files')):return '启动器安装／校验清单候选'
    return '未知用途'
