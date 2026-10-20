"""Image alpha composition uses Material object references, never name guesses."""
from __future__ import annotations
import hashlib

def _key(obj,path_id=None):
    return id(getattr(obj,'assets_file',None)),str(obj.path_id if path_id is None else path_id)

def combine_alpha(rgb,alpha):
    """Keep the RGB texture's native pixels; align only its explicit alpha mask."""
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


def full_texture_sprite_aliases(env,pairs,check):
    """Prove full-image Sprite aliases before deciding whole-package PNG paths.

    References are local to one serialized file. Crop/atlas/rotation/polygon
    cases remain independent exports. Even a full rectangle may use a tight
    mesh, so native RGBA pixels must match the texture's actual export too.
    Maps use reader identity; emitted completion evidence uses Unity path IDs.
    """
    textures={_key(obj):obj for obj in env.objects if obj.type.name=='Texture2D'}
    fingerprints={};aliases={};redundant=set()
    def fingerprint(image):
        return image.size,hashlib.sha256(image.convert('RGBA').tobytes()).digest()
    for sprite in env.objects:
        check()
        if sprite.type.name!='Sprite':continue
        try:
            tree=sprite.read_typetree();render=tree['m_RD'];reference=render['texture']
            if reference.get('m_FileID',0)!=0:continue
            texture=textures.get(_key(sprite,reference.get('m_PathID')))
            if texture is None:continue
            if tree.get('m_AtlasTags') or tree.get('m_SpriteAtlas',{}).get('m_PathID') or tree.get('m_IsPolygon'):continue
            if (int(render['settingsRaw'])>>2)&15:continue
            if render.get('downscaleMultiplier',1)!=1:continue
            if any(offset.get(axis,0)!=0 for offset in (tree.get('m_Offset',{}),render.get('textureRectOffset',{})) for axis in ('x','y')):continue
            data=texture.read();width,height=data.m_Width,data.m_Height
            expected={'x':0,'y':0,'width':width,'height':height}
            if width<=0 or height<=0 or any(rect.get(key)!=value for rect in (tree['m_Rect'],render['textureRect']) for key,value in expected.items()):continue
            identity=id(texture)
            if identity not in fingerprints:
                image,_=texture_image(texture,data,env,pairs)
                fingerprints[identity]=fingerprint(image)
            if fingerprints[identity]!=fingerprint(sprite.read().image):continue
        except Exception:
            # Optional duplicate detection must not turn unsupported metadata
            # into lost pictures; the normal export path retains diagnostics.
            continue
        check()
        aliases.setdefault(identity,[]).append(str(sprite.path_id))
        redundant.add(id(sprite))
    return aliases,redundant
