"""Layered outpainting and pose/line guidance for non-explicit illustrations.

Annotations use original-image pixel coordinates, including negative values outside
the original. The UI preview size never changes the saved coordinate system.
"""
import argparse
import hashlib
import json
import math
import secrets
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'ComfyUI' / 'output'
POSE_MODEL = 'xinsir_controlnet_openpose_sdxl.safetensors'
CANNY_MODEL = 'xinsir_controlnet_canny_sdxl.safetensors'
JOINTS = ['nose', 'neck', 'right_shoulder', 'right_elbow', 'right_wrist',
          'left_shoulder', 'left_elbow', 'left_wrist', 'right_hip', 'right_knee',
          'right_ankle', 'left_hip', 'left_knee', 'left_ankle', 'right_eye',
          'left_eye', 'right_ear', 'left_ear']
BONES = [(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),
         (1,11),(11,12),(12,13),(1,0),(0,14),(14,16),(0,15),(15,17)]
COLORS = [(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),
          (85,255,0),(0,255,0),(0,255,85),(0,255,170),(0,255,255),
          (0,170,255),(0,85,255),(0,0,255),(85,0,255),(170,0,255),
          (255,0,255),(255,0,170),(255,0,85)]


def number(value, low, high, label, integer=False):
    if isinstance(value, bool):
        raise ValueError(label + '格式错误')
    try:
        n = float(value)
    except (ValueError, TypeError):
        raise ValueError(label + '格式错误')
    if not math.isfinite(n) or not low <= n <= high or (integer and n != int(n)):
        raise ValueError(label + '超出范围')
    return int(n) if integer else n


def load_source(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('原图不存在，请重新选择')
    with Image.open(path) as f:
        if f.width * f.height > 40_000_000:
            raise ValueError('原图超过4000万像素，请先缩小')
        im = ImageOps.exif_transpose(f).convert('RGBA')
        base = Image.new('RGBA', im.size, 'white')
        base.alpha_composite(im)
        return base.convert('RGB')


def validate_project(data):
    if not isinstance(data, dict) or data.get('version', 1) != 1:
        raise ValueError('不支持的补全工程格式')
    source = str(data.get('source', ''))
    im = load_source(source)
    if data.get('source_sha256') and data['source_sha256'] != hashlib.sha256(Path(source).read_bytes()).hexdigest():
        raise ValueError('原图内容已改变，请重新载入图片并检查标注')
    w, h = im.size
    if data.get('source_size') and data['source_size'] != [w, h]:
        raise ValueError('原图尺寸已改变，请重新载入并标注')
    padding = data.get('padding') or {}
    pad = {k:number(padding.get(k,0),0,4096,'扩图尺寸',True)
           for k in ('left','top','right','bottom')}
    cw, ch = w+pad['left']+pad['right'], h+pad['top']+pad['bottom']
    if max(cw,ch) > 8192 or cw*ch > 40_000_000:
        raise ValueError('扩展画布超过8192边长或4000万像素')
    def point(p):
        if not isinstance(p,(list,tuple)) or len(p) != 2:
            raise ValueError('标注点格式错误')
        return [number(p[0],-pad['left'],w+pad['right'],'点横坐标'),
                number(p[1],-pad['top'],h+pad['bottom'],'点纵坐标')]
    joints = data.get('joints') or {}
    if not isinstance(joints,dict) or any(k not in JOINTS for k in joints):
        raise ValueError('未知的人体关节')
    joints = {k:point(v) for k,v in joints.items()}
    paths = {}
    count = 0
    for name in ('strokes','hair'):
        rows = data.get(name) or []
        if not isinstance(rows,list) or len(rows)>1000:
            raise ValueError('笔画数量过多')
        result = []
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('points'),list):
                raise ValueError('笔画格式错误')
            points = row['points']
            count += len(points)
            if count > 50000 or not points:
                raise ValueError('笔画为空或点数过多')
            action = row.get('action','paint')
            if action not in ('paint','erase'):
                raise ValueError('笔画操作错误')
            result.append(dict(points=[point(p) for p in points],
                               width=number(row.get('width',20),1,1024,'笔宽'),action=action))
        paths[name] = result
    instruction = str(data.get('instruction','')).strip()
    if len(instruction)>4000:
        raise ValueError('补全要求限4000字')
    engine = data.get('engine','qwen')
    if engine not in ('qwen','sdxl'):
        raise ValueError('未知的补全引擎')
    locked = data.get('locked') or []
    if not isinstance(locked,list) or any(k not in JOINTS for k in locked):
        raise ValueError('锁定关节格式错误')
    project = dict(version=1,source=str(Path(source).resolve()),source_size=[w,h],
        padding=pad,joints=joints,locked=locked,**paths,instruction=instruction,engine=engine,
        overlap=number(data.get('overlap',0),0,256,'接缝范围',True),
        feather=number(data.get('feather',4),0,32,'羽化',True),
        seed=number(data.get('seed',-1),-1,2**32-1,'种子',True),
        steps=number(data.get('steps',20),4,50,'步数',True),
        candidates=number(data.get('candidates',1),1,3,'方案数',True),
        megapixels=number(data.get('megapixels',1),0.25,1.5,'生成分辨率'),
        pose_strength=number(data.get('pose_strength',0.8),0,1.5,'骨架强度'),
        line_strength=number(data.get('line_strength',0.55),0,1.5,'线稿强度'))
    if data.get('source_sha256'):
        project['source_sha256'] = data['source_sha256']
    return project, im


def draw_path(draw, row, offset, color):
    pts = [(round(p[0]+offset[0]), round(p[1]+offset[1])) for p in row['points']]
    width = max(1,round(row['width']))
    if len(pts)>1:
        draw.line(pts,fill=color,width=width,joint='curve')
    r = width/2
    for x,y in pts:
        draw.ellipse((x-r,y-r,x+r,y+r),fill=color)


def make_layers(project, original):
    p=project['padding']; w,h=original.size
    size=(w+p['left']+p['right'],h+p['top']+p['bottom'])
    offset=(p['left'],p['top'])
    # A repeated edge can be misread as a real object extending to the new border.
    # Use a neutral missing-content field, with the original at its exact offset.
    canvas=Image.new('RGB',size,(235,235,235))
    canvas.paste(original,offset)
    expanded=Image.new('RGBA',size,(0,0,0,0))
    expanded.paste(original.convert('RGBA'),offset)
    transparent=ImageOps.invert(expanded.getchannel('A'))
    mask=Image.new('L',size,255)
    mask.paste(0,(*offset,offset[0]+w,offset[1]+h))
    overlap=project['overlap']
    if overlap and any(p.values()):
        ys,xs=np.mgrid[0:h,0:w]
        distance=np.full((h,w),overlap,dtype=np.float32)
        if p['left']: distance=np.minimum(distance,xs)
        if p['right']: distance=np.minimum(distance,w-1-xs)
        if p['top']: distance=np.minimum(distance,ys)
        if p['bottom']: distance=np.minimum(distance,h-1-ys)
        band=(255*np.clip(1-distance/overlap,0,1)).astype('uint8')
        mask.paste(Image.fromarray(band),offset)
    draw=ImageDraw.Draw(mask)
    for row in project['strokes']:
        draw_path(draw,row,offset,0 if row['action']=='erase' else 255)
    if not mask.getbbox():
        raise ValueError('请扩展画布，或涂抹允许修改的区域；打点和线稿本身不改变选区')
    # Blur is clipped to the explicit editable support: protected pixels stay exact.
    support=mask.point(lambda x:255 if x else 0)
    if project['feather']:
        soft=mask.filter(ImageFilter.GaussianBlur(project['feather']))
        mask=Image.composite(soft,Image.new('L',size),support)
    # Every transparent extension pixel is a generation target, including pixels
    # adjacent to the source edge. Erasing only protects the existing artwork.
    mask=Image.composite(Image.new('L',size,255),mask,transparent)
    pose=Image.new('RGB',size); pd=ImageDraw.Draw(pose)
    guide=Image.new('RGB',size); gd=ImageDraw.Draw(guide)
    j=project['joints']; thick=max(4,round(max(size)/180))
    xy=lambda k:tuple(j[k][i]+offset[i] for i in (0,1))
    for i,(a,b) in enumerate(BONES):
        ka,kb=JOINTS[a],JOINTS[b]
        if ka in j and kb in j:
            pd.line((xy(ka),xy(kb)),fill=COLORS[i],width=thick)
            gd.line((xy(ka),xy(kb)),fill=COLORS[i],width=thick)
    for i,k in enumerate(JOINTS):
        if k in j:
            x,y=xy(k); r=thick
            for d in (pd,gd): d.ellipse((x-r,y-r,x+r,y+r),fill=COLORS[i])
            gd.text((x+r+2,y),k,fill='white',stroke_width=1,stroke_fill='black')
    lines=Image.new('RGB',size); ld=ImageDraw.Draw(lines)
    for row in project['hair']:
        draw_path(ld,row,offset,'white')
        draw_path(gd,row,offset,'white')
    return dict(canvas=canvas,expanded=expanded,mask=mask,pose=pose,lines=lines,guide=guide)


def prepare(data, directory=None):
    project,original=validate_project(data)
    layers=make_layers(project,original)
    token=secrets.token_hex(8)
    folder=Path(directory) if directory else OUT/'completion_projects'/token
    folder.mkdir(parents=True,exist_ok=True)
    project['source_sha256']=hashlib.sha256(Path(project['source']).read_bytes()).hexdigest()
    project_path=folder/'project.json'
    project_path.write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,im in layers.items(): im.save(folder/(name+'.png'))
    return project_path,project,original,layers


def capabilities():
    models=ROOT/'ComfyUI'/'models'
    return dict(pose=(models/'controlnet'/POSE_MODEL).is_file(),
                canny=(models/'controlnet'/CANNY_MODEL).is_file(),
                qwen=(models/'diffusion_models'/'qwen_image_edit_2509_fp8_e4m3fn.safetensors').is_file(),
                joints=JOINTS,bones=BONES,colors=COLORS)


def context_crop(mask):
    """Keep local edits focused while retaining enough adjacent drawing context."""
    w,h=mask.size
    left,top,right,bottom=mask.getbbox()
    margin=max(128,round(max(right-left,bottom-top)*0.5))
    crop=(max(0,left-margin),max(0,top-margin),min(w,right+margin),min(h,bottom+margin))
    if (crop[2]-crop[0])*(crop[3]-crop[1])>w*h*.85:
        return (0,0,w,h)
    return crop


def sampling_size(size,engine,megapixels):
    scale=1.0 if engine=='qwen' else min(1.0,math.sqrt(megapixels*1_000_000/(size[0]*size[1])))
    working=tuple(max(64,round(v*scale/16)*16) for v in size)
    if engine=='qwen':
        # TextEncodeQwenImageEditPlus always encodes references at 1024² area.
        # Match that exact rounding, otherwise reference positions drift relative
        # to the sample latent. Iterate to an idempotent pair before uploading.
        for _ in range(10):
            scale=math.sqrt(1024*1024/(working[0]*working[1]))
            encoded=tuple(round(v*scale/8)*8 for v in working)
            if encoded==working: return working
            working=encoded
        raise ValueError('无法匹配Qwen参考编码尺寸')
    return working


def build_workflow(project,names,seed,prefix):
    import fig
    if project['engine']=='qwen':
        references=[names['guide']] if project['joints'] or project['hair'] else []
        instruction=(('Image 1 is an illustration placed inside an expanded canvas. The uniform light '
            'gray border outside the original rectangle is missing content, not part of the drawing. '
            'Replace this blank border with a coherent continuation of both the subject and background. ')
            if any(project['padding'].values()) else 'Edit image 1 according to the requested local modification. ')
        instruction+=('Keep all existing objects at the same positions and scale. The completed subject '
            'must fit inside the canvas with background margin around the reconstructed outer contour; '
            'do not leave it clipped at the outer image edge. Preserve the original '
            'Japanese illustration rendering, line weight, palette, shadow shapes and lighting. '
            'Reconstruct coherent anatomy and continuity. ')
        if project['joints'] or project['hair']:
            instruction+=('Image 2 is a control map, not another artwork. It has the exact same canvas '
                'coordinates as image 1: labeled colored joints and bones specify pose; white curves '
                'specify hair locks or contour paths. Follow their '
                'positions but do not reproduce any guide marks, dots, text or colored lines. '
                'Use image 1 alone for character identity, framing, colors and style. ')
        # The editor displays purple for readability; inference receives an
        # achromatic contour to avoid tinting generated hair with a UI color.
        request=project['instruction']
        for source,target in [('紫色引导线','白色引导线'),('紫色曲线','白色曲线'),
                              ('magenta outline','white outline'),('magenta curves','white curves')]:
            request=request.replace(source,target)
        wf=fig.build_qwen_figure_edit_wf(names['canvas'],instruction+request,seed,prefix,references)
        # Already sized to a multiple of 16: avoid a second auto-scaling operation.
        wf['scale']={'class_type':'ImageScale','inputs':dict(image=['load',0],upscale_method='lanczos',
            width=names['width'],height=names['height'],crop='disabled')}
        # Generic latent masking anchors the existing composition. Qwen Edit is
        # still instruction-driven, not a dedicated inpaint checkpoint.
        wf['mask_load']={'class_type':'LoadImageMask','inputs':dict(image=names['mask'],channel='red')}
        wf['masked_latent']={'class_type':'SetLatentNoiseMask','inputs':dict(samples=['latent',0],mask=['mask_load',0])}
        wf['sample']['inputs'].update(latent_image=['masked_latent',0],steps=project['steps'])
    else:
        prompt=('score_9, score_8_up, score_7_up, source_anime, Japanese anime illustration, '
            'coherent anatomy, consistent linework, matching colors and cel shading, '+project['instruction'])
        negative='text, watermark, sketch marks, colored joint dots, extra limbs, duplicate limbs, malformed hands, photorealistic'
        wf=fig.build_img2img_wf('pony',prompt,negative,seed,names['width'],names['height'],project['steps'],1.0,names['canvas'])
        wf['mask_load']={'class_type':'LoadImageMask','inputs':dict(image=names['mask'],channel='red')}
        wf['5a']={'class_type':'VAEEncodeForInpaint','inputs':dict(pixels=['5',0],vae=['4',2],mask=['mask_load',0],grow_mask_by=0)}
        wf['9']['inputs']['filename_prefix']=prefix
        pos,neg=['6',0],['7',0]
        for key,model,strength,enabled in [
            ('pose',POSE_MODEL,project['pose_strength'],bool(project['joints'])),
            ('lines',CANNY_MODEL,project['line_strength'],bool(project['hair']))]:
            if not enabled or not strength: continue
            path=ROOT/'ComfyUI'/'models'/'controlnet'/model
            if not path.is_file(): raise ValueError('缺少控制权重：'+model)
            wf[key+'_image']={'class_type':'LoadImage','inputs':dict(image=names[key])}
            wf[key+'_loader']={'class_type':'ControlNetLoader','inputs':dict(control_net_name=model)}
            wf[key+'_apply']={'class_type':'ControlNetApplyAdvanced','inputs':dict(
                positive=pos,negative=neg,control_net=[key+'_loader',0],image=[key+'_image',0],
                strength=strength,start_percent=0.0,end_percent=0.85)}
            pos,neg=[key+'_apply',0],[key+'_apply',1]
        wf['3']['inputs'].update(positive=pos,negative=neg)
    return wf


def run(project_path):
    import fig
    data=json.loads(Path(project_path).read_text(encoding='utf-8'))
    project,original=validate_project(data)
    digest=hashlib.sha256(Path(project['source']).read_bytes()).hexdigest()
    if data.get('source_sha256') and data['source_sha256']!=digest:
        raise ValueError('原图内容已改变，请重新准备工程')
    if not project['instruction']: raise ValueError('请填写补全要求')
    layers=make_layers(project,original)
    fig.ensure_comfyui_running()
    folder=Path(project_path).parent
    size=layers['canvas'].size
    crop=context_crop(layers['mask']) if project['engine']=='qwen' else (0,0,*size)
    crop_size=(crop[2]-crop[0],crop[3]-crop[1])
    working=sampling_size(crop_size,project['engine'],project['megapixels'])
    names={'width':working[0],'height':working[1]}
    for key,im in layers.items():
        if key=='expanded': continue
        target=im.crop(crop).resize(working,Image.Resampling.NEAREST if key=='mask' else Image.Resampling.LANCZOS)
        path=folder/('input_'+key+'.png'); target.save(path)
        names[key]=fig.upload_image(str(path))['name']
    print(f'工程：{project_path}',flush=True)
    print(f'画布 {size[0]}×{size[1]}；采样 {working[0]}×{working[1]}；引擎 {project["engine"]}',flush=True)
    print(f'上下文裁剪框：{crop}',flush=True)
    results=[]
    for index in range(project['candidates']):
        seed=project['seed'] if project['seed']>=0 else secrets.randbelow(2**32)
        seed=(seed+index)%(2**32)
        prefix=fig.unique_prefix('completion_raw')
        wf=build_workflow(project,names,seed,prefix)
        (folder/f'workflow_{index+1}.json').write_text(json.dumps(wf,ensure_ascii=False,indent=2),encoding='utf-8')
        try: response=fig.api_post('/prompt',{'prompt':wf})
        except Exception as exc:
            import urllib.error
            if isinstance(exc,urllib.error.HTTPError):
                raise RuntimeError('工作流校验失败：'+exc.read().decode('utf-8','replace')) from exc
            raise
        pid=response.get('prompt_id')
        if not pid: raise RuntimeError('ComfyUI未返回任务编号：'+str(response))
        print(f'第{index+1}个方案 seed={seed}，任务 {pid}',flush=True)
        files=fig.collect_files(fig.wait_done(pid,2400,'引导补全'))
        files=[(fn,sub) for fn,sub,kind in files if fn.lower().endswith('.png')]
        if not files: raise RuntimeError('生成未返回图片')
        raw=fig.verified_output_path(*files[0])
        generated=layers['canvas'].copy()
        generated.paste(load_source(raw).resize(crop_size,Image.Resampling.LANCZOS),crop[:2])
        result=Image.composite(generated,layers['canvas'],layers['mask'])
        path=OUT/f'completion_{folder.name}_{index+1}.png'; result.save(path)
        # Verify exact protection after writing, not just before serialization.
        protected=np.asarray(layers['mask'])==0
        actual=np.asarray(Image.open(path).convert('RGB'))
        if not np.array_equal(actual[protected],np.asarray(layers['canvas'])[protected]):
            raise RuntimeError('保护区像素校验失败')
        results.append(dict(path=str(path),seed=seed,raw=raw,prompt_id=pid,context_crop=crop))
        print('补全结果：'+str(path),flush=True)
    (folder/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('保护区像素校验通过；原文件未覆盖。',flush=True)
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    a=parser.parse_args()
    raise SystemExit(run(a.project))
