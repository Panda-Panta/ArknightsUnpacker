from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import CancelToken, ExtractionRequest
from arknights_unpacker.extraction import engine
from arknights_unpacker.jobs import worker_entry
from arknights_unpacker.ui.job_history import remaining_extraction


def test_expression_kind_writes_compositions_and_preserves_partial_diagnostics(tmp_path, monkeypatch):
    source = tmp_path / 'character.ab'
    source.write_bytes(b'UnityFS-character-fixture')
    env = SimpleNamespace(objects=[], container={})
    monkeypatch.setattr(engine, 'load_bundle', lambda _: env)
    picture = Image.new('RGBA', (3, 4), (1, 2, 3, 100))

    def images(actual, options=None, check=lambda: None):
        assert actual is env and options is None
        yield {'name': 'group1_face1', 'image': picture, 'metadata': {'entry_id': '0:0:1'}, 'object_ids': ['7']}
        yield {'name': 'bad_group', 'error': '角色配置引用缺失', 'metadata': {}, 'object_ids': []}

    monkeypatch.setitem(sys.modules, 'arknights_unpacker.extraction.characters',
                        SimpleNamespace(iter_character_images=images))
    result = engine.run_extraction(ExtractionRequest([str(source)], str(tmp_path / 'out'), kinds=['expression']))
    assert result.status == 'partial' and len(result.outputs) == 1
    assert result.outputs[0]['kind'] == 'character_expression'
    assert result.outputs[0]['character']['entry_id'] == '0:0:1'
    with Image.open(result.outputs[0]['path']) as actual:
        assert actual.tobytes() == picture.tobytes()
    assert '引用缺失' in result.errors[0]['error']


def test_expression_preview_options_cross_service_worker_boundary_without_saving_output(tmp_path):
    services = AppServices(tmp_path / 'data', output_root=tmp_path / 'formal')
    calls = []

    def run(operation, args, emit=None, cancel=None, **kwargs):
        calls.append((operation, args, kwargs))
        return {'status': 'succeeded', 'outputs': [], 'errors': [], 'skipped': []}

    services.runner.run = run
    options = {'group_id': '0:0', 'base_id': '0:0:2', 'face_id': '0:0:1', 'x': -3, 'y': 8, 'width': 30, 'height': 20}
    output = str(tmp_path / 'preview')
    try:
        services.extract([str(tmp_path / 'character.ab')], output, kinds=['expression'],
                         character_options=options, remember_output=False)
        assert calls[0][0] == 'extract'
        assert calls[0][1]['character_options'] == options
        assert calls[0][2]['reusable'] is True
        assert services.config['output_root'] == str((tmp_path / 'formal').resolve())
    finally:
        services.shutdown()


def test_worker_character_catalog_is_json_and_metadata_only(tmp_path, monkeypatch):
    env = SimpleNamespace(objects=[])
    monkeypatch.setattr('arknights_unpacker.extraction.unity.load_bundle', lambda _: env)
    monkeypatch.setitem(sys.modules, 'arknights_unpacker.extraction.characters',
                        SimpleNamespace(character_catalog=lambda actual, check=lambda: None: {'groups': [], 'diagnostics': ['unsupported']}))
    request = tmp_path / 'request.json'
    result = tmp_path / 'result.json'
    request.write_text(json.dumps({'operation': 'character_catalog', 'args': {'path': 'fixture.ab'},
                                  'result_file': str(result)}), 'utf-8')
    assert worker_entry(str(request)) == 0
    assert json.loads(result.read_text('utf-8'))['value']['diagnostics'] == ['unsupported']


def test_partial_character_retry_keeps_options_and_retries_whole_unfinished_group(tmp_path):
    source = str(tmp_path / 'character.ab')
    output = tmp_path / 'retained.png'
    output.write_bytes(b'retained')
    record = {'result': {'status': 'partial',
                        'outputs': [{'source': source, 'object_id': 'character:0:0:1', 'path': str(output),
                                     'size': 8, 'kind': 'character_expression'}],
                        'errors': [{'source': source, 'object_id': 'character:bad', 'error': 'unfinished group'}]}}

    def unavailable(*args, **kwargs):
        raise AssertionError('Character completion is separate from raw Unity object enumeration')

    request = {'paths': [source], 'kinds': ['expression'], 'character_options': {'group_id': '0:0'}}
    paths, ids = remaining_extraction(request, [record], unavailable, lambda _: None, CancelToken())
    assert paths == [source] and ids == {}
