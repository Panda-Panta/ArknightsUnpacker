"""Packet-stream USM demux using WannaCRI; filenames never control output paths."""
from __future__ import annotations
from pathlib import Path
import json
import shutil
import subprocess
import time
from unittest.mock import patch

def extract_usm(source,save,check,emit):
    from wannacri import usm
    import wannacri.usm.usm as usm_module
    from wannacri.usm.types import OpMode
    opened=[]
    builtin_open=open
    def tracked_open(*args,**kwargs):
        handle=builtin_open(*args,**kwargs);opened.append(handle);return handle
    try:
        with patch.object(usm_module,'open',tracked_open,create=True):
            try: media=usm.Usm.open(source,encoding='utf-8');encoding='utf-8'
            except UnicodeDecodeError:
                # PC CRID may contain legacy non-UTF8 filenames. Latin1 preserves
                # metadata bytes; demux payloads are never transcoded or rewritten.
                media=usm.Usm.open(source,encoding='latin1');encoding='latin1-byte-preserving'
        outputs=[]
        for category,items,key in [('video_stream',media.videos,media.video_key),('audio_stream',media.audios,media.audio_key),('alpha_stream',media.alphas,media.video_key)]:
            for index,item in enumerate(items):
                check();filename=item.filename
                def write_stream(target,stream=item,key=key):
                    with target.open('wb') as f:
                        mode=OpMode.NONE if key is None else OpMode.DECRYPT
                        for packet in stream.stream(mode,key):
                            check();f.write(packet[0] if isinstance(packet,tuple) else packet)
                record=save(source,category+'_'+str(index),Path(filename).stem,Path(filename).suffix or '.stream',write_stream,category)
                outputs.append(record)
        if not outputs: raise ValueError('USM未包含可提取流')
        ffprobe=shutil.which('ffprobe');ffmpeg=shutil.which('ffmpeg')
        receipt={'metadataEncoding':encoding,'streamCount':len(outputs),'streams':outputs,'ffprobe':ffprobe,'ffmpeg':ffmpeg,'playableConversion':'not_requested'}
        for rec in outputs:
            if ffprobe:
                proc=subprocess.run([ffprobe,'-v','error','-show_streams','-of','json',rec['path']],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=30)
                if proc.returncode==0: rec['probe']=json.loads(proc.stdout)
                else: rec['probeError']=proc.stderr[-1500:]
        videos=[r for r in outputs if r['kind']=='video_stream'];audios=[r for r in outputs if r['kind']=='audio_stream']
        if ffmpeg and videos:
            for i,video in enumerate(videos):
                audio=audios[i] if i<len(audios) else None
                def convert(target,video=video,audio=audio):
                    cmd=[ffmpeg,'-v','error','-nostdin','-y','-i',video['path']]
                    if audio:cmd += ['-i',audio['path']]
                    cmd += ['-c:v','copy']
                    if audio:cmd += ['-c:a','aac']
                    cmd += ['-f','matroska',str(target)]
                    log=target.with_suffix(target.suffix+'.log')
                    try:
                        with log.open('w',encoding='utf-8') as stream:
                            proc=subprocess.Popen(cmd,stdout=stream,stderr=stream,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                            try:
                                while proc.poll() is None:check();time.sleep(.05)
                            finally:
                                if proc.poll() is None:proc.terminate();proc.wait(timeout=5)
                        if proc.returncode: raise ValueError('FFmpeg转换失败: '+log.read_text(encoding='utf-8',errors='replace')[-1200:])
                    finally:log.unlink(missing_ok=True)
                try:
                    converted=save(source,'playable_'+str(i),source.stem,'.mkv',convert,'video_playable')
                    receipt['playableConversion']='succeeded';receipt.setdefault('converted',[]).append(converted)
                except Exception as e:
                    from arknights_unpacker.contracts import CancelledError
                    if isinstance(e,CancelledError):raise
                    receipt['playableConversion']='failed';receipt['conversionError']=str(e)
                    emit({'kind':'diagnostic','message':str(e)})
        elif not ffmpeg:receipt['playableConversion']='ffmpeg_unavailable_original_streams_preserved'
        save(source,'media_receipt',source.stem,'.media.json',json.dumps(receipt,ensure_ascii=False,indent=2).encode('utf-8'),'video_metadata')
    finally:
        for handle in opened:
            handle.close()
