from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import pytest
from arknights_unpacker.contracts import ExtractionRequest,CancelToken
from arknights_unpacker.extraction.engine import run_extraction
from arknights_unpacker.extraction.decoder import normalize_flatbuffer,decode_table_bytes,schema

class BlackboardSample:
    def Key(self): return b'tag'
    def Value(self): return 0.0
    def ValueStr(self): return b'seamonster'

def test_blackboard_is_not_dictionary_wrapper():
    value,evidence=normalize_flatbuffer(BlackboardSample())
    assert value=={'key':'tag','value':0.0,'valueStr':'seamonster'}

def test_json_signed_header_false_positive():
    import flatbuffers
    m=schema('character_table');b=flatbuffers.Builder(128)
    m.clz_Torappu_SimpleKVTable_clz_Torappu_CharacterDataStartCharactersVector(b,0)
    v=b.EndVector();m.clz_Torappu_SimpleKVTable_clz_Torappu_CharacterDataStart(b)
    m.clz_Torappu_SimpleKVTable_clz_Torappu_CharacterDataAddCharacters(b,v)
    root=m.clz_Torappu_SimpleKVTable_clz_Torappu_CharacterDataEnd(b);b.Finish(root)
    raw=b'{\xff'+b'0'*126+bytes(b.Output())
    value,evidence=decode_table_bytes(raw,'character_table')
    assert value=={}
    assert evidence['fields']['/characters']['state']=='empty_vector'

def env_with_text(names):
    class Obj:
        type=SimpleNamespace(name='TextAsset')
        def __init__(self,idx,name):self.path_id=idx;self.name=name
        def read(self):return SimpleNamespace(m_Name=self.name,m_Script='hello中文')
    return SimpleNamespace(objects=[Obj(i,n) for i,n in enumerate(names)],container={})

def request(tmp_path,names=('input.bin',)):
    game=tmp_path/'game';game.mkdir()
    paths=[]
    for n in names:
        p=game/n;p.write_bytes(b'UnityFS\0data');paths.append(str(p))
    return ExtractionRequest(paths,str(tmp_path/'output'),kinds=['text'],source_root=str(game))

def test_same_names_and_traversal_export_do_not_overwrite(tmp_path):
    req=request(tmp_path)
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env_with_text(['../../evil','../../evil'])):
        result=run_extraction(req)
    assert result.status=='succeeded'
    paths=[Path(o['path']) for o in result.outputs]
    assert len(paths)==2 and len(set(paths))==2
    assert all(Path(req.output_root).resolve() in p.parents for p in paths)
    assert all(p.read_bytes()=='hello中文'.encode() for p in paths)

def test_corrupt_bundle_does_not_hide_other_success(tmp_path):
    req=request(tmp_path,('good.bin','bad.bin'))
    def load(p):
        if p.name=='bad.bin':raise ValueError('corrupt-bundle')
        return env_with_text(['good'])
    with patch('arknights_unpacker.extraction.engine.load_bundle',side_effect=load):
        result=run_extraction(req)
    assert result.status=='partial' and len(result.outputs)==1 and len(result.errors)==1

def test_cancel_preserves_completed_output_and_no_partial(tmp_path):
    req=request(tmp_path);token=CancelToken()
    def emit(e):
        if e.get('kind')=='output':token.cancel()
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env_with_text(['one','two'])):
        result=run_extraction(req,emit,token)
    assert result.status=='cancelled' and len(result.outputs)==1
    assert not list(Path(req.output_root).rglob('*.partial'))

def test_disk_full_is_failure_not_success(tmp_path):
    req=request(tmp_path)
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env_with_text(['one'])),patch.object(Path,'write_bytes',side_effect=OSError(28,'disk full')):
        result=run_extraction(req)
    assert result.status=='failed' and not result.outputs
    assert not list(Path(req.output_root).rglob('*.partial'))

def test_retry_keeps_previous_output(tmp_path):
    req=request(tmp_path)
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env_with_text(['same'])):
        first=run_extraction(req);second=run_extraction(req)
    assert first.outputs[0]['path']!=second.outputs[0]['path']
    assert Path(first.outputs[0]['path']).read_bytes()=='hello中文'.encode()

def test_unknown_signature_is_explicit_partial(tmp_path):
    req=request(tmp_path);Path(req.paths[0]).write_bytes(b'not-unity')
    result=run_extraction(req)
    assert result.status=='partial' and result.skipped and not result.outputs

def test_source_root_is_read_only(tmp_path):
    req=request(tmp_path);req.output_root=str(Path(req.source_root)/'out')
    with pytest.raises(ValueError):run_extraction(req)
    assert not Path(req.output_root).exists()

def test_raw_text_mode_preserves_signed_bytes_without_decoding(tmp_path):
    req=request(tmp_path);req.mode='raw'
    class Obj:
        type=SimpleNamespace(name='TextAsset');path_id=1
        def read(self):return SimpleNamespace(m_Name='something',m_Script='{"a":1}')
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=SimpleNamespace(objects=[Obj()],container={})):
        result=run_extraction(req)
    assert len(result.outputs)==1 and result.outputs[0]['kind']=='text_raw'
    assert Path(result.outputs[0]['path']).read_bytes()==b'{"a":1}'

def test_selected_object_does_not_export_unrelated_spine_group(tmp_path):
    req=request(tmp_path);req.kinds=['text','spine'];req.object_ids={req.paths[0]:['0']}
    unrelated={'id':'100','name':'unrelated','object_ids':{'100','101'},'files':[('bad.skel',b'data','spine_skeleton')]}
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env_with_text(['selected'])),patch('arknights_unpacker.extraction.spine.iter_spine_groups',return_value=iter([unrelated])):
        result=run_extraction(req)
    assert len(result.outputs)==1 and result.outputs[0]['object_id']=='0'
