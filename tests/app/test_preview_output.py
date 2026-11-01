"""Temporary exports must not replace the saved destination for real exports."""
import json
from pathlib import Path

import pytest

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import ExportFormat, GameDataSnapshot, OperatorProfile


@pytest.mark.parametrize('remember', [False, True])
@pytest.mark.parametrize('operation', ['extract', 'report'])
def test_preview_output_is_not_saved_but_formal_output_is(tmp_path, monkeypatch, remember, operation):
    official = tmp_path / 'saved-output'
    service = AppServices(tmp_path / 'data', output_root=official)
    service.save_config()
    before = service.config_file.read_bytes()
    target = tmp_path / 'p'
    source = tmp_path / 'source.ab'
    source.write_bytes(b'read-only fixture')
    calls = []
    def run(*args, **kwargs):
        calls.append(kwargs)
        return {'status': 'succeeded', 'outputs': []}
    monkeypatch.setattr(service.runner, 'run', run)
    service.gamedata = GameDataSnapshot('fixture', '1', '1', {})
    monkeypatch.setattr(service, 'operator_profile', lambda *args: OperatorProfile('char_fixture', '预览测试'))
    try:
        if operation == 'extract':
            service.extract([str(source)], target, remember_output=remember)
            assert calls == ([{}] if remember else [{'reusable': True}])
        else:
            service.export(['char_fixture'], [], target, {ExportFormat.JSON}, remember_output=remember)
        expected = target if remember else official
        assert service.config['output_root'] == str(expected)
        assert json.loads(service.config_file.read_text('utf-8'))['output_root'] == str(expected)
        if not remember:
            assert service.config_file.read_bytes() == before
        assert source.read_bytes() == b'read-only fixture'
        assert target.is_dir()
    finally:
        service.shutdown()


@pytest.mark.parametrize('name', ['preview', 'previews'])
def test_snapshot_save_rejects_temporary_preview_roots(tmp_path, name):
    service = AppServices(tmp_path / 'data', output_root=tmp_path / 'exports')
    service.gamedata = GameDataSnapshot('fixture', '1', '1', {})
    temporary = service.data_root / name / ('a' * 32)
    temporary.mkdir(parents=True)
    sentinel = temporary / 'preview.txt'
    sentinel.write_bytes(b'current preview')
    target = temporary / 'saved.json'
    try:
        with pytest.raises(ValueError, match='临时预览目录'):
            service.export_snapshot(target)
        assert not target.exists() and sentinel.read_bytes() == b'current preview'
        official = tmp_path / 'exports' / 'saved.json'
        service.export_snapshot(official)
        assert official.is_file()
    finally:
        service.shutdown()
