import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from arknights_unpacker.contracts import ExtractionRequest,CancelToken
from arknights_unpacker.extraction.engine import run_extraction

class JsonObject:
    type=SimpleNamespace(name='TextAsset');path_id=9
    def read(self):return SimpleNamespace(m_Name='native_json',m_Script='{"value":1}')

def request(tmp_path):
    p=tmp_path/'input.bin';p.write_bytes(b'UnityFS-fixture')
    return ExtractionRequest([str(p)],str(tmp_path/'out'),kinds=['text'])

def test_object_complete_follows_all_outputs_once(tmp_path):
    req=request(tmp_path);events=[]
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=SimpleNamespace(objects=[JsonObject()],container={})):
        result=run_extraction(req,events.append)
    assert len(result.outputs)==2
    kinds=[e['kind'] for e in events]
    assert kinds==['progress','output','output','object_complete']
    assert events[-1]['object_id']=='9' and events[-1]['source']==str(Path(req.paths[0]).resolve())

def test_write_failure_after_first_output_does_not_complete_object(tmp_path):
    req=request(tmp_path);events=[];original=Path.write_bytes;calls=0
    def write(path,data):
        nonlocal calls
        calls+=1
        if calls==2:raise OSError('disk-full-on-second-output')
        return original(path,data)
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=SimpleNamespace(objects=[JsonObject()],container={})),patch.object(Path,'write_bytes',write):
        result=run_extraction(req,events.append)
    assert result.status=='partial' and len(result.outputs)==1
    assert not any(e['kind']=='object_complete' for e in events)

def test_cancel_after_outputs_prevents_object_complete(tmp_path):
    req=request(tmp_path);events=[];token=CancelToken()
    def emit(event):
        events.append(event)
        if event['kind']=='output':token.cancel()
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=SimpleNamespace(objects=[JsonObject()],container={})):
        result=run_extraction(req,emit,token)
    assert result.status=='cancelled' and not any(e['kind']=='object_complete' for e in events)

def test_complete_spine_group_reports_all_members_after_all_files(tmp_path):
    req=request(tmp_path);req.kinds=['spine'];events=[]
    group={'id':'100','name':'group','object_ids':{'100','101','102'},'files':[(str(i)+'.bin',b'payload','spine_source') for i in range(4)]}
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=SimpleNamespace(objects=[],container={})),patch('arknights_unpacker.extraction.spine.iter_spine_groups',return_value=iter([group])):
        result=run_extraction(req,events.append)
    assert result.status=='succeeded' and len(result.outputs)==4
    done=[e for e in events if e['kind']=='object_complete']
    assert len(done)==1 and events[-1]==done[0]
    assert done[0]['group_id']=='100' and done[0]['object_ids']==['100','101','102']
