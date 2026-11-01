"""New exports contain current profiles, independent of historical comparisons."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import ImageDraw

from arknights_unpacker.contracts import (EntityChangeSet, ExportFormat, ModuleProfile,
    OperatorProfile, ReportDocument, ReportOptions, ReportSelection, as_jsonable)
from arknights_unpacker.reports import compose_report, export_report


def selection():
    operator = OperatorProfile('char_current', '当前干员', trait='当前角色参数标记',
        attributes=[{'key': 'atk', 'label': '攻击', 'value': 1234}])
    module = ModuleProfile('equip_current', operator.char_id, operator.name, '当前模组',
        phases=[{'level': level, 'trait': f'当前模组等级{level}参数标记',
                 'attributes': [{'key': 'atk', 'label': '攻击', 'value': 10 * level}]}
                for level in (1, 2, 3)])
    changes = EntityChangeSet('old_snapshot', 'current_snapshot', operators=[
        {'id': operator.char_id, 'name': operator.name, 'kind': 'modified',
         'changes': [{'field': 'trait', 'before': '旧角色历史标记', 'after': operator.trait}]}], modules=[
        {'id': module.equip_id, 'name': module.name, 'kind': 'modified',
         'changes': [{'field': 'trait', 'before': '旧模组历史标记', 'after': '历史差分专用标记'}]}])
    return ReportSelection([operator], [module], changes)


def test_all_new_export_formats_keep_current_values_without_history(tmp_path, monkeypatch):
    chosen = selection()
    original = deepcopy(as_jsonable(chosen))
    document = compose_report(chosen, ReportOptions(width=640, font_size=18))
    assert not document.metadata.get('changes')
    painted = []
    draw_text = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        painted.append((str(text), xy[0]))
        return draw_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture)
    artifacts = export_report(document, tmp_path, set(ExportFormat))
    assert {artifact.format for artifact in artifacts} == {item.value for item in ExportFormat}
    json_path = next(Path(item.path) for item in artifacts if item.format == 'json')
    saved = json.loads(json_path.read_text('utf-8'))
    assert saved['operators'] == original['operators']
    assert saved['modules'] == original['modules']
    assert not saved['metadata'].get('changes')
    outputs = [''.join(text for text, _ in painted)]
    outputs.extend(Path(item.path).read_text('utf-8') for item in artifacts if item.format != 'png')
    for output in outputs:
        assert '旧角色历史标记' not in output
        assert '旧模组历史标记' not in output
        assert '历史差分专用标记' not in output
        assert '更新对照' not in output
    assert '当前角色参数标记' in outputs[0]
    columns = {}
    for text, x in painted:
        columns[x] = columns.get(x, '') + text
    assert all(any(f'当前模组等级{level}参数标记' in column for column in columns.values()) for level in (1, 2, 3))
    assert as_jsonable(chosen) == original


def test_exporting_legacy_document_omits_history_without_mutating_input(tmp_path):
    chosen = selection()
    document = ReportDocument('旧资料重导出', chosen.operators, chosen.modules,
        metadata={'changes': as_jsonable(chosen.changes), 'version': 'current'})
    original = deepcopy(as_jsonable(document))
    artifacts = export_report(document, tmp_path, {ExportFormat.JSON, ExportFormat.TXT, ExportFormat.HTML})
    for artifact in artifacts:
        output = Path(artifact.path).read_text('utf-8')
        assert '旧角色历史标记' not in output
        assert '旧模组历史标记' not in output
        assert '更新对照' not in output
    assert as_jsonable(document) == original
