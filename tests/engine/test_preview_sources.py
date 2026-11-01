"""Standalone preview inputs use the same guarded extraction/output contract."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from arknights_unpacker.contracts import CancelToken, ExtractionRequest
from arknights_unpacker.extraction import engine


@pytest.mark.parametrize('suffix,expected_type', [
    ('.PNG', 'Image'), ('.wav', 'AudioClip'), ('.webm', 'VideoClip'),
    ('.json', 'TextAsset'), ('.bytes', 'TextAsset'), ('.skel', 'TextAsset'),
    ('.USM', 'VideoClip'), ('.idx', 'TextAsset'),
])
def test_standalone_object_inventory_does_not_try_to_load_a_unity_bundle(tmp_path, monkeypatch, suffix, expected_type):
    source = tmp_path / ('resource' + suffix)
    source.write_bytes(b'original media or text bytes')
    monkeypatch.setattr(engine, 'load_bundle', lambda _: pytest.fail('Standalone input reached the Unity loader'))
    objects = engine.list_bundle_objects(source)
    assert len(objects) == 1
    assert objects[0]['id'] == 'source' and objects[0]['type'] == expected_type
    assert objects[0]['name'] == source.name
    assert objects[0]['previewable'] is True


@pytest.mark.parametrize('suffix,kind', [('.png', 'image'), ('.wav', 'audio'),
    ('.webm', 'video'), ('.json', 'text'), ('.skel', 'spine')])
@pytest.mark.parametrize('mode', ['auto', 'raw'])
def test_selected_standalone_resource_keeps_original_bytes_and_never_overwrites(tmp_path, suffix, kind, mode):
    game = tmp_path / 'game'
    game.mkdir()
    source = game / ('resource' + suffix)
    payload = b'original bytes\0\xff\n'
    source.write_bytes(payload)
    req = ExtractionRequest([str(source)], str(tmp_path / 'out'), mode=mode,
        kinds=[kind], source_root=str(game), object_ids={str(source): ['source']})
    events = []
    first = engine.run_extraction(req, events.append)
    second = engine.run_extraction(req)
    assert first.status == second.status == 'succeeded'
    first_path, second_path = (Path(result.outputs[0]['path']) for result in (first, second))
    assert first_path != second_path
    assert first_path.read_bytes() == second_path.read_bytes() == source.read_bytes() == payload
    assert first_path.suffix == suffix
    assert first.outputs[0]['object_id'] == 'source'
    assert [event['kind'] for event in events] == ['progress', 'output', 'object_complete', 'source_complete']
    assert not list((tmp_path / 'out').rglob('*.partial'))


@pytest.mark.parametrize('suffix', ['.png', '.usm', '.idx'])
@pytest.mark.parametrize('restriction', ['type', 'object'])
def test_source_selection_and_kind_filters_prevent_unrequested_work(tmp_path, monkeypatch, suffix, restriction):
    source = tmp_path / ('resource' + suffix)
    source.write_bytes(b'input remains untouched')
    monkeypatch.setattr(engine, 'load_bundle', lambda _: pytest.fail('Unrequested source loaded'))
    monkeypatch.setattr('arknights_unpacker.extraction.usm.extract_usm', lambda *args: pytest.fail('Unrequested video demuxed'))
    monkeypatch.setattr('arknights_unpacker.extraction.manifest.read_resource_manifest', lambda *args: pytest.fail('Unrequested index decoded'))
    req = ExtractionRequest([str(source)], str(tmp_path / 'out'),
        kinds=['audio'] if restriction == 'type' else ['image', 'video', 'text'],
        object_ids={str(source): ['unrelated'] if restriction == 'object' else ['source']})
    events = []
    result = engine.run_extraction(req, events.append)
    assert not result.outputs and not result.errors and result.skipped
    assert not any(event['kind'] in {'source_complete', 'object_complete'} for event in events)
    assert source.read_bytes() == b'input remains untouched'


def test_usm_preview_source_reuses_existing_demux_and_returns_all_playable_outputs(tmp_path, monkeypatch):
    source = tmp_path / 'intro.usm'
    source.write_bytes(b'CRID-original')
    calls = []

    def demux(path, save, check, emit):
        calls.append(path)
        save(path, 'video_stream_0', 'intro', '.ivf', b'ivf-stream', 'video_stream')
        save(path, 'playable_0', 'intro', '.mkv', b'playable-container', 'video_playable')

    monkeypatch.setattr('arknights_unpacker.extraction.usm.extract_usm', demux)
    events = []
    result = engine.run_extraction(ExtractionRequest([str(source)], str(tmp_path / 'out'),
        kinds=['video'], object_ids={str(source): ['source']}), events.append)
    assert calls == [source.resolve()]
    assert [output['kind'] for output in result.outputs] == ['video_stream', 'video_playable']
    assert events[-2]['kind'] == 'object_complete' and events[-2]['object_id'] == 'source'
    assert events[-1]['kind'] == 'source_complete'
    assert source.read_bytes() == b'CRID-original'


def test_idx_preview_returns_decoded_manifest_instead_of_raw_binary(tmp_path, monkeypatch):
    source = tmp_path / 'resources.idx'
    source.write_bytes(b'original-index')
    monkeypatch.setattr('arknights_unpacker.extraction.manifest.read_resource_manifest', lambda path: {'files': ['demo.ab']})
    result = engine.run_extraction(ExtractionRequest([str(source)], str(tmp_path / 'out'),
        kinds=['text'], object_ids={str(source): ['source']}))
    assert len(result.outputs) == 1
    assert result.outputs[0]['kind'] == 'manifest'
    assert 'demo.ab' in Path(result.outputs[0]['path']).read_text('utf-8')


def test_unity_signature_takes_precedence_over_a_loose_file_extension(tmp_path, monkeypatch):
    source = tmp_path / 'bundle.json'
    source.write_bytes(b'UnityFS-fixture')
    unity_object = SimpleNamespace(path_id=12, type=SimpleNamespace(name='AssetBundle'))
    monkeypatch.setattr(engine, 'load_bundle', lambda path: SimpleNamespace(container={}, objects=[unity_object]))
    assert engine.list_bundle_objects(source)[0]['id'] == '12'
    result = engine.run_extraction(ExtractionRequest([str(source)], str(tmp_path / 'out'), kinds=['text']))
    assert not result.outputs


def test_unverified_unity_video_clip_is_not_an_automatic_preview_candidate(tmp_path, monkeypatch):
    source = tmp_path / 'videos.ab'
    source.write_bytes(b'UnityFS-fixture')
    obj = SimpleNamespace(path_id=7, type=SimpleNamespace(name='VideoClip'),
        read=lambda: SimpleNamespace(m_Name='Embedded movie'))
    monkeypatch.setattr(engine, 'load_bundle', lambda path: SimpleNamespace(container={}, objects=[obj]))
    row = engine.list_bundle_objects(source)[0]
    assert row['name'] == 'Embedded movie'
    assert row['previewable'] is False


def test_cancellation_after_a_direct_output_prevents_completion_events(tmp_path):
    source = tmp_path / 'recording.wav'
    source.write_bytes(b'preserved recording bytes')
    token, events = CancelToken(), []

    def emit(event):
        events.append(event)
        if event['kind'] == 'output':
            token.cancel()

    result = engine.run_extraction(ExtractionRequest([str(source)], str(tmp_path / 'out'),
        kinds=['audio']), emit, token)
    assert result.status == 'cancelled' and len(result.outputs) == 1
    assert not any(event['kind'] in {'object_complete', 'source_complete'} for event in events)


def test_standalone_output_inside_game_is_rejected_before_creating_files(tmp_path):
    source = tmp_path / 'image.png'
    source.write_bytes(b'original')
    output = tmp_path / 'do-not-create'
    with pytest.raises(ValueError, match='输出目录'):
        engine.run_extraction(ExtractionRequest([str(source)], str(output), kinds=['image'], source_root=str(tmp_path)))
    assert not output.exists() and source.read_bytes() == b'original'


def test_cancelling_a_large_source_copy_leaves_no_output_or_partial_file(tmp_path, monkeypatch):
    source = tmp_path / 'long-recording.wav'
    source.write_bytes(b'original-chunk' * 180000)
    expected_size = source.stat().st_size
    token = CancelToken()
    original_open = Path.open

    class CancellingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            block = self.stream.read(size)
            if size > 16 and block:
                token.cancel()
            return block

    def opened(path, mode='r', *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return CancellingReader(stream) if path == source and mode == 'rb' else stream

    monkeypatch.setattr(Path, 'open', opened)
    result = engine.run_extraction(ExtractionRequest([str(source)], str(tmp_path / 'out'),
        kinds=['audio']), cancel=token)
    assert result.status == 'cancelled' and not result.outputs
    assert not list((tmp_path / 'out').rglob('*.partial'))
    assert not list((tmp_path / 'out').rglob('*.wav'))
    assert source.stat().st_size == expected_size
