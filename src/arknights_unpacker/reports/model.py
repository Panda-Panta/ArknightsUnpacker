"""A small semantic view shared by text, HTML and PNG renderers."""
from dataclasses import dataclass, field
import json
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
    'summary':'基本信息', 'skills':'技能', 'potentials':'潜能提升', 'scope':'适用条件',
    'token_attributes':'召唤物属性', 'token_effects':'召唤物效果',
}

# Evidence and implementation structures remain losslessly in the JSON sidecar.
RAW_KEYS = {'metadata','field_evidence','field_sources','getter','blackboard','sources','raw_metadata','source_root',
    'input_root','game_root','installation_root','source_roots','input_roots','effects','hidden_effects',
    'token_effects','token_attributes','scope','raw_key','target','operation','talent_index','token_key',
    'raw_changed','categories','fields','numeric_level','snapshot_id','path_id','decoder_version',
    'format','states','state','dictionary','enumRepresentation','resourceVerification',
    'comparison','comparison_build', 'id','char_id','equip_id','form_of','source','diagnostics',
    'version','resource_version','generated_at','template_version','evidence_boundary',
    'baseline_id','current_id','baseline_version','current_version','pointer','sha256','path',
    'skill_id','skillId','equipId','charId','tokenKey','difference_type','slot'}
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
    kind: str = ''
    notes: list[tuple[str, str]] = field(default_factory=list)


def _terminology_rows(effects):
    rows = []
    for effect in effects:
        definitions = [*(effect.get('term_definitions') or []),
                       *((effect.get('comparison') or {}).get('original_term_definitions') or [])]
        for definition in definitions:
            term = plain(definition.get('term', '')).strip()
            text = plain(definition.get('description', '')).strip()
            if term and text and (term, text) not in rows:
                rows.append((term, text))
    return rows


def _known_text(value: Any, fallback: str) -> str:
    text = plain(value).strip() if value is not None else ''
    return text if re.search(r'[\u3400-\u9fff]', text) else fallback


def _effect_text(value: Any) -> str:
    if value is None or not str(value).strip():
        return '效果未确认'
    return re.sub(r'\{[^{}]*\}', '（效果未确认）', plain(value))


def _potential_text(effect: dict[str, Any]) -> str:
    delta = effect.get('potential_delta')
    if not delta:
        return ''
    if not isinstance(delta, dict):
        return plain(delta)
    description = _effect_value(effect)
    annotated_description = False
    evidence = [(change.get('metadata') or {}).get('description_evidence') if isinstance(change, dict) else None
                for change in delta.values()]
    if evidence and isinstance(evidence[0], dict) and all(item == evidence[0] for item in evidence):
        source = evidence[0]
        before, after = source.get('before'), source.get('after')
        if before and after and description == after:
            # Reversing every official potential annotation must reproduce the
            # entire baseline. One annotation cannot conceal another change.
            if source.get('annotated'):
                annotated_description = True
            else:
                return f'基础天赋：{_effect_text(before)}\n当前潜能：{_effect_text(after)}'
    remaining = {}
    for key, change in delta.items():
        name = ATTRIBUTE_LABELS.get(key)
        pattern = ('攻击(?:力)?(?!速度)' if name == '攻击' else
                   '防御(?:力)?' if name == '防御' else re.escape(name or ''))
        # Only an explicit, adjacent signed annotation establishes that the
        # description already carries this attribute's potential increment.
        annotations = re.finditer(pattern + r'([^，。；\n（）()]*?)[（(][+-]\d+(?:\.\d+)?%?[）)]', description)
        if name and any(not any(other in match.group(1) for other in ATTRIBUTE_LABELS.values()) for match in annotations):
            continue
        # Internal implementation values need no extra warning when the game
        # supplies a complete annotated description. Known gameplay attributes
        # still require their own adjacent annotation above.
        if annotated_description and not name:
            continue
        remaining[key] = change
    return present('potential_delta', remaining) if remaining else ''


def present(key: str, value: Any) -> str:
    if key == 'profession':
        return PROFESSIONS.get(value, _known_text(value, '职业未确认'))
    if key == 'sub_profession_name':
        return _player_name(value, '分支未确认')
    if key == 'sub_profession':
        return '分支未确认'
    if key == 'rarity' and isinstance(value, str) and value.startswith('TIER_'):
        return value[5:] + '星'
    if key == 'phase' and (isinstance(value, int) or str(value).startswith('PHASE_')):
        return '精英' + str(value).removeprefix('PHASE_')
    if key in {'unlock','unlock_condition'} and isinstance(value, dict):
        conditions = [present(k, value[k]) + ('级' if k == 'level' else '')
                      for k in ('phase', 'level', 'potential') if value.get(k) is not None]
        if any(k not in {'phase', 'level', 'potential'} and v is not None for k, v in value.items()):
            conditions.append('其他解锁条件未确认')
        return '、'.join(conditions) or '无额外条件'
    if key == 'room':
        return ROOMS.get(value, _known_text(value, '设施未确认'))
    if key == 'sp_type':
        return SP_TYPES.get(value, _known_text(value, '技力回复方式未确认'))
    if key == 'trigger':
        return TRIGGERS.get(value, _known_text(value, '触发方式未确认'))
    if key == 'duration_type':
        return {'NONE':'常规持续','AMMO':'弹药制',0:'常规持续',1:'弹药制'}.get(value, _known_text(value, '持续方式未确认'))
    if key in {'description', 'trait'}:
        return _effect_text(value)
    if key in {'key', 'label'}:
        return ATTRIBUTE_LABELS.get(value, _known_text(value, '属性效果未确认'))
    if key == 'potential_delta' and isinstance(value,dict):
        names={**ATTRIBUTE_LABELS, 'damage_resistance_normal':'普通目标伤害减免',
               'damage_resistance_seamonster':'海怪伤害减免'}
        rows=[]
        unknown = False
        for parameter,change in value.items():
            if parameter in names and isinstance(change,dict) and any(k in change for k in ('before','after','delta')):
                rows.append(f'{names[parameter]}相关潜能效果有变化，幅度未确认')
            else:
                unknown = True
        if unknown:
            rows.append('部分潜能效果未确认')
        return '\n'.join(rows) if rows else '无额外潜能增量'
    if key == 'kind':
        return {'added':'新增','modified':'修改','removed':'移除','form_added':'新增形态'}.get(value, plain(value))
    return plain(value)


def _rows(data: dict[str, Any], skip: set[str] | None = None) -> list[tuple[str, str]]:
    return [(label(k), present(k,v)) for k,v in data.items() if k in LABELS and k not in RAW_KEYS | (skip or set())
            and (v is not None or k in {'description','trait'})]


def _complete_rows(data: dict[str, Any], required: tuple[str, ...], skip=None) -> list[tuple[str, str]]:
    rows = []
    for key in required:
        if key not in RAW_KEYS:
            source_key = 'sub_profession_name' if key == 'sub_profession' and data.get('sub_profession_name') else key
            rows.append((label(key), present(source_key, data.get(source_key))))
    return rows + _rows(data, set(required) | {'sub_profession_name'} | (skip or set()))


def _missing(profile, name: str, keys: tuple[str, ...]) -> str:
    issues = '\n'.join(str(x) for x in profile.diagnostics).lower()
    return f'{name}资料不完整' if _draft(profile) or any(k.lower() in issues for k in keys) else f'无{name}'


def _player_name(value: Any, fallback: str) -> str:
    text = plain(value).strip() if value is not None else ''
    return text or fallback


def _number(value: Any, *, signed: bool = False, unit: str = '') -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return plain(value)
    number = format(value, '+.12g' if signed and value else '.12g')
    return number + unit


def _unique_text(values, fallback='未提供'):
    return '\n'.join(dict.fromkeys(str(value).strip() for value in values
                                    if value is not None and str(value).strip())) or fallback


def _compact_cells(values, labels):
    # Point at the first complete value, so references never form a chain.
    seen, result = {}, []
    for value, label_text in zip(values, labels):
        if value not in {'未提供', '—', ''} and not any(marker in value for marker in ('未解析', '未确认', '不完整')):
            if value in seen:
                result.append('同' + seen[value])
                continue
            seen[value] = label_text
        result.append(value)
    return result


def _module_states(phases):
    states = {'1级': [], '2级': [], '3级': []}
    for index, phase in enumerate(phases, 1):
        level = str(phase.get('level', '')).strip()
        title = level + '级' if level.isdigit() else f'未标明阶段{index}'
        states.setdefault(title, []).append(phase)
    return list(states.items())


def _effect_groups(states, field_name, module_unlock, token_names):
    groups = {}
    for state, phases in states:
        for phase in phases:
            for effect in phase.get(field_name, []):
                if not (effect.get('name') or effect.get('description') or effect.get('potential_delta') or
                        (field_name == 'talents' and effect.get('blackboard'))):
                    continue
                scope = {key: value for key, value in (effect.get('scope') or {}).items() if value}
                unlock = effect.get('unlock_condition') or {}
                identity = (effect.get('talent_index'), effect.get('name') or '',
                            json.dumps(scope, sort_keys=True, ensure_ascii=False),
                            json.dumps(unlock, sort_keys=True, ensure_ascii=False))
                title = ('天赋：' if field_name == 'talents' else '召唤物效果：') + _player_name(effect.get('name'), '未命名天赋' if field_name == 'talents' else '模组强化')
                qualifiers = [f'{key}：{value}' for key, value in _scope_rows(scope, token_names)]
                if unlock and unlock != module_unlock:
                    qualifiers.append('解锁：' + present('unlock_condition', unlock))
                if qualifiers:
                    title += '\n' + '；'.join(qualifiers)
                group = groups.setdefault(identity, {'title': title, 'states': {}, 'originals': []})
                group['states'].setdefault(state, []).append(effect)
                comparison = effect.get('comparison')
                if isinstance(comparison, dict) and comparison.get('original') is not None:
                    group['originals'].append(_effect_text(comparison['original']))
    return list(groups.values())


def _effect_value(effect):
    comparison = effect.get('comparison')
    value = comparison.get('current') if isinstance(comparison, dict) else effect.get('description')
    if value is not None and plain(value).strip():
        return _effect_text(value)
    return '效果未确认'


def _effect_matrix_rows(groups, states):
    effects, potentials = [], []
    labels = ['未装备', *[title for title, _ in states]]
    for group in groups:
        baseline = _unique_text(group['originals'])
        values, potential_values = [baseline], ['未提供']
        has_potential = False
        for state, phases in states:
            records = group['states'].get(state, [])
            # Domain stages describe that level's patch. A present level with
            # no patch for this known talent retains its original effect.
            values.append(_unique_text((_effect_value(item) for item in records)) if records
                          else baseline if phases else '未提供')
            deltas = [text for item in records if (text := _potential_text(item))]
            has_potential |= bool(deltas)
            potential_values.append(_unique_text(deltas))
        effects.append([group['title'], *_compact_cells(values, labels)])
        if has_potential:
            potentials.append([group['title'], *_compact_cells(potential_values, labels)])
    return effects, potentials


def _attribute_value(row, comparison=None):
    unit = row.get('unit', '')
    if comparison is None:
        value = row.get('value')
        return _number(value, signed=True, unit=unit) + '（加成）' if value is not None else '未提供'
    bonus = _number(row.get('bonus'), signed=True, unit=unit)
    reason = comparison.get('reason')
    if reason or comparison.get('panel_applies') is False:
        state = {'locked': '尚未解锁', 'conditional': '需满足限定条件'}.get(reason, '不计常驻面板')
        return f'{state}（{bonus}）'
    if row.get('after') is None:
        return f'未提供（加成 {bonus}）'
    return f'{_number(row["after"], unit=unit)}（{bonus}）'


def _module_blocks(module: dict[str, Any], prefix: str = '', *, owner_id: str = '', fallback_id: str = 'module') -> list[Block]:
    module = as_jsonable(module)
    name = _player_name(module.get('name'), '未命名模组')
    if name in {module.get('equip_id'), module.get('id')}:
        name = '未命名模组'
    char_name = _player_name(module.get('char_name'), '未标明干员')
    if char_name == module.get('char_id'):
        char_name = '未标明干员'
    title = f"{prefix}{char_name} · {_player_name(module.get('type_name'), '类型未提供')} · {name}"
    owner = _player_name(module.get('char_id') or owner_id, '未标明干员')
    key = _player_name(module.get('equip_id') or module.get('id'), fallback_id)
    entry = {'entry_id': f'module:{owner}:{key}', 'entry_title': title}
    metadata = module.get('metadata') or {}
    build = metadata.get('comparison_build')
    intro = []
    if isinstance(build, dict):
        intro.append(('培养', f'精英{plain(build.get("phase"))} · Lv.{plain(build.get("level"))} · 潜能{plain(build.get("potential"))} · 信赖{plain(build.get("trust"))}'))
    intro.append(('属性口径', '装备后值（该级模组总加成）；战斗效果与召唤物另列。'))
    module_unlock = metadata.get('unlock_condition') or {}
    if module_unlock:
        intro.append(('解锁', present('unlock_condition', module_unlock)))
    if metadata.get('special_equip'):
        intro.append(('限定条件', plain(metadata.get('special_equip_description')) if metadata.get('special_equip_description') else '限定模组，需满足适用条件'))
    phases = module.get('phases') or []
    token_ids = dict.fromkeys(token for phase in phases for token in (phase.get('token_attributes') or {}))
    for phase in phases:
        for effect in [*phase.get('talents', []), *phase.get('token_effects', [])]:
            token = (effect.get('scope') or {}).get('tokenKey')
            if token:
                token_ids.setdefault(token, None)
    token_names = {token: f'召唤物{index}' for index, token in enumerate(token_ids, 1)}
    blocks = [Block(title, intro, group='模组', kind='module-info', **entry)]
    if not phases:
        blocks[0].rows.append(('阶段', '模组效果未确认'))
        return blocks
    states = _module_states(phases)
    columns = ['项目', '未装备', *[label_text for label_text, _ in states]]

    def matrix(title_text, kind, cells, notes=None):
        if cells:
            blocks.append(Block(title_text, columns=list(columns), cells=cells, group='模组', kind=kind,
                                notes=notes or [], **entry))

    attributes = {}
    for state, members in states:
        for phase in members:
            comparison = phase.get('comparison')
            compared = isinstance(comparison, dict) and bool(comparison.get('attributes'))
            rows = comparison['attributes'] if compared else phase.get('attributes', [])
            for row in rows:
                key = row.get('key') or row.get('label') or '未标明属性'
                record = attributes.setdefault(key, {'label': _attribute_label(row), 'before': [], 'states': {}})
                if record['label'] == '属性效果未确认':
                    record['states'].setdefault(state, []).append('效果未确认')
                    continue
                if compared and row.get('before') is not None:
                    record['before'].append(_number(row['before'], unit=row.get('unit', '')))
                record['states'].setdefault(state, []).append(_attribute_value(row, comparison if compared else None))
    matrix('属性对照', 'module-attributes', [
        [row['label'], _unique_text(row['before']), *[_unique_text(row['states'].get(state, [])) for state, _ in states]]
        for row in attributes.values()])

    original_traits = []
    traits = []
    conditions, diagnostics = [], []
    for state, members in states:
        current, rules, issues = [], [], []
        for phase in members:
            comparison = phase.get('comparison')
            trait = comparison.get('trait') if isinstance(comparison, dict) else None
            if isinstance(trait, dict):
                if trait.get('original') is not None:
                    original_traits.append(_effect_text(trait['original']))
                current.append(_effect_text(trait.get('current')))
            elif 'trait' in phase:
                current.append(_effect_text(phase['trait']))
            rules.extend(f'{label_text}：{value}' for label_text, value in _scope_rows(phase.get('scope'), token_names))
            if isinstance(comparison, dict) and comparison.get('reason'):
                rules.append({'locked': '尚未解锁，装备后面板不计入',
                              'conditional': '限定模组，需满足限定条件；不计入常驻面板'}.get(comparison['reason'], '生效条件未确认'))
            if _unresolved(phase.get('diagnostics', [])):
                issues.append('部分效果未确认')
        traits.append(_unique_text(current))
        conditions.append(_unique_text(rules, '—') if members else '未提供')
        diagnostics.append(_unique_text(issues, '—') if members else '未提供')
    effects = []
    baseline_trait = _unique_text(original_traits)
    if baseline_trait != '未提供' or any(value != '未提供' for value in traits):
        effects.append(['特性', *_compact_cells([baseline_trait, *traits], columns[1:])])
    talent_rows, potential_rows = _effect_matrix_rows(_effect_groups(states, 'talents', module_unlock, token_names), states)
    effects.extend(talent_rows)
    matrix('特性与天赋', 'module-effects', effects, _terminology_rows(
        effect for phase in phases for effect in phase.get('talents', [])))
    matrix('潜能增量', 'module-potential', potential_rows)

    summons, token_potentials = _effect_matrix_rows(_effect_groups(states, 'token_effects', module_unlock, token_names), states)
    token_attributes = {}
    for state, members in states:
        for phase in members:
            for token, board in (phase.get('token_attributes') or {}).items():
                pairs = board.items() if isinstance(board, dict) else ((item.get('key'), item.get('value')) for item in board if isinstance(item, dict)) if isinstance(board, list) else []
                for key, value in pairs:
                    label_text = token_names[token] + ' · ' + ATTRIBUTE_LABELS.get(key, '属性效果未确认')
                    text = _number(value, signed=True) + '（加成）' if key in ATTRIBUTE_LABELS else '效果未确认'
                    token_attributes.setdefault(label_text, {}).setdefault(state, []).append(text)
    summons.extend([label_text, '未提供', *[_unique_text(values.get(state, [])) for state, _ in states]]
                   for label_text, values in token_attributes.items())
    matrix('召唤物', 'module-summons', summons, _terminology_rows(
        effect for phase in phases for effect in phase.get('token_effects', [])))
    matrix('召唤物潜能增量', 'module-potential', token_potentials)
    extra = []
    if any(value not in {'—', '未提供'} for value in conditions):
        extra.append(['适用条件', '—', *_compact_cells(conditions, columns[2:])])
    if any(value not in {'—', '未提供'} for value in diagnostics):
        extra.append(['资料状态', '—', *_compact_cells(diagnostics, columns[2:])])
    matrix('生效条件', 'module-conditions', extra)
    return blocks

ATTRIBUTE_LABELS = {'atk':'攻击','def':'防御','max_hp':'生命上限','maxHp':'生命上限',
    'attack_speed':'攻击速度','magic_resistance':'法术抗性','respawn_time':'再部署时间','cost':'部署费用','block_cnt':'阻挡数',
    'attackSpeed':'攻击速度','magicResistance':'法术抗性','respawnTime':'再部署时间','blockCnt':'阻挡数',
    'baseAttackTime':'基础攻击间隔','base_attack_time':'基础攻击间隔'}


def _attribute_label(row):
    return _known_text(row.get('label'), ATTRIBUTE_LABELS.get(row.get('key'), '属性效果未确认'))


def _scope_rows(scope: Any, token_names=None) -> list[tuple[str,str]]:
    if not isinstance(scope,dict):
        return []
    rows = []
    if scope.get('tokenKey'):
        rows.append(('适用对象', (token_names or {}).get(scope['tokenKey'], '指定召唤物')))
    elif scope.get('isToken'):
        rows.append(('适用对象', '召唤物'))
    names = {'validInGameTag':'玩法条件','validInMapTag':'地图条件','validModeIndices':'模式条件',
             'game_tag_meta':'限定玩法'}
    unknown = False
    for key, name in names.items():
        condition = scope.get(key)
        if not condition:
            continue
        values = condition if isinstance(condition, (list, tuple)) else [condition]
        known = []
        for value in values:
            if isinstance(value, dict):
                value = value.get('name') or value.get('label')
            text = _known_text(value, '')
            if text:
                known.append(text)
            else:
                unknown = True
        if known:
            rows.append((name, '、'.join(dict.fromkeys(known))))
    if unknown or any(value for key, value in scope.items() if key not in {*names, 'isToken', 'tokenKey'}):
        rows.append(('限定条件', '限定地图/模式，具体范围未确认'))
    return rows


def _unresolved(diagnostics) -> bool:
    markers = ('missing','unparsed','unresolved','unsupported','不完整','未解析','缺失','损坏','未知占位','no usable','断裂')
    return any(any(marker in str(diagnostic).lower() for marker in markers) for diagnostic in diagnostics)


def _draft(profile) -> bool:
    return profile.metadata.get('complete') is False or _unresolved(profile.diagnostics)


def semantic_blocks(document: ReportDocument) -> list[Block]:
    blocks = []
    if document.metadata.get('complete') is False or any(_draft(profile) for profile in [*document.operators, *document.modules]):
        blocks.append(Block('资料不完整', [('提示', '部分效果未确认；缺项不表示无技能或无效果。')], group='草稿警告'))
    for profile in document.operators:
        name = _player_name(profile.name, '未命名干员') if profile.name != profile.char_id else '未命名干员'
        blocks.append(Block(name, _complete_rows(profile.summary,
            ('profession','sub_profession','rarity','phase','level','potential','trust','obtainable','appellation')), group='概览'))
        blocks.append(Block('特性', [('说明', _effect_text(profile.trait))], group='特性'))
        attrs = profile.attributes
        blocks.append(Block('属性与加成', columns=['项目', '最终值', '基础', '信赖', '潜能', '模组', '单位'], cells=[
            [_attribute_label(a)] + ([plain(a.get(k)) for k in ('value','base','trust','potential','module','unit')]
                                    if _attribute_label(a) != '属性效果未确认' else ['效果未确认', '', '', '', '', ''])
            for a in attrs] if attrs else [['属性数据未提供', '', '', '', '', '', '']], group='属性'))
        for i, skill in enumerate(profile.skills, 1):
            index = _player_name(skill.get('index'), str(i))
            name = _player_name(skill.get('name'), '未命名技能')
            if name == skill.get('id'):
                name = '未命名技能'
            key = _player_name(skill.get('id'), f'index-{index}')
            owner = _player_name(profile.char_id, '未标明干员')
            entry = {'entry_id': f'skill:{owner}:{key}', 'entry_title': name}
            blocks.append(Block(f'技能{index} · {name}', _complete_rows(skill,
                ('level','sp_type','trigger','init_sp','sp_cost','duration','duration_type','description'), {'index','name'}), group='技能', **entry))
        if not profile.skills:
            blocks.append(Block('技能', [('状态', _missing(profile, '技能', ('skill', '技能')))], group='技能'))
        for talent in profile.talents:
            rows = _complete_rows(talent, ('description','unlock_condition'), {'name','potential_delta'})
            if potential := _potential_text(talent):
                rows.append(('潜能增量', potential))
            blocks.append(Block('天赋 · ' + _player_name(talent.get('name'), '未命名天赋'), rows,
                                group='天赋', notes=_terminology_rows([talent])))
        if not profile.talents:
            blocks.append(Block('天赋', [('状态', _missing(profile, '天赋', ('talent','天赋')))], group='天赋'))
        for skill in profile.building_skills:
            blocks.append(Block('后勤 · ' + _player_name(skill.get('name'), '未命名后勤技能'), _complete_rows(skill, ('description','room','unlock'), {'name'}), group='后勤'))
        if not profile.building_skills:
            blocks.append(Block('后勤技能', [('状态', _missing(profile, '后勤技能', ('building','后勤','基建')))], group='后勤'))
        blocks.append(Block('潜能提升', [(f'潜能{i + 2}', plain(value)) for i, value in enumerate(profile.potentials)]
            or [('状态', _missing(profile, '潜能提升', ('potential','潜能')))], group='潜能'))
        for index, module in enumerate(profile.modules, 1):
            blocks.extend(_module_blocks(module, owner_id=profile.char_id, fallback_id=f'index-{index}'))
        if not profile.modules:
            blocks.append(Block('模组', [('状态', _missing(profile, '模组', ('module', 'equip', '模组')))], group='模组'))
    for index, module in enumerate(document.modules, 1):
        blocks.extend(_module_blocks(as_jsonable(module), fallback_id=f'index-{index}'))
    if not blocks:
        blocks.append(Block('未选择资料', [('提示', '选择干员或模组后生成资料。')]))
    return blocks


def _readable_tree(value: Any, prefix: str = '') -> str:
    if isinstance(value, dict):
        if ('key' in value or 'label' in value) and 'value' in value and _attribute_label(value) == '属性效果未确认':
            return prefix + '属性效果未确认'
        rows = []
        for key, item in value.items():
            if key == 'sub_profession' and value.get('sub_profession_name'):
                continue
            if key == 'scope':
                rows.extend(f'{prefix}{name}：{text}' for name, text in _scope_rows(item))
            elif key == 'token_attributes' and isinstance(item, dict):
                for index, attributes in enumerate(item.values(), 1):
                    pairs = attributes.items() if isinstance(attributes, dict) else ((a.get('key'), a.get('value')) for a in attributes if isinstance(a, dict)) if isinstance(attributes, list) else []
                    for attribute, amount in pairs:
                        rows.append(f'{prefix}召唤物{index} · {ATTRIBUTE_LABELS.get(attribute, "属性效果未确认")}：' +
                                    (plain(amount) if attribute in ATTRIBUTE_LABELS else '效果未确认'))
            elif key not in RAW_KEYS - {'token_effects'} and (key in LABELS or key in ATTRIBUTE_LABELS):
                if isinstance(item, (dict, list)) and key not in {'unlock','unlock_condition','potential_delta'}:
                    rows.append(_readable_tree(item, f'{prefix}{label(key)} / '))
                else:
                    rows.append(f'{prefix}{ATTRIBUTE_LABELS.get(key, label(key))}：{present(key,item)}')
        return '\n'.join(rows) or '暂无可确认的效果变化'
    if isinstance(value, list):
        return '\n'.join(_readable_tree(v, f'{prefix}{i+1}. ') for i,v in enumerate(value)) or '无条目'
    return prefix + plain(value)


def display_title(document: ReportDocument) -> str:
    title = document.title
    if not title or not title.strip():
        return '干员与模组资料'
    if any(title == profile.name == profile.char_id for profile in document.operators):
        return '未命名干员'
    if any(title == profile.name == profile.equip_id for profile in document.modules):
        return '未命名模组'
    return title


def text_report(document: ReportDocument) -> str:
    lines = [display_title(document)]
    for block in semantic_blocks(document):
        lines.extend(['', f'【{block.title}】'])
        lines.extend(f'{key}：{value}' for key, value in block.rows)
        if block.columns:
            lines.append(' | '.join(block.columns))
            lines.extend(' | '.join(row) for row in block.cells)
        lines.extend(f'{key}：{value}' for key, value in block.notes)
    return '\n'.join(lines) + '\n'
