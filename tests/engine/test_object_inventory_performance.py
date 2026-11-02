"""Browsing names must not deserialize image/audio payloads unnecessarily."""
from types import SimpleNamespace

import pytest

from arknights_unpacker.extraction import engine


def test_object_inventory_uses_name_only_reader_and_preserves_logical_paths(tmp_path, monkeypatch):
    source = tmp_path / 'sample.ab'
    source.write_bytes(b'UnityFS-fixture')

    def full_read():
        pytest.fail('Listing names deserialized a texture payload')

    obj = SimpleNamespace(path_id=12, type=SimpleNamespace(name='Texture2D'), byte_size=2048,
                          peek_name=lambda: 'native picture', read=full_read, get_raw_data=full_read)
    env = SimpleNamespace(objects=[obj], container={'images/picture.png': SimpleNamespace(path_id=12)})
    monkeypatch.setattr(engine, 'load_bundle', lambda path: env)
    assert engine.list_bundle_objects(source) == [
        {'id': '12', 'type': 'Texture2D', 'name': 'native picture', 'logical_path': 'images/picture.png', 'size': 2048}]


@pytest.mark.parametrize('peek_result', [None, RuntimeError('unsupported type tree')])
def test_name_only_read_falls_back_when_format_has_no_supported_peek_node(tmp_path, monkeypatch, peek_result):
    source = tmp_path / 'sample.ab'
    source.write_bytes(b'UnityFS-fixture')

    def peek():
        if isinstance(peek_result, Exception):
            raise peek_result
        return peek_result

    obj = SimpleNamespace(path_id=24, type=SimpleNamespace(name='MonoBehaviour'),
                          peek_name=peek, read=lambda: SimpleNamespace(m_Name='fallback name'))
    monkeypatch.setattr(engine, 'load_bundle', lambda path: SimpleNamespace(objects=[obj], container={}))
    assert engine.list_bundle_objects(source)[0]['name'] == 'fallback name'
