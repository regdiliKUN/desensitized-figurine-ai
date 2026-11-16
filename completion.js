'use strict';
(()=>{
const root=document.getElementById('completion-inline');
if(!root)return;
const $=id=>id==='instruction'?document.getElementById('edit-request'):
  id==='candidates'?document.getElementById('edit-candidates'):root.querySelector('#ce-'+id);
const API=location.pathname.replace(/\/$/,'');
const KEYS=['nose','neck','right_shoulder','right_elbow','right_wrist','left_shoulder','left_elbow','left_wrist','right_hip','right_knee','right_ankle','left_hip','left_knee','left_ankle','right_eye','left_eye','right_ear','left_ear'];
const LABELS=['鼻','颈','右肩','右肘','右腕','左肩','左肘','左腕','右髋','右膝','右踝','左髋','左膝','左踝','右眼','左眼','右耳','左耳'];
const BONES=[[1,2],[1,5],[2,3],[3,4],[5,6],[6,7],[1,8],[8,9],[9,10],[1,11],[11,12],[12,13],[1,0],[0,14],[14,16],[0,15],[15,17]];
const COLORS=['#ff0000','#ff5500','#ffaa00','#ffff00','#aaff00','#55ff00','#00ff00','#00ff55','#00ffaa','#00ffff','#00aaff','#0055ff','#0000ff','#5500ff','#aa00ff','#ff00ff','#ff00aa','#ff0055'];
let p={version:1,source:'',source_size:[800,500],padding:{left:0,right:0,top:0,bottom:0},joints:{},locked:[],strokes:[],hair:[]};
let image=null,tool='joint',scale=1,history=[],future=[],gesture=null,resizeGesture=null,jobId=null,polling=false,cap={};
const canvas=$('canvas'),ctx=canvas.getContext('2d');
const clone=x=>JSON.parse(JSON.stringify(x));
const say=s=>{$('status').textContent=s;};
async function api(path,data){
  const response=await fetch(API+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result;
}
async function action(fn){try{await fn();}catch(e){say(e.message);}}
for(let i=0;i<KEYS.length;i++){
  const key=KEYS[i],o=document.createElement('option');o.value=key;o.textContent=LABELS[i];$('joint').append(o);
  const row=document.createElement('div');row.className='ce-joint-row';
  const pick=document.createElement('button');pick.type='button';pick.className='ce-joint-select';pick.dataset.joint=key;pick.style.setProperty('--joint-color',COLORS[i]);pick.setAttribute('aria-label','选择'+LABELS[i]+'定位点');
  const dot=document.createElement('span');dot.className='ce-joint-dot';dot.setAttribute('aria-hidden','true');pick.append(dot,document.createTextNode(LABELS[i]));
  pick.onclick=()=>{$('joint').value=key;activateTool('joint');render();say('已选择'+LABELS[i]+'：到图片上点击定位；再点已放置的圆点可取消。');};
  const remove=document.createElement('button');remove.type='button';remove.className='ce-joint-remove';remove.dataset.removeJoint=key;remove.textContent='×';remove.title='取消'+LABELS[i]+'定位';remove.setAttribute('aria-label','取消'+LABELS[i]+'定位');remove.onclick=()=>removeJoint(key);
  row.append(pick,remove);$('joint-list').append(row);
}
function activateTool(next){tool=next;root.querySelectorAll('[data-tool]').forEach(x=>x.classList.toggle('active',x.dataset.tool===tool));updateCursor();}
function updateCursor(){
  if(tool!=='joint'){canvas.style.cursor='crosshair';return;}
  const color=COLORS[KEYS.indexOf($('joint').value)];
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26"><circle cx="13" cy="13" r="8" fill="none" stroke="white" stroke-width="4"/><circle cx="13" cy="13" r="8" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
  canvas.style.cursor=`url("data:image/svg+xml,${encodeURIComponent(svg)}") 13 13, crosshair`;
}
function removeJoint(key){
  if(!p.joints[key])return;remember();delete p.joints[key];p.locked=p.locked.filter(k=>k!==key);$('joint').value=key;activateTool('joint');changed();
  say('已取消'+LABELS[KEYS.indexOf(key)]+'定位；点击图片其他位置可重新放置。');
}
function settings(){
  Object.assign(p,{instruction:$('instruction').value.trim(),engine:$('engine').value,overlap:Number($('overlap').value),feather:Number($('feather').value),seed:Number($('seed').value),steps:Number($('steps').value),candidates:Number($('candidates').value),megapixels:Number($('megapixels').value),pose_strength:Number($('pose-strength').value),line_strength:Number($('line-strength').value)});
  return p;
}
function sync(){
  $('source-path').value=p.source;
  $('source-label').textContent=p.source||'尚未选择图片';
  for(const k of ['left','right','top','bottom'])$('pad-'+k).value=p.padding[k];
  for(const [id,key,def] of [['instruction','instruction',''],['engine','engine','qwen'],['overlap','overlap',0],['feather','feather',4],['seed','seed',-1],['steps','steps',20],['candidates','candidates',1],['megapixels','megapixels',1],['pose-strength','pose_strength',.8],['line-strength','line_strength',.55]])$(id).value=p[key]??def;
  engineHelp();render();
}
function remember(){settings();history.push(clone(p));if(history.length>80)history.shift();future=[];}
function changed(){render();try{localStorage.setItem('figurine-completion-draft',JSON.stringify(settings()));}catch{} }
function undo(){if(!history.length)return;future.push(clone(settings()));p=history.pop();gesture=null;sync();}
function redo(){if(!future.length)return;history.push(clone(settings()));p=future.pop();gesture=null;sync();}
function dims(){return [p.source_size[0]+p.padding.left+p.padding.right,p.source_size[1]+p.padding.top+p.padding.bottom];}
function toScreen(point){return [(point[0]+p.padding.left)*scale,(point[1]+p.padding.top)*scale];}
function eventPoint(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)/scale-p.padding.left,(e.clientY-r.top)/scale-p.padding.top];}
function within(point){const [w,h]=p.source_size;return point[0]>=-p.padding.left&&point[0]<=w+p.padding.right&&point[1]>=-p.padding.top&&point[1]<=h+p.padding.bottom;}
function bound(point){const [w,h]=p.source_size;return [Math.max(-p.padding.left,Math.min(w+p.padding.right,point[0])),Math.max(-p.padding.top,Math.min(h+p.padding.bottom,point[1]))];}
function path(c,row,color){
  c.strokeStyle=color;c.fillStyle=color;c.lineWidth=Math.max(1,row.width*scale);c.lineCap='round';c.lineJoin='round';c.beginPath();
  const pts=row.points.map(toScreen);c.moveTo(...pts[0]);for(const point of pts.slice(1))c.lineTo(...point);c.stroke();
  if(pts.length===1){c.beginPath();c.arc(...pts[0],Math.max(.5,row.width*scale/2),0,Math.PI*2);c.fill();}
}
function render(){
  const [w,h]=dims(),zoom=$('zoom').value;
  scale=resizeGesture?resizeGesture.scale:zoom==='fit'?Math.min(1,Math.max(80,$('stage').clientWidth-50)/w,1000/h):Number(zoom);
  // Display buffer may be smaller than original; data always stays in native pixels.
  scale=Math.min(scale,4096/w,4096/h);
  canvas.width=Math.max(1,Math.round(w*scale));canvas.height=Math.max(1,Math.round(h*scale));
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(image)ctx.drawImage(image,p.padding.left*scale,p.padding.top*scale,p.source_size[0]*scale,p.source_size[1]*scale);
  if($('show-mask').checked&&image){
    const mask=document.createElement('canvas');mask.width=canvas.width;mask.height=canvas.height;const m=mask.getContext('2d');
    const [sw,sh]=p.source_size,l=p.padding.left*scale,t=p.padding.top*scale;
    m.clearRect(l,t,sw*scale,sh*scale);
    const band=Number($('overlap').value)*scale;
    // Preview the editable support; the backend applies the smooth transition.
    m.fillStyle='#67a5ff';
    if(p.padding.left)m.fillRect(l,t,Math.min(band,sw*scale),sh*scale);
    if(p.padding.right)m.fillRect(l+Math.max(0,sw*scale-band),t,Math.min(band,sw*scale),sh*scale);
    if(p.padding.top)m.fillRect(l,t,sw*scale,Math.min(band,sh*scale));
    if(p.padding.bottom)m.fillRect(l,t+Math.max(0,sh*scale-band),sw*scale,Math.min(band,sh*scale));
    for(const stroke of p.strokes){m.globalCompositeOperation=stroke.action==='erase'?'destination-out':'source-over';path(m,stroke,'#67a5ff');}
    ctx.globalAlpha=.32;ctx.drawImage(mask,0,0);ctx.globalAlpha=1;
  }
  if(image){ctx.strokeStyle='#e9edff';ctx.lineWidth=1;ctx.setLineDash([6,5]);ctx.strokeRect(p.padding.left*scale,p.padding.top*scale,p.source_size[0]*scale,p.source_size[1]*scale);ctx.setLineDash([]);}
  if($('show-hair').checked)for(const row of p.hair)path(ctx,row,'#ff50dc');
  if($('show-pose').checked){
    BONES.forEach(([a,b],i)=>{if(p.joints[KEYS[a]]&&p.joints[KEYS[b]]){ctx.strokeStyle=COLORS[i];ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(...toScreen(p.joints[KEYS[a]]));ctx.lineTo(...toScreen(p.joints[KEYS[b]]));ctx.stroke();}});
    for(const [key,point]of Object.entries(p.joints)){
      const i=KEYS.indexOf(key);if(i<0)continue;const [x,y]=toScreen(point);ctx.beginPath();ctx.arc(x,y,key===$('joint').value?7:5,0,Math.PI*2);ctx.fillStyle=COLORS[i];ctx.fill();
      ctx.strokeStyle=p.locked.includes(key)?'#ffdc62':'white';ctx.lineWidth=p.locked.includes(key)?3:1;ctx.stroke();ctx.font='12px Microsoft YaHei';ctx.strokeStyle='#111';ctx.lineWidth=3;ctx.strokeText(LABELS[i]+(p.locked.includes(key)?' 🔒':''),x+9,y-6);ctx.fillStyle='white';ctx.fillText(LABELS[i]+(p.locked.includes(key)?' 🔒':''),x+9,y-6);
    }
  }
  const key=$('joint').value,pt=p.joints[key];$('joint-info').textContent=pt?`${LABELS[KEYS.indexOf(key)]}：${pt.map(Math.round).join(', ')}${p.locked.includes(key)?'（已锁定）':''}`:'当前关节尚未放置';
  root.querySelectorAll('[data-joint]').forEach(button=>{const k=button.dataset.joint,placed=!!p.joints[k];button.classList.toggle('active',k===key);button.classList.toggle('placed',placed);button.setAttribute('aria-pressed',String(k===key));button.title=LABELS[KEYS.indexOf(k)]+(placed?'：已定位，点击左图圆点或旁边×取消':'：尚未定位');});
  root.querySelectorAll('[data-remove-joint]').forEach(button=>button.disabled=!p.joints[button.dataset.removeJoint]);
  for(const k of ['left','right','top','bottom'])$('pad-'+k).value=p.padding[k];
  updateCursor();
  $('dimensions').textContent=`原图 ${p.source_size.join(' × ')} → 画布 ${w} × ${h}；预览 ${Math.round(scale*100)}%`;
  $('undo').disabled=!history.length;$('redo').disabled=!future.length;
}
async function openSource(source,project=null){
  const result=await api('/api/completion_preview',{path:source,source_sha256:project?.source_sha256});
  if(project?.source_size&&JSON.stringify(project.source_size)!==JSON.stringify(result.source_size))throw new Error('原图尺寸已改变，不能直接复用标注');
  const im=new Image();await new Promise((resolve,reject)=>{im.onload=resolve;im.onerror=()=>reject(new Error('预览载入失败'));im.src=result.image;});
  p=project||{version:1,source,source_size:result.source_size,padding:{left:0,right:0,top:0,bottom:0},joints:{},locked:[],strokes:[],hair:[],instruction:$('instruction').value,candidates:Number($('candidates').value)};
  p.source=source;p.source_size=result.source_size;if(result.source_sha256)p.source_sha256=result.source_sha256;p.locked??=[];image=im;history=[];future=[];gesture=null;sync();say('已载入。先扩展画布或涂修改区，再按需添加骨架和引导线。');
  document.dispatchEvent(new CustomEvent('completion-source-changed',{detail:{path:source}}));
}
async function pick(){const result=await api('/api/pick',{kind:'image'});if(result.path)await openSource(result.path);}
function validateClient(){
  if(!image)throw new Error('请先载入图片');
  const all=[...Object.values(p.joints),...p.strokes.flatMap(s=>s.points),...p.hair.flatMap(s=>s.points)];
  if(all.some(point=>!within(point)))throw new Error('有标注位于画布外，请扩大画布或删除对应标注');
  if(!Object.values(p.padding).some(Boolean)&&!p.strokes.some(s=>s.action==='paint'))throw new Error('请扩展画布或涂抹修改区；打点和引导线不等于修改区');
  return settings();
}
function engineHelp(){
  $('megapixels').disabled=$('engine').value==='qwen';
  $('engine-help').textContent=$('engine').value==='qwen'?'Qwen：参考原图与独立控制图；约100万像素采样以匹配参考编码，姿态属于语义参考，不能保证逐点服从。':'SDXL：骨架接入 OpenPose ControlNet，紫色轮廓线接入 Canny 控制；颜色和画风仍需检查。建议使用英文描述。';
}
root.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>activateTool(b.dataset.tool));
canvas.addEventListener('pointerdown',e=>{
  if(!image||e.button!==0)return;e.preventDefault();canvas.focus({preventScroll:true});const point=bound(eventPoint(e));
  if(tool==='joint'){
    const active=$('joint').value;
    const hits=Object.entries(p.joints).map(([k,v])=>[k,Math.hypot((v[0]-point[0])*scale,(v[1]-point[1])*scale)]).filter(x=>x[1]<11).sort((a,b)=>a[1]-b[1]);
    const selected=hits.find(x=>x[0]===active),hit=selected||hits[0];
    if(hit){removeJoint(hit[0]);return;}
    remember();p.joints[active]=point;changed();say('已固定'+LABELS[KEYS.indexOf(active)]+'；再次点击圆点可取消。');return;
  }
  remember();canvas.setPointerCapture(e.pointerId);
  if(tool==='hair-erase'){
    const threshold=Number($('brush').value)/2;
    // Distance to segments, so long sparse strokes can also be erased midway.
    const distance=(a,b,q)=>{const dx=b[0]-a[0],dy=b[1]-a[1],d=dx*dx+dy*dy,t=d?Math.max(0,Math.min(1,((q[0]-a[0])*dx+(q[1]-a[1])*dy)/d)):0;return Math.hypot(q[0]-a[0]-t*dx,q[1]-a[1]-t*dy);};
    p.hair=p.hair.filter(row=>!row.points.some((pt,i)=>distance(pt,row.points[Math.min(i+1,row.points.length-1)],point)<=threshold+row.width/2));
  }else{
    const row={width:Number($('brush').value),points:[point],action:tool==='erase'?'erase':'paint'};
    const rows=tool==='hair'?p.hair:p.strokes;rows.push(row);gesture={kind:'stroke',row};
  }changed();
});
canvas.addEventListener('pointermove',e=>{
  const point=bound(eventPoint(e));$('cursor').textContent='原图坐标：'+point.map(Math.round).join(', ');
  if(!gesture)return;
  const pts=gesture.row.points,last=pts[pts.length-1];if(Math.hypot(point[0]-last[0],point[1]-last[1])*scale>=2)pts.push(point);
  render();
});
function endGesture(){if(gesture){gesture=null;changed();}}
canvas.addEventListener('pointerup',endGesture);canvas.addEventListener('pointercancel',endGesture);canvas.addEventListener('lostpointercapture',endGesture);
root.querySelectorAll('[data-edge]').forEach(handle=>{
  handle.addEventListener('pointerdown',e=>{
    if(!image||e.button!==0)return;e.preventDefault();e.stopPropagation();
    remember();resizeGesture={edge:handle.dataset.edge,x:e.clientX,y:e.clientY,scale,padding:clone(p.padding),pointer:e.pointerId};
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove',e=>{
    if(!resizeGesture||resizeGesture.pointer!==e.pointerId)return;
    const g=resizeGesture,dx=(e.clientX-g.x)/g.scale,dy=(e.clientY-g.y)/g.scale,next=clone(g.padding);
    if(g.edge.includes('w'))next.left=Math.max(0,Math.min(4096,Math.round(g.padding.left-dx)));
    if(g.edge.includes('e'))next.right=Math.max(0,Math.min(4096,Math.round(g.padding.right+dx)));
    if(g.edge.includes('n'))next.top=Math.max(0,Math.min(4096,Math.round(g.padding.top-dy)));
    if(g.edge.includes('s'))next.bottom=Math.max(0,Math.min(4096,Math.round(g.padding.bottom+dy)));
    const w=p.source_size[0]+next.left+next.right,h=p.source_size[1]+next.top+next.bottom;
    if(Math.max(w,h)>8192||w*h>40000000){say('已达到画布大小上限。');return;}
    const points=[...Object.values(p.joints),...p.strokes.flatMap(s=>s.points),...p.hair.flatMap(s=>s.points)];
    if(points.some(pt=>pt[0]<-next.left||pt[0]>p.source_size[0]+next.right||pt[1]<-next.top||pt[1]>p.source_size[1]+next.bottom)){
      say('缩小后会移除已有标注区域，请先取消对应点位或笔画。');return;
    }
    p.padding=next;render();
    $('frame').style.transform=`translate(${-(next.left-g.padding.left)*g.scale}px,${-(next.top-g.padding.top)*g.scale}px)`;
  });
  const finish=e=>{
    if(!resizeGesture||resizeGesture.pointer!==e.pointerId)return;
    if(e.type==='pointercancel'){p.padding=resizeGesture.padding;history.pop();}
    resizeGesture=null;$('frame').style.transform='';changed();say('画布边框已调整。棋盘格是透明像素，点击“补全画面”即可自动填充。');
  };
  handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
});
$('export-canvas').onclick=()=>action(async()=>{
  const result=await api('/api/completion_save',{project:validateClient()});
  const a=document.createElement('a');a.href=API+'/api/completion_image?path='+encodeURIComponent(result.expanded_path)+'&download=1';a.click();
  $('save-path').textContent=result.path;say('已导出透明画布 PNG；新增区域为真实透明像素，不包含骨架或引导线。');
});
$('pick').onclick=()=>action(pick);$('load-path').onclick=()=>action(()=>openSource($('source-path').value.trim().replace(/^"|"$/g,'')));
$('apply-padding').onclick=()=>action(()=>{
  if(!image)throw new Error('请先选择图片');const next={};for(const k of ['left','right','top','bottom']){const v=Number($('pad-'+k).value);if(!Number.isInteger(v)||v<0||v>4096)throw new Error('边距必须是0～4096的整数');next[k]=v;}
  const w=p.source_size[0]+next.left+next.right,h=p.source_size[1]+next.top+next.bottom;if(Math.max(w,h)>8192||w*h>40000000)throw new Error('画布超过8192边长或4000万像素');remember();p.padding=next;changed();
});
$('joint').onchange=()=>{activateTool('joint');render();};$('lock-joint').onclick=()=>{};
$('delete-joint').onclick=()=>removeJoint($('joint').value);
$('template').onclick=()=>{
  if(!image)return;remember();const [w,h]=p.source_size;
  const points=[[.5,.13],[.5,.25],[.38,.27],[.32,.43],[.29,.57],[.62,.27],[.68,.43],[.71,.57],[.43,.53],[.42,.72],[.41,.93],[.57,.53],[.58,.72],[.59,.93],[.47,.12],[.53,.12],[.44,.14],[.56,.14]];
  points.forEach((pt,i)=>{if(!p.joints[KEYS[i]])p.joints[KEYS[i]]=[pt[0]*w,pt[1]*h];});changed();say('已放入站姿模板。请手动调整至目标姿态；模板不是识图结果。');
};
$('undo').onclick=undo;$('redo').onclick=redo;
$('clear-layer').onclick=()=>{remember();if(tool==='joint'){p.joints=Object.fromEntries(Object.entries(p.joints).filter(([k])=>p.locked.includes(k)));}else if(tool.startsWith('hair'))p.hair=[];else p.strokes=[];changed();};
for(const id of ['show-mask','show-pose','show-hair','zoom','overlap'])$(id).onchange=render;
$('brush').oninput=()=>{$('brush-value').textContent=$('brush').value;};$('engine').onchange=engineHelp;
document.addEventListener('keydown',e=>{if(!root.contains(e.target)||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?redo():undo();}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();redo();}});
window.addEventListener('resize',render);
$('export').onclick=()=>action(()=>{if(!image)throw new Error('请先选择图片');const blob=new Blob([JSON.stringify(settings(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='插画补全工程.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);say('工程已导出；原图使用路径引用，请保留原图。');});
$('load').onclick=()=>$('project-file').click();
$('project-file').onchange=()=>action(async()=>{
  const f=$('project-file').files[0];if(!f)return;
  try{
    if(f.size>8*1024*1024)throw new Error('工程文件过大');const next=JSON.parse(await f.text());
    if(next.version!==1||typeof next.source!=='string'||!Array.isArray(next.source_size)||!next.padding||!next.joints||!Array.isArray(next.strokes)||!Array.isArray(next.hair))throw new Error('补全工程格式不正确');
    const nums=[...next.source_size,...Object.values(next.padding)];if(nums.some(x=>!Number.isFinite(x)))throw new Error('工程尺寸格式错误');
    const [w,h]=[next.source_size[0]+next.padding.left+next.padding.right,next.source_size[1]+next.padding.top+next.padding.bottom];
    if(w<=0||h<=0||Math.max(w,h)>8192||w*h>40000000)throw new Error('工程画布尺寸超出范围');
    if(Object.keys(next.joints).some(k=>!KEYS.includes(k)))throw new Error('工程含未知关节');
    for(const point of [...Object.values(next.joints),...next.strokes.flatMap(s=>s.points),...next.hair.flatMap(s=>s.points)])if(!Array.isArray(point)||point.length!==2||point.some(v=>!Number.isFinite(v)))throw new Error('工程标注格式错误');
    const validated=await api('/api/completion_validate',{project:next});
    await openSource(validated.project.source,validated.project);
  }finally{$('project-file').value='';}
});
$('save').onclick=()=>action(async()=>{const result=await api('/api/completion_save',{project:validateClient()});$('save-path').textContent=result.path;say('已保存工程、遮罩和引导图。可在 ComfyUI/output/completion_projects 中找到。');});
$('generate').onclick=()=>action(async()=>{
  const project=validateClient();if(!project.instruction)throw new Error('请填写补全要求');
  if(project.engine==='sdxl'&&Object.keys(project.joints).length&&!cap.pose)throw new Error('OpenPose模型未安装，暂不能运行SDXL骨架控制');
  $('generate').disabled=true;
  try{const result=await api('/api/run',{mode:'complete_image',project});jobId=result.job_id;sessionStorage.setItem('completion-job-id',jobId);$('results').replaceChildren();say('任务已提交。生成期间可以查看日志。');await poll();}
  catch(e){$('generate').disabled=false;throw e;}
});
async function showResult(path){
  if([...$('results').children].some(x=>x.dataset.path===path))return;
  const box=document.createElement('div');box.className='result';box.dataset.path=path;
  const im=document.createElement('img');im.alt='补全结果';const text=document.createElement('p');text.textContent=path;
  const use=document.createElement('button');use.textContent='作为下一轮原图';use.onclick=()=>action(()=>openSource(path));
  const full=API+'/api/completion_image?path='+encodeURIComponent(path);
  const download=document.createElement('a');download.textContent='下载原尺寸 PNG';download.href=full+'&download=1';download.style.cssText='display:block;color:#c5baff;margin-top:6px';
  box.append(im,text,use,download);$('results').append(box);
  const result=await api('/api/edit_preview',{path});im.src=result.image;
  im.onclick=()=>{$('dialog-image').src=full;$('preview-dialog').showModal();};
}
async function poll(){
  if(polling)return;polling=true;
  try{
    if(!jobId)return;const state=await api('/api/status');
    if(state.job_id!==jobId){$('generate').disabled=false;say('当前控制中心任务已改变；历史结果请在输出目录查看。');jobId=null;sessionStorage.removeItem('completion-job-id');return;}
    $('log').textContent=state.output||'等待生成引擎……';$('log').scrollTop=$('log').scrollHeight;
    for(const line of (state.output||'').split(/\r?\n/)){const match=/^补全结果[：:]\s*(.+)$/.exec(line.trim());if(match)await showResult(match[1]);}
    if(state.running){say('正在生成；完成后会显示结果和像素保护校验。');setTimeout(poll,2500);}
    else{$('generate').disabled=false;say(state.exit_code===0?'补全完成，保护区像素校验通过。请检查新生成部分的结构和接缝。':'生成失败，请查看运行日志。工程与标注已保留。');jobId=null;sessionStorage.removeItem('completion-job-id');}
  }catch(e){say('状态读取失败：'+e.message+'；任务可能仍在后台运行。');if(jobId)setTimeout(poll,5000);}
  finally{polling=false;}
}
$('close-dialog').onclick=()=>$('preview-dialog').close();
action(async()=>{cap=await api('/api/completion_capabilities');$('capabilities').textContent=`Qwen：${cap.qwen?'已安装':'未安装'}；OpenPose：${cap.pose?'已安装':'未安装'}；Canny：${cap.canny?'已安装':'未安装'}`;jobId=sessionStorage.getItem('completion-job-id');if(jobId){$('generate').disabled=true;await poll();}});
engineHelp();render();
canvas.tabIndex=0;
const details=document.getElementById('edit-completion');
async function useOriginalSelection(){
  if(typeof editImage!=='undefined'&&editImage&&editImage!==p.source)await openSource(editImage);
}
details.addEventListener('toggle',()=>{if(details.open)action(async()=>{await useOriginalSelection();render();});});
window.CompletionEditor={
  setSource:source=>source===p.source?Promise.resolve():openSource(source),
  refresh:render,
  getState:()=>clone(settings()),
  showResult,
};
if(location.hash==='#edit-completion'){
  details.open=true;
  requestAnimationFrame(()=>details.scrollIntoView({block:'start'}));
}
})();
