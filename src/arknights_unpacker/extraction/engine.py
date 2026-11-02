"""Synchronous extraction service. Run through the application-owned worker process."""
from __future__ import annotations
import hashlib
import json
import re
import os
import uuid
from pathlib import Path
from arknights_unpacker.contracts import ExtractionResult, CancelledError, null_progress
from .unity import load_bundle, raw_text
from .decoder import decode_text_bytes
from .images import full_texture_sprite_aliases, material_alpha_pairs, sprite_image, texture_image
from arknights_unpacker.library.preview_types import source_preview_type

def safe_component(name):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(name)).strip(' .')
    if not name or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'{p}{i}' for p in ('COM','LPT') for i in range(1,10)]}: name='asset_'+name
    return name[:160]

def validate_output_root(output,source_roots):
    target=Path(output).resolve()
    for root in source_roots:
        root=Path(root).resolve()
        if target==root or root in target.parents: raise ValueError('输出目录不得位于游戏/输入根目录内')
    return target

def _roots(request):
    roots=[Path(request.source_root)] if request.source_root else []
    for path in request.paths:
        for p in Path(path).resolve().parents:
            if p.name=='Arknights_Data': roots.append(p.parent);break
    return roots

def _object_paths(env):
    result={}
    for logical,ptr in env.container.items():
        try: result[str(ptr.path_id)]=logical
        except AttributeError: pass
    return result

def _object_name(obj):
    # UnityPy's name-only reader avoids parsing texture/audio/MonoBehaviour
    # payloads merely to populate the inventory. Keep the existing fallback
    # for formats where the installed type tree has no name-peek node.
    try:
        peek=getattr(obj,'peek_name',None)
        name=peek() if callable(peek) else None
        if isinstance(name,str):return name
    except Exception:
        pass
    try:return getattr(obj.read(),'m_Name','')
    except Exception:return ''

def list_bundle_objects(path):
    path=Path(path)
    with path.open('rb') as stream:head=stream.read(16)
    candidate=source_preview_type(path)
    if candidate and not head.startswith((b'UnityFS',b'UnityRaw',b'UnityWeb')):
        return [{'id':'source','type':candidate[0],'name':path.name,
                 'logical_path':path.name,'previewable':True,'size':path.stat().st_size}]
    env=load_bundle(path);paths=_object_paths(env);items=[]
    for obj in env.objects:
        name=''
        if obj.type.name in {'TextAsset','Texture2D','Sprite','AudioClip','VideoClip','Material','MonoBehaviour'}:
            name=_object_name(obj)
        # Serialized object bytes exclude any separate streaming payloads.
        # ObjectReader already has this metadata; do not read/decode for size.
        item={'id':str(obj.path_id),'type':obj.type.name,'name':name,'logical_path':paths.get(str(obj.path_id),''),'size':getattr(obj,'byte_size',None)}
        if obj.type.name=='VideoClip':item['previewable']=False
        items.append(item)
    return items

def run_extraction(request,emit=null_progress,cancel=None):
    if request.mode not in ('auto','raw'):raise ValueError('不支持的解包模式: '+request.mode)
    result=ExtractionResult(request_id=request.request_id)
    output=validate_output_root(request.output_root,_roots(request))
    output.mkdir(parents=True,exist_ok=True)
    kinds=set(request.kinds)
    def check():
        if cancel: cancel.check()
    def complete_object(source,obj_id,**extra):
        check()
        emit({'kind':'object_complete','source':str(source),'object_id':str(obj_id),**extra})
    def complete_source(source):
        check()
        emit({'kind':'source_complete','source':str(source)})
    def copy_source(source,target):
        with source.open('rb') as original,target.open('wb') as copied:
            while True:
                check()
                block=original.read(1024*1024)
                if not block:break
                copied.write(block)
    def save(source,obj_id,name,suffix,content,kind,*,group=None,metadata=None,flat=False):
        check()
        bucket=output if flat and not group else output/(safe_component(source.stem)+'_'+hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:10])
        if group: bucket=bucket/safe_component(group)
        bucket.mkdir(parents=True,exist_ok=True)
        target=bucket/(safe_component(name)+suffix if group else safe_component(name)+'__'+safe_component(obj_id)+suffix)
        if target.exists():
            # Never overwrite previous output; retry gets an explicit unique output.
            index=2
            while target.with_stem(target.stem+'_'+str(index)).exists(): index+=1
            target=target.with_stem(target.stem+'_'+str(index))
        temp=target.with_name(target.name+'.'+uuid.uuid4().hex+'.partial')
        try:
            if callable(content): content(temp)
            else: temp.write_bytes(content)
            check()
            while True:
                try:
                    descriptor=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(descriptor);break
                except FileExistsError:
                    target=target.with_stem(target.stem+'_'+uuid.uuid4().hex[:8])
            try:temp.replace(target)
            except BaseException:
                target.unlink(missing_ok=True);raise
        finally:
            temp.unlink(missing_ok=True)
        item={'source':str(source),'object_id':obj_id,'path':str(target),'kind':kind,'size':target.stat().st_size}
        if metadata:item.update(metadata)
        result.outputs.append(item);emit({**item,'kind':'output','asset_kind':kind});return item
    try:
        for index,raw_path in enumerate(request.paths):
            check();source=Path(raw_path).resolve()
            emit({'kind':'progress','stage':'extract','index':index,'total':len(request.paths),'path':str(source)})
            if not source.is_file():
                result.errors.append({'source':str(source),'error':'输入不是文件'});continue
            try:
                with source.open('rb') as f: head=f.read(16)
                candidate=source_preview_type(source)
                if candidate and not head.startswith((b'UnityFS',b'UnityRaw',b'UnityWeb')):
                    selected=set(request.object_ids.get(raw_path,request.object_ids.get(str(source),[])))
                    if selected and not (selected & ({'source','manifest'} if source.suffix.lower()=='.idx' else {'source'})):
                        result.skipped.append({'source':str(source),'reason':'未选中源文件对象'});continue
                    source_kind=candidate[1]
                    if source_kind not in kinds and not (source_kind=='spine' and 'text' in kinds):
                        result.skipped.append({'source':str(source),'reason':'源文件不属于所选资源类型'});continue
                    if source.suffix.lower()=='.usm':
                        if request.mode=='raw':save(source,'source',source.stem,'.usm',lambda p:copy_source(source,p),'video_source')
                        else:
                            from .usm import extract_usm
                            extract_usm(source,save,check,emit)
                    elif source.suffix.lower()=='.idx':
                        from .manifest import read_resource_manifest
                        data=read_resource_manifest(source)
                        save(source,'manifest',source.stem,'.json',json.dumps(data,ensure_ascii=False,indent=2).encode(),'manifest')
                    else:
                        output_kind={'text':'text_raw','spine':'spine_source'}.get(source_kind,source_kind)
                        save(source,'source',source.stem,source.suffix,lambda p:copy_source(source,p),output_kind,
                             metadata={'passthrough':True})
                    complete_object(source,'source')
                    complete_source(source)
                    continue
                if not head.startswith((b'UnityFS',b'UnityRaw',b'UnityWeb')):
                    result.skipped.append({'source':str(source),'reason':'不支持的文件签名'});continue
                env=load_bundle(source)
                if 'expression' in kinds:
                    if request.mode=='raw':raise ValueError('表情差分制作需要自动处理模式')
                    from .characters import iter_character_images
                    before_errors=len(result.errors);before_outputs=len(result.outputs)
                    for composition in iter_character_images(env,request.character_options,check):
                        check()
                        metadata=composition.get('metadata',{})
                        obj_id='character:'+str(metadata.get('entry_id',composition.get('name','unknown')))
                        if composition.get('error'):
                            result.errors.append({'source':str(source),'object_id':obj_id,'error':composition['error']})
                            continue
                        image=composition['image']
                        save(source,obj_id,composition['name'],'.png',lambda p,img=image:img.save(p,format='PNG'),
                             'character_expression',metadata={'image_size':list(image.size),'character':metadata})
                        complete_object(source,obj_id)
                    if kinds=={'expression'}:
                        if len(result.errors)==before_errors and len(result.outputs)>before_outputs:complete_source(source)
                        continue
                pairs=material_alpha_pairs(env,lambda message:result.skipped.append({'source':str(source),'reason':message})) if 'image' in kinds and request.mode=='auto' else {}
                selected=set(request.object_ids.get(raw_path,request.object_ids.get(str(source),[])))
                # Decide paths before the first output event. Count only selected
                # decoded picture candidates, not Material/text dependencies. A
                # later decode failure or cancellation must never relocate files
                # already recorded in progress events and recovery checkpoints.
                selected_image_object_count=sum(1 for obj in env.objects if obj.type.name in {'Texture2D','Sprite'} and (not selected or str(obj.path_id) in selected)) if 'image' in kinds and request.mode=='auto' else 0
                # Object selection is explicit: preserve every requested object.
                # Only automatic whole-package images collapse proven aliases.
                image_aliases,aliased_objects=full_texture_sprite_aliases(env,pairs,check) if selected_image_object_count and not selected else ({},set())
                selected_image_count=selected_image_object_count-len(aliased_objects)
                if 'spine' in kinds and request.mode!='raw':
                    from .spine import iter_spine_groups
                    for group in iter_spine_groups(env,check):
                        if selected and not (selected & group.get('object_ids',{group['id']})):continue
                        if 'error' in group:
                            result.errors.append({'source':str(source),'object_id':group['id'],'error':group['error']});continue
                        groupname=group['name']+'__'+group['id']
                        bucket=output/(safe_component(source.stem)+'_'+hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:10])
                        basegroup=groupname;counter=2
                        bucket.mkdir(parents=True,exist_ok=True)
                        while True:
                            try:(bucket/safe_component(groupname)).mkdir(exist_ok=False);break
                            except FileExistsError:groupname=basegroup+'_'+str(counter);counter+=1
                        for filename,content,kind in group['files']:
                            if hasattr(content,'save'):
                                image=content
                                save(source,group['id'],filename,'',lambda p,img=image:img.save(p,format='PNG'),kind,group=groupname)
                            else: save(source,group['id'],filename,'',content,kind,group=groupname)
                        complete_object(source,group['id'],group_id=str(group['id']),object_ids=sorted(group['object_ids']))
                selected=set(request.object_ids.get(raw_path,request.object_ids.get(str(source),[])))
                for obj in env.objects:
                    check()
                    obj_id=str(obj.path_id)
                    if selected and obj_id not in selected: continue
                    if id(obj) in aliased_objects:continue
                    typ=obj.type.name
                    if typ not in {'Texture2D','Sprite','TextAsset','AudioClip'}: continue
                    try:
                        output_start=len(result.outputs)
                        data=obj.read();name=getattr(data,'m_Name','') or typ
                        if typ in {'Texture2D','Sprite'} and ('image' in kinds or ('spine' in kinds and request.mode=='raw')):
                            if request.mode=='raw':
                                save(source,obj_id,name,'.'+typ+'.bin',obj.get_raw_data(),'image_serialized');complete_object(source,obj_id);continue
                            image,pairing=texture_image(obj,data,env,pairs) if typ=='Texture2D' else sprite_image(obj,data,env,pairs)
                            # Resource pixels come directly from Unity's decoded
                            # texture / cropped Sprite; report and preview sizes
                            # are display settings and never enter this path.
                            metadata={'image_size':list(image.size),'image_layout':'flat' if selected_image_count==1 else 'package','selected_image_count':selected_image_count,'selected_image_object_count':selected_image_object_count}
                            if pairing:metadata['image_pairing']=pairing
                            if id(obj) in image_aliases:metadata['image_aliases']=image_aliases[id(obj)]
                            save(source,obj_id,name,'.png',lambda p,img=image:img.save(p,format='PNG'),'image',metadata=metadata,flat=selected_image_count==1)
                        elif typ=='TextAsset' and ('text' in kinds or 'spine' in kinds):
                            raw=raw_text(data)
                            spine=any(x in name.lower() for x in ('.atlas','.skel','.spine'))
                            if 'text' not in kinds and not spine: continue
                            save(source,obj_id,name,'.bytes',raw,'spine_source' if spine else 'text_raw')
                            if not spine and request.mode!='raw':
                                stem=re.sub(r'[0-9a-f]{6}(?:\.bytes)?$','',name)
                                try:
                                    decoded,evidence=decode_text_bytes(raw,stem)
                                except Exception as e:
                                    try:
                                        raw.decode('utf-8');textual=True
                                    except UnicodeError: textual=False
                                    if not textual: result.skipped.append({'source':str(source),'object_id':obj_id,'reason':'原始字节已保留，解码未支持: '+str(e)})
                                else: save(source,obj_id,name,'.json',json.dumps(decoded,ensure_ascii=False,indent=2).encode('utf-8',errors='backslashreplace'),'text_json')
                        elif typ=='AudioClip' and 'audio' in kinds:
                            if request.mode=='raw':
                                save(source,obj_id,name,'.audio',bytes(data.m_AudioData),'audio_source');complete_object(source,obj_id);continue
                            try:
                                samples=data.samples
                                if not samples: raise ValueError('音频解码未返回样本')
                                for sample_name,sample in samples.items():
                                    suffix=Path(sample_name).suffix or '.wav'
                                    save(source,obj_id,name+'_'+Path(sample_name).stem,suffix,sample,'audio')
                            except Exception as e:
                                # Preserve encoded stream with truthful label when native codec is absent.
                                raw=bytes(data.m_AudioData)
                                save(source,obj_id,name,'.audio',raw,'audio_source')
                                result.skipped.append({'source':str(source),'object_id':obj_id,'reason':'保留音频源，播放格式解码失败: '+str(e)})
                        if len(result.outputs)>output_start:
                            completed_ids=image_aliases.get(id(obj))
                            complete_object(source,obj_id,**({'object_ids':sorted([obj_id,*completed_ids])} if completed_ids else {}))
                    except CancelledError: raise
                    except Exception as e: result.errors.append({'source':str(source),'object_id':obj_id,'error':f'{type(e).__name__}: {e}'})
            except CancelledError: raise
            except Exception as e: result.errors.append({'source':str(source),'error':f'{type(e).__name__}: {e}'})
    except CancelledError:
        result.status='cancelled'
    else:
        result.status='partial' if result.outputs and result.errors else 'failed' if result.errors else 'succeeded'
    if not result.outputs and not result.errors and result.status!='cancelled':
        result.status='partial'
        if not result.skipped: result.skipped.append({'reason':'没有符合所选类型/对象的可导出资源'})
    (output/'extraction-result.json').write_text(json.dumps(vars(result),ensure_ascii=False,indent=2),encoding='utf-8')
    return result
