"""Default export directory behavior, isolated from installed/user directories."""
import json
from pathlib import Path
import sys

import pytest

from arknights_unpacker.application import AppServices
from arknights_unpacker import paths

_RESOURCE_ROOT = paths.resource_root()


def source_program(monkeypatch, root):
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(paths, '__file__', str(root / 'src/arknights_unpacker/paths.py'))
    # Program location is the behavior under test; runtime schemas/rules still
    # come from the real read-only test checkout, as they do in a built bundle.
    monkeypatch.setattr(paths, 'resource_root', lambda: _RESOURCE_ROOT)


@pytest.mark.parametrize('frozen', [False, True])
def test_program_exports_ignores_cwd_meipass_and_custom_data_directory(tmp_path, monkeypatch, frozen):
    program = tmp_path / 'missing-parent' / 'portable-program'
    cwd = tmp_path / 'unrelated-working-directory'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    source_program(monkeypatch, program)
    if frozen:
        monkeypatch.setattr(sys, 'frozen', True)
        monkeypatch.setattr(sys, 'executable', str(program / 'ArknightsUnpacker.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'different-bundle-resources'), raising=False)
    expected = program / 'exports'
    assert paths.program_root() == program
    assert paths.default_output_root() == expected
    assert not expected.exists()
    custom_data = tmp_path / 'separate-state'
    service = AppServices(custom_data)
    try:
        assert service.data_root == custom_data
        assert service.config['output_root'] == str(expected)
        assert expected.is_dir()
        assert not (custom_data / 'exports').exists()
        assert not (cwd / 'exports').exists()
    finally:
        service.shutdown()


def test_startup_retains_files_already_in_program_exports(tmp_path, monkeypatch):
    program = tmp_path / 'program'
    source_program(monkeypatch, program)
    exports = program / 'exports'
    (exports / 'subfolder').mkdir(parents=True)
    retained = {exports / 'existing.png': b'original image bytes',
                exports / 'subfolder' / 'report.html': b'original report bytes'}
    for path, content in retained.items():
        path.write_bytes(content)
    service = AppServices(tmp_path / 'data')
    try:
        assert service.config['output_root'] == str(exports)
        assert {path: path.read_bytes() for path in retained} == retained
    finally:
        service.shutdown()


@pytest.mark.parametrize('saved_output', ['legacy_default', '', '   ', None])
def test_old_default_or_empty_setting_migrates_once_and_preserves_other_settings(tmp_path, monkeypatch, saved_output):
    program, home = tmp_path / 'program', tmp_path / 'isolated-home'
    source_program(monkeypatch, program)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    old_exports = home / 'Documents' / 'ArknightsExports'
    old_exports.mkdir(parents=True)
    retained = old_exports / 'old-export.png'
    retained.write_bytes(b'keep old exports at original location')
    value = str(old_exports) if saved_output == 'legacy_default' else saved_output
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    original = {'output_root': value, 'hours': 36.5, 'report_width': 1472,
                'formats': ['html'], 'data_locale': 'zh_CN',
                'user_setting': {'saved': [1, 2, 'unchanged']}}
    config_file = data_dir / 'settings.json'
    config_file.write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')
    expected = program / 'exports'
    service = AppServices(data_dir)
    try:
        assert service.config['output_root'] == str(expected)
        assert expected.is_dir()
        saved = json.loads(config_file.read_text(encoding='utf-8'))
        assert saved['output_root'] == str(expected)
        for key, content in original.items():
            if key != 'output_root':
                assert service.config[key] == content
                assert saved[key] == content
        assert retained.read_bytes() == b'keep old exports at original location'
        assert not list(expected.iterdir()), 'changing a default must not move old exported files'
    finally:
        service.shutdown()
    reopened = AppServices(data_dir)
    try:
        assert reopened.config['output_root'] == str(expected)
        assert reopened.config['user_setting'] == original['user_setting']
        assert retained.read_bytes() == b'keep old exports at original location'
    finally:
        reopened.shutdown()


def test_custom_output_is_preserved_and_remains_lazily_created(tmp_path, monkeypatch):
    source_program(monkeypatch, tmp_path / 'program')
    custom = tmp_path / 'my-custom-output'
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    config_file = data_dir / 'settings.json'
    config_file.write_text(json.dumps({'output_root': str(custom), 'hours': 15}), encoding='utf-8')
    service = AppServices(data_dir)
    try:
        assert service.config['output_root'] == str(custom)
        assert service.config['hours'] == 15
        assert json.loads(config_file.read_text(encoding='utf-8'))['output_root'] == str(custom)
        assert not custom.exists()
    finally:
        service.shutdown()


def test_default_exports_creation_failure_names_output_path(tmp_path, monkeypatch):
    program = tmp_path / 'program'
    source_program(monkeypatch, program)
    expected = program / 'exports'
    old_mkdir = Path.mkdir
    def denied(path, *args, **kwargs):
        if path == expected:
            raise PermissionError('test output directory is read-only')
        return old_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', denied)
    with pytest.raises(OSError) as captured:
        AppServices(tmp_path / 'data')
    assert str(expected) in str(captured.value)
    assert '输出' in str(captured.value)
    assert not expected.exists()


@pytest.mark.parametrize('game_evidence', ['directory_layout', 'saved_root'])
def test_external_data_directory_does_not_allow_automatic_exports_inside_game(tmp_path, monkeypatch, game_evidence):
    game = tmp_path / 'game'
    game.mkdir()
    if game_evidence == 'directory_layout':
        (game / 'Arknights_Data').mkdir()
    source_program(monkeypatch, game)
    data_dir = tmp_path / 'outside-game-data'
    if game_evidence == 'saved_root':
        data_dir.mkdir()
        (data_dir / 'settings.json').write_text(json.dumps({'game_root': str(game)}), encoding='utf-8')
    with pytest.raises((ValueError, OSError), match='游戏'):
        AppServices(data_dir)
    assert not (game / 'exports').exists()


def test_explicit_output_bypasses_unwritable_default_and_persists_on_restart(tmp_path, monkeypatch):
    program = tmp_path / 'program'
    source_program(monkeypatch, program)
    default = program / 'exports'
    custom = tmp_path / 'custom exports'
    data_dir = tmp_path / 'external-data'
    data_dir.mkdir()
    config_file = data_dir / 'settings.json'
    config_file.write_text(json.dumps({'output_root': str(default), 'hours': 19}), encoding='utf-8')
    old_mkdir = Path.mkdir
    default_calls = []
    def denied_default(path, *args, **kwargs):
        if path == default:
            default_calls.append(path)
            raise PermissionError('default exports is not writable')
        return old_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', denied_default)
    service = AppServices(data_dir, output_root=str(custom))
    try:
        assert service.config['output_root'] == str(custom)
        assert service.config['hours'] == 19
        assert json.loads(config_file.read_text(encoding='utf-8'))['output_root'] == str(custom)
        assert not default_calls
        assert not custom.exists()
        assert not default.exists()
    finally:
        service.shutdown()
    reopened = AppServices(data_dir)
    try:
        assert reopened.config['output_root'] == str(custom)
        assert reopened.config['hours'] == 19
        assert not default_calls
        assert not custom.exists()
    finally:
        reopened.shutdown()


def test_explicit_output_can_choose_legacy_documents_path_without_migration(tmp_path, monkeypatch):
    program, home = tmp_path / 'program', tmp_path / 'isolated-home'
    source_program(monkeypatch, program)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    explicit = home / 'Documents' / 'ArknightsExports'
    data_dir = tmp_path / 'external-data'
    service = AppServices(data_dir, output_root=str(explicit))
    try:
        assert service.config['output_root'] == str(explicit)
        assert json.loads((data_dir / 'settings.json').read_text(encoding='utf-8'))['output_root'] == str(explicit)
        assert not explicit.exists()
        assert not (program / 'exports').exists()
    finally:
        service.shutdown()
