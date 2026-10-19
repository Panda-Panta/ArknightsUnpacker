"""Image alpha composition uses Material object references, never name guesses."""
from __future__ import annotations

def _key(obj,path_id=None):
    return id(getattr(obj,'assets_file',None)),str(obj.path_id if path_id is None else path_id)

def combine_alpha(rgb,alpha):
    image=rgb.convert('RGBA')
    mask=alpha.convert('L')
    if mask.size!=image.size:mask=mask.resize(image.size)
    image.putalpha(mask)
    return image

def material_alpha_pairs(env,on_error=None):
    pairs={}
    for obj in env.objects:
        if obj.type.name!='Material':continue
        try:
            tree=obj.read_typetree()
            envs=tree['m_SavedProperties']['m_TexEnvs']
            envs=dict(envs) if isinstance(envs,list) else envs
            rgb=envs.get('_MainTex',{}).get('m_Texture',{})
            alpha=envs.get('_AlphaTex',{}).get('m_Texture',{})
        except Exception as e:
            if on_error:on_error('Material '+str(obj.path_id)+' 无法读取透明通道引用: '+str(e))
            continue
        if not rgb.get('m_PathID') or not alpha.get('m_PathID'):continue
        # FileID zero is local to this Material's serialized assets file. External
        # RGB cannot be associated by path_id alone; do not guess across files.
        if rgb.get('m_FileID',0)!=0:continue
        pairs.setdefault(_key(obj,rgb['m_PathID']),[]).append({'material':str(obj.path_id),'alpha':alpha})
    return pairs

def texture_image(obj,data,env,pairs):
    entries=pairs.get(_key(obj),[])
    if not entries:return data.image,None
    references={(e['alpha'].get('m_FileID',0),e['alpha']['m_PathID']) for e in entries}
    if len(references)!=1:raise ValueError('同一RGB存在冲突的Material Alpha引用，拒绝推断配对')
    file_id,alpha_id=next(iter(references))
    if file_id!=0:raise ValueError('Material Alpha位于外部依赖包，当前环境不可确认')
    alpha=next((x for x in env.objects if _key(x)==_key(obj,alpha_id)),None)
    if alpha is None or alpha.type.name!='Texture2D':raise ValueError('Material明确引用的Alpha纹理缺失')
    image=combine_alpha(data.image,alpha.read().image)
    return image,{'rgb':str(obj.path_id),'alpha':str(alpha_id),'materials':[e['material'] for e in entries],'pairing':'Material._MainTex/_AlphaTex'}
