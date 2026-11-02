"""Image alpha follows Material and AVG configuration references, never names."""
from __future__ import annotations
from copy import copy
import hashlib

from .character_config import iter_character_groups

def _key(obj,path_id=None):
    return id(getattr(obj,'assets_file',None)),str(obj.path_id if path_id is None else path_id)

def combine_alpha(rgb,alpha,*,channel='L'):
    """Keep the RGB texture's native pixels; align only its explicit alpha mask."""
    image=rgb.convert('RGBA')
    mask=alpha.convert('RGBA').getchannel(channel) if channel!='L' else alpha.convert('L')
    if mask.size!=image.size:mask=mask.resize(image.size)
    image.putalpha(mask)
    return image

def material_alpha_pairs(env,on_error=None):
    """Keep the existing entry point; AVG also supplies explicit Sprite alpha."""
    pairs={}
    objects={_key(obj):obj for obj in env.objects}
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
        if rgb.get('m_FileID',0)!=0:
            if on_error:on_error('Material '+str(obj.path_id)+' 的RGB位于外部依赖包，当前环境不可确认')
            continue
        pairs.setdefault(_key(obj,rgb['m_PathID']),[]).append({'material':str(obj.path_id),'alpha':alpha})
    for group in iter_character_groups(env,on_error=on_error):
        reader=group['reader']
        for index,entry in enumerate(group['entries']):
            if not isinstance(entry,dict):
                if on_error:on_error('角色配置 '+group['config_id']+' 存在无效图片条目')
                continue
            sprite_ref,alpha=entry.get('sprite'),entry.get('alphaTex')
            if not isinstance(sprite_ref,dict) or not sprite_ref.get('m_PathID'):
                if on_error:on_error('角色配置 '+group['config_id']+' 的Sprite引用缺失')
                continue
            # A null alpha means this entry uses the Sprite's embedded alpha.
            if not isinstance(alpha,dict) or not alpha.get('m_PathID'):continue
            if sprite_ref.get('m_FileID',0)!=0:
                if on_error:on_error('角色配置 '+group['config_id']+' 的Sprite位于外部依赖包，当前环境不可确认')
                continue
            sprite=objects.get(_key(reader,sprite_ref['m_PathID']))
            if sprite is None or sprite.type.name!='Sprite':
                if on_error:on_error('角色配置 '+group['config_id']+' 明确引用的Sprite缺失')
                continue
            record={'alpha':dict(alpha),'configuration':{'config_id':group['config_id'],
                    'group_index':group['group_index'],'entry_index':index,'sprite':str(sprite.path_id)}}
            pairs.setdefault(_key(sprite),[]).append(record)
            try:
                texture=sprite.read_typetree()['m_RD']['texture']
                if texture.get('m_FileID',0)!=0:
                    raise ValueError('Sprite纹理位于外部依赖包，当前环境不可确认')
                if not texture.get('m_PathID'):
                    raise ValueError('Sprite明确引用的RGB纹理缺失')
            except Exception as exc:
                if on_error:on_error('角色配置 '+group['config_id']+' 无法关联Sprite纹理: '+str(exc))
            else:
                pairs.setdefault(_key(sprite,texture['m_PathID']),[]).append(record)
    return pairs


def _alpha_reference(obj,env,entries):
    references={(e['alpha'].get('m_FileID',0),e['alpha']['m_PathID']) for e in entries}
    if len(references)!=1:raise ValueError('同一图片存在冲突的Alpha引用，拒绝推断配对')
    file_id,alpha_id=next(iter(references))
    if file_id!=0:raise ValueError('明确引用的Alpha位于外部依赖包，当前环境不可确认')
    alpha=next((x for x in env.objects if _key(x)==_key(obj,alpha_id)),None)
    if alpha is None or alpha.type.name!='Texture2D':raise ValueError('明确引用的Alpha纹理缺失')
    return alpha


def _pairing(obj,alpha,entries,*,sprite=False):
    result={'rgb':str(obj.path_id),'alpha':str(alpha.path_id),
            'materials':list(dict.fromkeys(e['material'] for e in entries if 'material' in e)),
            'pairing':'Material._MainTex/_AlphaTex'}
    configurations=[e['configuration'] for e in entries if 'configuration' in e]
    if configurations:
        result['configurations']=configurations
        result['pairing']='character_config.sprite/alphaTex'
    if sprite:result['sprite']=str(obj.path_id)
    return result


def texture_image(obj,data,env,pairs):
    entries=pairs.get(_key(obj),[])
    if not entries:return data.image,None
    alpha=_alpha_reference(obj,env,entries)
    channel='R' if any('configuration' in e for e in entries) else 'L'
    image=combine_alpha(data.image,alpha.read().image,channel=channel)
    return image,_pairing(obj,alpha,entries)


def sprite_image(obj,data,env,pairs):
    """Supply AVG alpha to UnityPy's crop/rotation/mesh renderer on a copy."""
    entries=pairs.get(_key(obj),[])
    if not entries:return data.image,None
    alpha=_alpha_reference(obj,env,entries)
    if getattr(data,'m_SpriteAtlas',None) or getattr(data,'m_AtlasTags',None):
        raise ValueError('带独立Alpha的Sprite使用图集，当前环境不可确认渲染引用')
    render=data.m_RD
    texture=getattr(render,'texture',None)
    if texture is not None and texture.m_FileID!=0:
        raise ValueError('Sprite明确引用的RGB纹理位于外部依赖包，当前环境不可确认')
    embedded=getattr(render,'alphaTexture',None)
    if embedded and (embedded.m_FileID!=0 or embedded.m_PathID!=alpha.path_id):
        raise ValueError('Sprite原有Alpha与角色配置存在冲突，拒绝推断配对')
    from UnityPy.classes import PPtr
    patched=copy(data)
    patched.m_RD=copy(render)
    patched.m_RD.alphaTexture=PPtr(m_FileID=0,m_PathID=alpha.path_id,assetsfile=getattr(obj,'assets_file',None))
    image=patched.image
    evidence=_pairing(obj,alpha,entries,sprite=True)
    if texture is not None:evidence['rgb']=str(texture.path_id)
    return image,evidence


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
            sprite_picture,_=sprite_image(sprite,sprite.read(),env,pairs)
            if fingerprints[identity]!=fingerprint(sprite_picture):continue
        except Exception:
            # Optional duplicate detection must not turn unsupported metadata
            # into lost pictures; the normal export path retains diagnostics.
            continue
        check()
        aliases.setdefault(identity,[]).append(str(sprite.path_id))
        redundant.add(id(sprite))
    return aliases,redundant
