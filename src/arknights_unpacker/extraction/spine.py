"""Spine groups follow SkeletonData -> AtlasData -> Material texture references."""
from __future__ import annotations
import json
import re
from .unity import raw_text
from .images import combine_alpha

def iter_spine_groups(env,check):
    objects={o.path_id:o for o in env.objects}
    def pointer(ref):
        if ref.get('m_FileID',0)!=0: raise ValueError('Spine依赖位于外部包，需连同依赖包提取')
        obj=objects.get(ref.get('m_PathID'))
        if obj is None: raise ValueError('Spine引用对象缺失: '+str(ref))
        return obj
    for obj in env.objects:
        check()
        if obj.type.name!='MonoBehaviour': continue
        try: tree=obj.read_typetree()
        except Exception: continue
        if not {'skeletonJSON','atlasAssets'}<=tree.keys(): continue
        name=tree.get('m_Name','Spine')
        try:
            skeleton=pointer(tree['skeletonJSON']).read()
            atlas_assets=tree['atlasAssets']
            if not atlas_assets: raise ValueError('SkeletonData缺少atlasAssets')
            atlas_object=pointer(atlas_assets[0])
            atlas_tree=atlas_object.read_typetree()
            atlas=pointer(atlas_tree['atlasFile']).read()
            raw_atlas=raw_text(atlas)
            pages=re.findall(r'(?m)^([^\r\n]+\.(?:png|jpg|jpeg))\r?$',raw_atlas.decode('utf-8'))
            mats=atlas_tree.get('materials',[])
            if len(pages)!=len(mats): raise ValueError(f'Atlas页数{len(pages)}与Material数{len(mats)}不符')
            # Validate binary skeleton with the bundled open-source Spine parser.
            raw_skel=raw_text(skeleton)
            from spine_asset.v38 import SkeletonBinary,SkeletonJson
            skel_data=SkeletonJson().read_skeleton_data(raw_skel.decode('utf-8')) if raw_skel.lstrip().startswith(b'{') else SkeletonBinary().read_skeleton_data(raw_skel)
            files=[(skeleton.m_Name,raw_skel,'spine_skeleton'),(atlas.m_Name,raw_atlas,'spine_atlas')]
            ids={str(obj.path_id),str(tree['skeletonJSON']['m_PathID']),str(atlas_object.path_id),str(atlas_tree['atlasFile']['m_PathID'])}
            material_refs=[]
            for page,matref in zip(pages,mats):
                check()
                material=pointer(matref);ids.add(str(material.path_id))
                mat=material.read_typetree()
                envs=mat['m_SavedProperties']['m_TexEnvs']
                envs=dict(envs) if isinstance(envs,list) else envs
                rgb_obj=pointer(envs['_MainTex']['m_Texture'])
                ids.add(str(rgb_obj.path_id))
                rgb=rgb_obj.read();image=rgb.image.convert('RGBA')
                alpha_ref=envs.get('_AlphaTex',{}).get('m_Texture',{})
                alpha_id=alpha_ref.get('m_PathID',0)
                material_refs.append({'page':page,'rgb':rgb_obj.path_id,'alpha':alpha_id or None,'pairing':'Material._MainTex/_AlphaTex'})
                if alpha_id:
                    alpha=pointer(alpha_ref);ids.add(str(alpha.path_id))
                    image=combine_alpha(image,alpha.read().image)
                files.append((page,image,'spine_texture'))
            receipt={'skeletonDataPathId':str(obj.path_id),'name':name,'skeleton':skeleton.m_Name,'atlas':atlas.m_Name,'pages':pages,'materialReferences':material_refs,'animations':[a.name for a in skel_data.animations],'pairing':'explicit-object-references','objectIds':sorted(ids)}
            files.append(('group.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode('utf-8'),'spine_group'))
            yield {'id':str(obj.path_id),'name':name,'files':files,'object_ids':ids}
        except Exception as e:
            from arknights_unpacker.contracts import CancelledError
            if isinstance(e,CancelledError):raise
            yield {'id':str(obj.path_id),'name':name,'error':f'{type(e).__name__}: {e}'}
