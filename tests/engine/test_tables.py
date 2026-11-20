import hashlib,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from arknights_unpacker.extraction.tables import load_local_tables

def resource_folder(tmp_path):
    root=tmp_path/'resources';root.mkdir()
    bundle=root/'table.bin';bundle.write_bytes(b'UnityFS-fixture')
    idx=root/'fixture.idx';idx.write_bytes(b'idx-fixture')
    m={'versionId':'test-build','manifestVersion':'V-test','manifestName':'fixture.idx','abInfos':[{'name':'table.bin','md5':'abcd','hash':'abcd','abSize':bundle.stat().st_size}]}
    (root/'hot_update_list.json').write_text(json.dumps(m),encoding='utf-8')
    index={'assets':[{'assetName':'gamedata/excel/character_tableabcdef','bundle':'table.bin'}],'bundles':[]}
    return root,index

class TextObj:
    type=SimpleNamespace(name='TextAsset');path_id=7
    def read(self):return SimpleNamespace(m_Name='character_tableabcdef',m_Script='{"char_test":{"name":"测试"}}')

def test_standalone_resource_root_and_short_token(tmp_path):
    root,index=resource_folder(tmp_path)
    with patch('arknights_unpacker.extraction.tables.read_resource_manifest',return_value=index),patch('arknights_unpacker.extraction.tables.load_bundle',return_value=SimpleNamespace(objects=[TextObj()])):
        result=load_local_tables(root,tmp_path/'cache',names={'character_table'})
    assert result.complete and result.version=='V-test'
    assert result.tables['character_table'].data['char_test']['name']=='测试'
    proof=result.tables['character_table'].field_evidence['resourceVerification']
    assert proof['hashKind']=='short_token' and not proof['cryptographicDigestVerified']

def test_changed_manifest_invalidates_entire_table_set(tmp_path):
    root,index=resource_folder(tmp_path)
    def changed(path,**kwargs):
        (root/'hot_update_list.json').write_text('{}',encoding='utf-8')
        return SimpleNamespace(objects=[TextObj()])
    with patch('arknights_unpacker.extraction.tables.read_resource_manifest',return_value=index),patch('arknights_unpacker.extraction.tables.load_bundle',side_effect=changed):
        with pytest.raises(OSError,match='变化'):load_local_tables(root,tmp_path/'cache',names={'character_table'})
    assert not (tmp_path/'cache'/'sources.json').exists()

def test_manifest_index_path_traversal_rejected(tmp_path):
    root,index=resource_folder(tmp_path)
    path=root/'hot_update_list.json';m=json.loads(path.read_text());m['manifestName']='../outside.idx';path.write_text(json.dumps(m))
    with pytest.raises(ValueError,match='不安全'):load_local_tables(root,tmp_path/'cache')

def test_bundle_path_traversal_rejected(tmp_path):
    root,index=resource_folder(tmp_path)
    path=root/'hot_update_list.json';m=json.loads(path.read_text());m['abInfos'][0]['name']='../table.bin';path.write_text(json.dumps(m))
    index['assets'][0]['bundle']='../table.bin'
    with patch('arknights_unpacker.extraction.tables.read_resource_manifest',return_value=index):
        with pytest.raises(ValueError,match='不安全'):load_local_tables(root,tmp_path/'cache')

def test_resource_mutation_during_decode_is_not_accepted(tmp_path):
    root,index=resource_folder(tmp_path)
    class ChangedText(TextObj):
        def read(self):
            with (root/'table.bin').open('ab') as f:f.write(b'changed')
            return super().read()
    with patch('arknights_unpacker.extraction.tables.read_resource_manifest',return_value=index),patch('arknights_unpacker.extraction.tables.load_bundle',return_value=SimpleNamespace(objects=[ChangedText()])):
        with pytest.raises(OSError,match='变化'):
            load_local_tables(root,tmp_path/'cache',names={'character_table'})
    assert not (tmp_path/'cache'/'sources.json').exists()


def test_explicit_level_uses_indexed_unity_container_instead_of_object_name(tmp_path, monkeypatch):
    root, index = resource_folder(tmp_path)
    name = 'level_example_s'
    logical = f'gamedata/levels/activities/example/{name}'
    container_path = f'dyn/{logical}.bytes'
    index['assets'] = [{'assetName': logical, 'path': container_path, 'bundle': 'table.bin'}]

    class LevelObj(TextObj):
        def __init__(self, object_name, path_id):
            self.object_name = object_name
            self.path_id = path_id

        def read(self):
            return SimpleNamespace(m_Name=self.object_name, m_Script='{}')

    expected = LevelObj('level_example_S', 12)
    other = LevelObj(name, 34)
    env = SimpleNamespace(objects=[expected, other], container={container_path: expected})
    monkeypatch.setattr('arknights_unpacker.extraction.tables.read_resource_manifest', lambda _: index)
    monkeypatch.setattr('arknights_unpacker.extraction.tables.load_bundle', lambda *_, **__: env)
    result = load_local_tables(root, None, names={name}, logical_names={name: logical},
                               decoders={name: lambda raw, _: (json.loads(raw), {})})

    assert result.tables[name].source.path_id == '12'
    assert result.tables[name].source.object_name == 'level_example_S'
