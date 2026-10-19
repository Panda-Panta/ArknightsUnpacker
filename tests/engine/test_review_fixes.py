import hashlib,json,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from PIL import Image
from arknights_unpacker.contracts import ExtractionRequest
from arknights_unpacker.extraction.engine import run_extraction
from arknights_unpacker.extraction.tables import load_local_tables

class Texture:
    type=SimpleNamespace(name='Texture2D')
    def __init__(self,id,name,image):self.path_id=id;self.data=SimpleNamespace(m_Name=name,image=image)
    def read(self):return self.data
    def get_raw_data(self):return b'original-texture'
class Material:
    type=SimpleNamespace(name='Material')
    def __init__(self,id,rgb,alpha):self.path_id=id;self.rgb=rgb;self.alpha=alpha
    def read_typetree(self):return {'m_SavedProperties':{'m_TexEnvs':[('_MainTex',{'m_Texture':{'m_FileID':0,'m_PathID':self.rgb}}),('_AlphaTex',{'m_Texture':{'m_FileID':0,'m_PathID':self.alpha}})]}}
    def read(self):return SimpleNamespace(m_Name='material')

def image_fixture(tmp_path):
    p=tmp_path/'source.bin';p.write_bytes(b'UnityFS-fixture')
    rgb=Texture(11,'rgb',Image.new('RGBA',(2,1),(20,40,60,255)))
    mask=Image.new('RGB',(2,1));mask.putdata([(0,0,0),(255,255,255)])
    alpha=Texture(12,'unrelated_name',mask)
    return p,SimpleNamespace(objects=[rgb,alpha,Material(13,11,12)],container={})

def test_image_only_uses_explicit_material_alpha_and_only_selected_output(tmp_path):
    p,env=image_fixture(tmp_path)
    req=ExtractionRequest([str(p)],str(tmp_path/'out'),kinds=['image'],object_ids={str(p):['11']})
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env):x=run_extraction(req)
    assert x.status=='succeeded' and len(x.outputs)==1
    assert Image.open(x.outputs[0]['path']).getchannel('A').getextrema()==(0,255)
    assert x.outputs[0]['image_pairing']['alpha']=='12'

def test_candidate_replaced_after_validation_cannot_be_complete(tmp_path):
    root=tmp_path/'resources';root.mkdir()
    old=b'UnityFS-old';new=b'UnityFS-new';md5=hashlib.md5(old).hexdigest()
    for n in ('character.bin','skill.bin'):(root/n).write_bytes(old)
    (root/'fixture.idx').write_bytes(b'fixture')
    manifest={'manifestName':'fixture.idx','manifestVersion':'test','versionId':'test','abInfos':[{'name':n,'md5':md5,'abSize':len(old)} for n in ('character.bin','skill.bin')]}
    (root/'hot_update_list.json').write_text(json.dumps(manifest))
    index={'assets':[{'assetName':'character_table','bundle':'character.bin'},{'assetName':'skill_table','bundle':'skill.bin'}]}
    class Obj:
        type=SimpleNamespace(name='TextAsset');path_id=1
        def __init__(self,name):self.name=name
        def read(self):return SimpleNamespace(m_Name=self.name,m_Script='{"ok":1}')
    saved=(root/'skill.bin').stat()
    def load(path,**kwargs):
        if path.name=='character.bin':
            (root/'skill.bin').write_bytes(new)
            os.utime(root/'skill.bin',ns=(saved.st_atime_ns,saved.st_mtime_ns))
        return SimpleNamespace(objects=[Obj('character_table' if path.name=='character.bin' else 'skill_table')])
    with patch('arknights_unpacker.extraction.tables.read_resource_manifest',return_value=index),patch('arknights_unpacker.extraction.tables.load_bundle',side_effect=load):
        try:x=load_local_tables(root,tmp_path/'cache',names={'character_table','skill_table'})
        except OSError:return
    assert not x.complete
    assert 'skill_table' not in x.tables

def spine_env():
    rgb=Texture(5,'same',Image.new('RGBA',(2,1),(1,2,3,255)))
    mask=Image.new('RGB',(2,1));mask.putdata([(0,0,0),(255,255,255)])
    alpha=Texture(6,'unexpected-mask-name',mask)
    class Text:
        type=SimpleNamespace(name='TextAsset')
        def __init__(self,id,name,raw):self.path_id=id;self.name=name;self.raw=raw
        def read(self):return SimpleNamespace(m_Name=self.name,m_Script=self.raw)
    class Mono:
        type=SimpleNamespace(name='MonoBehaviour')
        def __init__(self,id,tree):self.path_id=id;self.tree=tree
        def read_typetree(self):return self.tree
        def read(self):return SimpleNamespace(m_Name=self.tree.get('m_Name','mono'))
    ref=lambda n:{'m_FileID':0,'m_PathID':n}
    objects=[Text(1,'hero.skel','binary'),Text(2,'hero.atlas','\nhero.png\nsize: 2,1\n'),Mono(3,{'atlasFile':ref(2),'materials':[ref(4)]}),Material(4,5,6),rgb,alpha,Mono(7,{'m_Name':'hero','skeletonJSON':ref(1),'atlasAssets':[ref(3)]})]
    return SimpleNamespace(objects=objects,container={})

@pytest.mark.parametrize('member',[3,4,6])
def test_spine_complete_dependency_members_select_the_group(tmp_path,member):
    p=tmp_path/'source.bin';p.write_bytes(b'UnityFS-fixture')
    req=ExtractionRequest([str(p)],str(tmp_path/'out'),kinds=['spine'],object_ids={str(p):[str(member)]})
    parser=SimpleNamespace(read_skeleton_data=lambda raw:SimpleNamespace(animations=[]))
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=spine_env()),patch('spine_asset.v38.SkeletonBinary',return_value=parser):x=run_extraction(req)
    assert x.status=='succeeded' and len(x.outputs)==4
    group=next(o for o in x.outputs if o['kind']=='spine_group')
    receipt=json.loads(Path(group['path']).read_text())
    assert {'1','2','3','4','5','6','7'}<=set(receipt['objectIds'])
    png=next(o for o in x.outputs if o['kind']=='spine_texture')
    assert Image.open(png['path']).getchannel('A').getextrema()==(0,255)

def test_conflicting_explicit_alpha_references_are_not_guessed(tmp_path):
    p,env=image_fixture(tmp_path);env.objects.append(Material(14,11,999))
    req=ExtractionRequest([str(p)],str(tmp_path/'out'),kinds=['image'],object_ids={str(p):['11']})
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env):x=run_extraction(req)
    assert x.status=='failed' and not x.outputs and '冲突' in x.errors[0]['error']

def test_missing_explicit_alpha_is_diagnostic_not_opaque_success(tmp_path):
    p,env=image_fixture(tmp_path);env.objects=[o for o in env.objects if o.path_id!=12]
    req=ExtractionRequest([str(p)],str(tmp_path/'out'),kinds=['image'],object_ids={str(p):['11']})
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env):x=run_extraction(req)
    assert x.status=='failed' and not x.outputs and '缺失' in x.errors[0]['error']

def test_raw_texture_does_not_change_original_object_bytes(tmp_path):
    p,env=image_fixture(tmp_path)
    req=ExtractionRequest([str(p)],str(tmp_path/'out'),mode='raw',kinds=['image'],object_ids={str(p):['11']})
    with patch('arknights_unpacker.extraction.engine.load_bundle',return_value=env):x=run_extraction(req)
    assert len(x.outputs)==1 and Path(x.outputs[0]['path']).read_bytes()==b'original-texture'

def test_unity_parser_receives_the_exact_bytes_used_for_digest_proof(tmp_path):
    from arknights_unpacker.extraction.tables import _decode_bundle
    from arknights_unpacker.contracts import null_progress
    p=tmp_path/'table.bin';payload=b'UnityFS-verified-snapshot';p.write_bytes(payload);stat=p.stat()
    expected={'size':len(payload),'mtime_ns':stat.st_mtime_ns,'sha256':hashlib.sha256(payload).hexdigest(),'expected_md5':hashlib.md5(payload).hexdigest()}
    class Obj:
        path_id=1;type=SimpleNamespace(name='TextAsset')
        def read(self):return SimpleNamespace(m_Name='character_table',m_Script='{"ok":1}')
    with patch('arknights_unpacker.extraction.tables.load_bundle',return_value=SimpleNamespace(objects=[Obj()])) as parser:
        decoded=_decode_bundle(p,{'character_table'},'base',{},null_progress,None,expected=expected)
    assert parser.call_args.kwargs['data']==payload
    proof=decoded['character_table'].field_evidence['decodedPayloadVerification']
    assert proof['expectedMd5Verified'] and proof['md5']==hashlib.md5(payload).hexdigest()
    assert decoded['character_table'].source.sha256==hashlib.sha256(payload).hexdigest()
