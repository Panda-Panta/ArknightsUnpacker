"""Inventory sizes come from metadata, without loading serialized payloads."""
from types import SimpleNamespace

import pytest

from arknights_unpacker.extraction import engine


@pytest.mark.parametrize('size', [0, 90, 1024, 2**32 - 1, None])
@pytest.mark.parametrize('kind', ['Texture2D', 'AudioClip', 'Mesh', 'VideoClip'])
def test_object_size_is_serialized_byte_size_without_payload_reads(tmp_path, monkeypatch, size, kind):
    source = tmp_path / 'sample.ab'
    source.write_bytes(b'UnityFS-fixture')

    def forbidden(*args, **kwargs):
        pytest.fail('Collecting object size read a serialized or streaming payload')

    obj = SimpleNamespace(path_id=12, type=SimpleNamespace(name=kind), byte_size=size,
                          peek_name=lambda: 'resource', read=forbidden, get_raw_data=forbidden)
    monkeypatch.setattr(engine, 'load_bundle', lambda path: SimpleNamespace(objects=[obj], container={}))
    result = engine.list_bundle_objects(source)[0]
    assert result['size'] == size
    assert result['id'] == '12'
    if kind == 'VideoClip':
        assert result['previewable'] is False
    else:
        assert 'previewable' not in result


def test_object_with_missing_byte_size_is_unknown_not_zero(tmp_path, monkeypatch):
    source = tmp_path / 'sample.ab'
    source.write_bytes(b'UnityFS-fixture')
    obj = SimpleNamespace(path_id=24, type=SimpleNamespace(name='Mesh'))
    monkeypatch.setattr(engine, 'load_bundle', lambda path: SimpleNamespace(objects=[obj], container={}))
    assert engine.list_bundle_objects(source)[0]['size'] is None


@pytest.mark.parametrize('suffix', ['.png', '.wav', '.txt', '.usm', '.idx'])
def test_standalone_source_size_is_file_bytes_without_decoding(tmp_path, monkeypatch, suffix):
    source = tmp_path / ('source' + suffix)
    source.write_bytes(b'not-a-Unity-bundle' * 100)

    def forbidden(*args, **kwargs):
        pytest.fail('Standalone inventory attempted to decode the source')

    monkeypatch.setattr(engine, 'load_bundle', forbidden)
    result = engine.list_bundle_objects(source)[0]
    assert result['id'] == 'source'
    assert result['size'] == source.stat().st_size
    assert result['previewable'] is True
