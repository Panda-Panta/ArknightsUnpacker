"""A small semantic view shared by text, HTML and PNG renderers."""
from dataclasses import dataclass, field
import re
from typing import Any

from ..contracts import ReportDocument, as_jsonable

LABELS = {
    'profession':'职业', 'sub_profession':'分支', 'rarity':'稀有度', 'phase':'精英阶段',
    'level':'等级', 'potential':'潜能', 'trust':'信赖', 'obtainable':'可获取状态', 'appellation':'代号',
    'version':'游戏数据版本', 'resource_version':'资源版本', 'source':'来源', 'sources':'来源',
    'generated_at':'生成时间', 'template_version':'模板版本', 'evidence_boundary':'资料口径',
    'id':'ID', 'char_id':'干员ID', 'equip_id':'模组ID', 'char_name':'干员', 'name':'名称',
    'type_name':'模组类型', 'index':'技能序号', 'sp_type':'技力回复', 'trigger':'触发方式',
    'init_sp':'初始技力', 'sp_cost':'消耗技力', 'duration':'持续时间', 'duration_type':'持续类型',
    'description':'说明', 'potential_delta':'潜能增量', 'unlock_condition':'解锁条件',
    'room':'设施', 'unlock':'解锁条件', 'blackboard':'技能参数', 'diagnostics':'诊断',
    'before':'更新前', 'after':'更新后', 'kind':'变化类型', 'baseline_id':'基线快照', 'current_id':'当前快照',
    'operators':'干员变化', 'modules':'模组变化', 'changes':'更新对照', 'key':'字段', 'label':'项目',
    'base':'基础', 'module':'模组', 'value':'最终值', 'unit':'单位', 'metadata':'来源信息',
    'trait':'特性', 'talents':'天赋', 'attributes':'属性', 'phases':'模组阶段', 'pointer':'字段指针',
    'sub_profession_name':'分支', 'building_skills':'后勤技能', 'baseline_version':'更新前版本',
    'current_version':'更新后版本', 'max_charge':'最大充能次数', 'selected_module':'面板模组',
    'special_equip_description':'专属说明','special_equip':'专属模组','form_of':'原形态干员',
}

# Evidence and implementation structures remain losslessly in the JSON sidecar.
RAW_KEYS = {'metadata','field_evidence','field_sources','getter','blackboard','sources','raw_metadata','source_root',
    'input_root','game_root','installation_root','source_roots','input_roots','effects','hidden_effects',
    'token_effects','token_attributes','scope','raw_key','target','operation','talent_index','token_key',
    'raw_changed','categories','fields','numeric_level','snapshot_id','path_id','decoder_version',
    'format','states','state','dictionary','enumRepresentation','resourceVerification'}
PROFESSIONS = {'WARRIOR':'近卫','SNIPER':'狙击','TANK':'重装','MEDIC':'医疗','SUPPORT':'辅助',
    'CASTER':'术师','SPECIAL':'特种','PIONEER':'先锋','TOKEN':'召唤物','TRAP':'装置'}
ROOMS = {'CONTROL':'控制中枢','POWER':'发电站','MANUFACTURE':'制造站','DORMITORY':'宿舍',
    'MEETING':'会客室','HIRE':'办公室','TRADING':'贸易站','WORKSHOP':'加工站','TRAINING':'训练室','RECYCLE':'资源回收室'}
SP_TYPES = {'INCREASE_WITH_TIME':'自动回复','INCREASE_WHEN_ATTACK':'攻击回复',
    'INCREASE_WHEN_TAKEN_DAMAGE':'受击回复','ATTACK_OR_DAMAGE':'攻击或受击回复','NONE':'无技力回复',
    0:'无技力回复',1:'自动回复',2:'攻击回复',4:'受击回复',6:'攻击或受击回复',7:'全部回复方式'}
TRIGGERS = {'PASSIVE':'被动','MANUAL':'手动触发','AUTO':'自动触发',0:'被动',1:'手动触发',2:'自动触发'}


def label(key: str) -> str:
    return LABELS.get(key, key)


def plain(value: Any) -> str:
    if value is None:
        return '未提供'
    if value is True:
        return '是'
    if value is False:
        return '否'
    if isinstance(value, (dict, list, tuple)):
        return _readable_tree(value)
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    # Only known game formatting is removed. Unrecognized text remains visible.
    text = re.sub(r'<(?:/?(?:color|size|b|i|u|s)(?:=[^>]*)?|/?@[^>]+|/?\$[^>]+)>', '', text, flags=re.I)
    return re.sub(r'<br\s*/?>', '\n', text, flags=re.I)


@dataclass
class Block:
    title: str
    rows: list[tuple[str, str]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    cells: list[list[str]] = field(default_factory=list)
    group: str = ''
    entry_id: str = ''
    entry_title: str = ''
    stage: int | None = None


def _source_summary(value: Any) -> str:
    if not isinstance(value, dict):
        return plain(value)
    parts = []
    if value.get('table'):
        parts.append('数据表 ' + str(value['table']))
    if value.get('layer'):
        parts.append({'hot':'热更资源','base':'初始资源'}.get(value['layer'], str(value['layer'])))
    if value.get('sha256'):
        parts.append('SHA-256 ' + str(value['sha256'])[:12] + '…')
    return ' · '.join(parts) or '本地解析数据；完整来源与字段读取证据保存在JSON sidecar'


def present(key: str, value: Any) -> str:
    if key == 'source':
        return _source_summary(value)
    if key == 'profession':
        return PROFESSIONS.get(value, plain(value))
    if key == 'rarity' and isinstance(value, str) and value.startswith('TIER_'):
        return value[5:] + '星'
    if key == 'phase' and (isinstance(value, int) or str(value).startswith('PHASE_')):
        return '精英' + str(value).removeprefix('PHASE_')
    if key in {'unlock','unlock_condition'} and isinstance(value, dict):
        return '、'.join(present(k,v) + ('级' if k == 'level' else '') for k,v in value.items() if v is not None) or '无额外条件'
    if key == 'room':
        return ROOMS.get(value, plain(value))
    if key == 'sp_type':
        return SP_TYPES.get(value, '类型标识 ' + plain(value))
    if key == 'trigger':
        return TRIGGERS.get(value, plain(value))
    if key == 'duration_type':
        return {'NONE':'常规持续','AMMO':'弹药制',0:'常规持续',1:'弹药制'}.get(value, plain(value))
    if key == 'potential_delta' and isinstance(value,dict):
        names={'damage_resistance_normal':'普通目标伤害减免参数','damage_resistance_seamonster':'海怪伤害减免参数'}
        rows=[]
        for parameter,change in value.items():
            if isinstance(change,dict) and any(k in change for k in ('before','after','delta')):
                rows.append(f'{names.get(parameter,parameter)}：{plain(change.get("before"))} → {plain(change.get("after"))}（潜能增量 {plain(change.get("delta"))}）')
        return '\n'.join(rows) if rows else '无额外潜能增量'
    if key == 'kind':
        return {'added':'新增','modified':'修改','removed':'移除','form_added':'新增形态'}.get(value, plain(value))
    if key == 'diagnostics':
        return '\n'.join(str(x) for x in value) if value else '无已报告诊断'
    return plain(value)


def _rows(data: dict[str, Any], skip: set[str] | None = None) -> list[tuple[str, str]]:
    return [(label(k), present(k,v)) for k,v in data.items() if k in LABELS and k not in RAW_KEYS | (skip or set())
            and (v is not None or k in {'description','trait'}) and not (k == 'diagnostics' and not v)]


def _complete_rows(data: dict[str, Any], required: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(label(k), present(k,data.get('sub_profession_name') or data.get(k) if k=='sub_profession' else data.get(k)))
            for k in required if k not in RAW_KEYS] + _rows(data, set(required) | {'sub_profession_name'})


def _missing(profile, name: str, keys: tuple[str, ...]) -> str:
    issues = '\n'.join(str(x) for x in profile.diagnostics).lower()
    return f'{name}数据缺失或未解析；请查看诊断' if any(k.lower() in issues for k in keys) else f'无{name}（当前快照无条目）'


def _player_name(value: Any, fallback: str) -> str:
    text = plain(value).strip() if value is not None else ''
    return text or fallback


def _module_blocks(module: dict[str, Any], prefix: str = '', *, owner_id: str = '', fallback_id: str = 'module') -> list[Block]:
    module = as_jsonable(module)
    name = _player_name(module.get('name'), '未命名模组')
    title = f"{prefix}{_player_name(module.get('char_name'), '未标明干员')} · {_player_name(module.get('type_name'), '类型未提供')} · {name}"
    owner = _player_name(module.get('char_id') or owner_id, '未标明干员')
    key = _player_name(module.get('equip_id') or module.get('id'), fallback_id)
    entry = {'entry_id': f'module:{owner}:{key}', 'entry_title': title}
    blocks = [Block(title, _rows(module, {'phases'}), group='模组', **entry)]
    for phase in module.get('phases', []):
        level = str(phase.get('level', '')).strip()
        stage = int(level) if level in {'1', '2', '3'} else None
        phase_title = f'{level}级' if level and phase.get('level') is not None else '阶段未标明'
        phase_entry = {**entry, 'stage': stage}
        blocks.append(Block(f'{name} · {phase_title}',
            _complete_rows({k:v for k,v in phase.items() if k not in {'attributes','talents'}}, ('level','trait')) + _scope_rows(phase.get('scope')), group='模组', **phase_entry))
        attrs = phase.get('attributes', [])
        if attrs:
            blocks.append(Block('阶段属性', columns=['项目', '数值'], cells=[
                [plain(a.get('label', a.get('key'))), plain(a.get('value'))] for a in attrs], group='模组', **phase_entry))
        for talent in phase.get('talents', []):
            # Some module stages carry an empty implementation stub (index -1).
            # Keep raw records in JSON, and retain unresolved parameter records;
            # only a wholly empty player entry is omitted from display blocks.
            if not (_player_name(talent.get('name'), '') or _player_name(talent.get('description'), '')
                    or talent.get('potential_delta') or talent.get('blackboard')):
                continue
            blocks.append(Block('天赋：' + _player_name(talent.get('name'), '未命名天赋'), _complete_rows(talent, ('name','description','potential_delta')) + _scope_rows(talent.get('scope')), group='模组', **phase_entry))
        for effect in phase.get('token_effects', []):
            if not str(effect.get('description') or '').strip():
                continue
            blocks.append(Block('召唤物效果 · ' + _player_name(effect.get('name'), '模组强化'),
                _complete_rows(effect, ('description','potential_delta','unlock_condition')) + _scope_rows(effect.get('scope')), group='模组', **phase_entry))
        token_attributes = phase.get('token_attributes') or {}
        if isinstance(token_attributes, dict):
            for token, board in token_attributes.items():
                entries = board.items() if isinstance(board,dict) else ((x.get('key'),x.get('value')) for x in board if isinstance(x,dict)) if isinstance(board,list) else []
                rows = [(ATTRIBUTE_LABELS.get(k, str(k)),plain(v)) for k,v in entries]
                if rows:
                    blocks.append(Block('召唤物属性 · ' + _player_name(token, '未命名召唤物'), rows, group='模组', **phase_entry))
    if not module.get('phases'):
        blocks.append(Block('模组阶段', [('状态', '阶段数据未提供，请查看来源及诊断')], group='模组', **entry))
    return blocks


ATTRIBUTE_LABELS = {'atk':'攻击','def':'防御','max_hp':'生命上限','maxHp':'生命上限',
    'attack_speed':'攻击速度','magic_resistance':'法术抗性','respawn_time':'再部署时间','cost':'部署费用','block_cnt':'阻挡数'}


def _scope_rows(scope: Any) -> list[tuple[str,str]]:
    if not isinstance(scope,dict):
        return []
    names = {'validInGameTag':'玩法条件','validInMapTag':'地图条件','validModeIndices':'模式编号',
             'tokenKey':'召唤物标识','game_tag_meta':'限定玩法'}
    rows = [('适用对象','召唤物')] if scope.get('isToken') else []
    rows.extend((name,plain(scope[key])) for key,name in names.items() if scope.get(key))
    return rows


def _draft(profile) -> bool:
    if profile.metadata.get('complete') is False:
        return True
    markers = ('missing','unparsed','unresolved','unsupported','不完整','未解析','缺失','损坏','未知占位','no usable','断裂')
    return any(any(marker in str(diagnostic).lower() for marker in markers) for diagnostic in profile.diagnostics)


def semantic_blocks(document: ReportDocument) -> list[Block]:
    version_rows = _rows(document.metadata, {'changes'})
    for profile in [*document.operators, *document.modules]:
        profile_name = _player_name(profile.name, '未命名模组' if hasattr(profile, 'equip_id') else '未命名干员')
        version_rows.extend((f'{profile_name} · {label(key)}', present(key,profile.metadata.get(key)))
                            for key in ('version', 'resource_version', 'source'))
    blocks = [Block('资料口径与版本', version_rows)]
    drafts = [_player_name(profile.name, '未命名模组' if hasattr(profile, 'equip_id') else '未命名干员')
              for profile in [*document.operators,*document.modules] if _draft(profile)]
    if document.metadata.get('complete') is False or drafts:
        blocks.insert(0,Block('数据未完整解析 · 草稿', [('受影响资料','、'.join(drafts) or '当前资料'),
            ('阅读提示','部分必要数据缺失或未能解析。下方保留已确认内容，缺项不表示无技能或无效果，请同时查看诊断。')],group='草稿警告'))
    for profile in document.operators:
        blocks.append(Block(f'{_player_name(profile.name, "未命名干员")} · {_player_name(profile.char_id, "未标明干员ID")}', _complete_rows(profile.summary,
            ('profession','sub_profession','rarity','phase','level','potential','trust','obtainable','appellation')) + [('干员ID', profile.char_id)], group='概览'))
        blocks.append(Block('特性', [('说明', plain(profile.trait) or '特性未提供')], group='特性'))
        attrs = profile.attributes
        blocks.append(Block('属性与加成', columns=['项目', '最终值', '基础', '信赖', '潜能', '模组', '单位'], cells=[
            [plain(a.get('label', a.get('key')))] + [plain(a.get(k)) for k in ('value','base','trust','potential','module','unit')]
            for a in attrs] if attrs else [['属性数据未提供', '', '', '', '', '', '']], group='属性'))
        for i, skill in enumerate(profile.skills, 1):
            index = _player_name(skill.get('index'), str(i))
            name = _player_name(skill.get('name'), '未命名技能')
            key = _player_name(skill.get('id'), f'index-{index}')
            owner = _player_name(profile.char_id, '未标明干员')
            entry = {'entry_id': f'skill:{owner}:{key}', 'entry_title': name}
            blocks.append(Block(f'技能{index} · {name}', _complete_rows(skill,
                ('index','id','name','level','sp_type','trigger','init_sp','sp_cost','duration','duration_type','description')), group='技能', **entry))
            issues='\n'.join(str(d) for d in skill.get('diagnostics',[]))
            if any(marker in issues for marker in ('unresolved placeholder','non-numeric format','unsupported format')):
                board=skill.get('blackboard') or {}
                entries=board.items() if isinstance(board,dict) else ((item.get('key'),item.get('value')) for item in board if isinstance(item,dict))
                related=[(f'未解析参数 {key}',plain(value)) for key,value in entries if key and str(key) in issues]
                if related:
                    blocks.append(Block('未解析技能参数（关联诊断）',related,group='技能', **entry))
        if not profile.skills:
            blocks.append(Block('技能', [('状态', _missing(profile, '技能', ('skill', '技能')))], group='技能'))
        for talent in profile.talents:
            blocks.append(Block('天赋 · ' + _player_name(talent.get('name'), '未命名天赋'), _complete_rows(talent, ('name','description','potential_delta','unlock_condition')), group='天赋'))
        if not profile.talents:
            blocks.append(Block('天赋', [('状态', _missing(profile, '天赋', ('talent','天赋')))], group='天赋'))
        for skill in profile.building_skills:
            blocks.append(Block('后勤 · ' + _player_name(skill.get('name'), '未命名后勤技能'), _complete_rows(skill, ('name','description','room','unlock')), group='后勤'))
        if not profile.building_skills:
            blocks.append(Block('后勤技能', [('状态', _missing(profile, '后勤技能', ('building','后勤','基建')))], group='后勤'))
        blocks.append(Block('潜能提升', [(f'潜能{i + 2}', plain(value)) for i, value in enumerate(profile.potentials)]
            or [('状态', _missing(profile, '潜能提升', ('potential','潜能')))], group='潜能'))
        for index, module in enumerate(profile.modules, 1):
            blocks.extend(_module_blocks(module, owner_id=profile.char_id, fallback_id=f'index-{index}'))
        if not profile.modules:
            blocks.append(Block('模组', [('状态', _missing(profile, '模组', ('module', 'equip', '模组')))], group='模组'))
        blocks.append(Block('来源与诊断', _complete_rows(profile.metadata, ('version','resource_version','source')) + [('诊断', plain(profile.diagnostics) if profile.diagnostics else '无已报告诊断')], group='来源与诊断'))
    for index, module in enumerate(document.modules, 1):
        blocks.extend(_module_blocks(as_jsonable(module), fallback_id=f'index-{index}'))
    if document.metadata.get('changes'):
        changes = document.metadata['changes']
        blocks.append(Block('更新对照基准', _rows(changes, {'operators','modules'}), group='更新对照'))
        for category in ('operators','modules'):
            for index, change in enumerate(changes.get(category, []), 1):
                name = _player_name(change.get('name') or change.get('id') or change.get('char_id') or change.get('equip_id'), f'未命名条目{index}')
                rows = _rows(change, {'before','after','changes','difference_type'})
                for side in ('before','after'):
                    if side in change:
                        rows.append((label(side), _readable_tree(change[side])))
                blocks.append(Block(f'{label(category)} · {name}', rows, group='更新对照'))
                for field_change in change.get('changes', []):
                    field_name = _player_name(field_change.get('field'), '未标明字段')
                    if field_name in RAW_KEYS:
                        continue
                    blocks.append(Block(f'{name} · {label(field_name)}更新', [
                        ('更新前',_readable_tree(field_change.get('before'))),
                        ('更新后',_readable_tree(field_change.get('after')))], group='更新对照'))
    if not document.operators and not document.modules:
        blocks.append(Block('未选择资料', [('状态', '本报告未选择干员或模组。更新对照见下方（如有）。')]))
    return blocks


def _readable_tree(value: Any, prefix: str = '') -> str:
    if isinstance(value, dict):
        return '\n'.join(_readable_tree(v, f'{prefix}{label(k)} / ') if isinstance(v, (dict,list)) and k not in {'source','unlock','unlock_condition','potential_delta'}
                         else f'{prefix}{label(k)}：{present(k,v)}' for k,v in value.items() if k not in RAW_KEYS) or '无面向玩家的变化条目（原始字段见JSON）'
    if isinstance(value, list):
        return '\n'.join(_readable_tree(v, f'{prefix}{i+1}. ') for i,v in enumerate(value)) or '无条目'
    return prefix + plain(value)


def text_report(document: ReportDocument) -> str:
    lines = [document.title]
    for block in semantic_blocks(document):
        lines.extend(['', f'【{block.title}】'])
        lines.extend(f'{key}：{value}' for key, value in block.rows)
        if block.columns:
            lines.append(' | '.join(block.columns))
            lines.extend(' | '.join(row) for row in block.cells)
    return '\n'.join(lines) + '\n'
