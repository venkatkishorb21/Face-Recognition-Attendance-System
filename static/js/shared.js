// FaceAttend Pro v5 — Shared JS
const api={
  get:url=>fetch(url).then(r=>r.json()),
  post:(url,b)=>fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json()),
  put:(url,b)=>fetch(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(r=>r.json()),
  del:(url,b)=>fetch(url,{method:'DELETE',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined}).then(r=>r.json()),
};
const $=id=>document.getElementById(id);
const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
let _tt;
function toast(msg,type='info'){
  let el=$('toast');
  if(!el){el=document.createElement('div');el.id='toast';document.body.appendChild(el);}
  el.textContent=msg;el.className=`toast t-${type}`;el.style.display='block';
  clearTimeout(_tt);_tt=setTimeout(()=>el.style.display='none',3400);
}
function badge(s){
  const m={Present:'b-present',Absent:'b-absent',Late:'b-late',Pending:'b-pending',
    Approved:'b-approved',Rejected:'b-rejected',Active:'b-active',Inactive:'b-inactive',
    Safe:'b-safe','At Risk':'b-atrisk',Closed:'b-inactive',Extended:'b-extended'};
  const i={Present:'✓',Absent:'✗',Late:'⏱',Pending:'⋯',Approved:'✓',Rejected:'✗',
    Active:'●',Inactive:'○',Safe:'✓','At Risk':'⚠',Closed:'■',Extended:'↑'};
  return `<span class="badge ${m[s]||'b-info'}">${i[s]||'?'} ${esc(s)}</span>`;
}
function pctColor(p){return p>=75?'var(--ok)':p>=50?'var(--wrn)':'var(--err)';}
function prog(pct,color,h=7){
  return `<div class="prog" style="height:${h}px"><div class="prog-bar" style="width:${Math.min(pct,100)}%;background:${color}"></div></div>`;
}
function pctRing(pct,size=80){
  const r=30,c=2*Math.PI*r,color=pctColor(pct),dash=pct/100*c;
  return `<svg width="${size}" height="${size}" viewBox="0 0 80 80">
    <circle cx="40" cy="40" r="${r}" fill="none" stroke="#E8F1FC" stroke-width="10"/>
    <circle cx="40" cy="40" r="${r}" fill="none" stroke="${color}" stroke-width="10"
      stroke-dasharray="${dash} ${c-dash}" stroke-dashoffset="${c/4}" stroke-linecap="round"/>
    <text x="40" y="40" text-anchor="middle" dominant-baseline="middle"
      style="font-size:13px;font-weight:800;fill:${color};font-family:monospace">${pct}%</text>
  </svg>`;
}
function openModal(id){$(id)&&$(id).classList.add('open');}
function closeModal(id){$(id)&&$(id).classList.remove('open');}
function bgClose(e,id){if(e.target===e.currentTarget)closeModal(id);}
function fmtDate(d){try{return new Date(d+'T12:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'});}catch{return d;}}
async function loadNotifBadge(userId){
  try{
    const notifs=await api.get('/api/notifications'+(userId?'?userId='+userId:''));
    const c=notifs.filter(n=>!n.read).length;
    const dot=$('notifDot');
    if(dot){dot.textContent=c;dot.style.display=c?'flex':'none';}
  }catch(e){}
}
async function renderNotifModal(userId){
  try{
    const notifs=await api.get('/api/notifications'+(userId?'?userId='+userId:''));
    const el=$('notifList');
    if(!el)return;
    el.innerHTML=notifs.length?notifs.map(n=>`
      <div class="notif-item ${n.read?'read':'unread'} n${n.type||'info'}">
        <div style="font-size:13px;font-weight:${n.read?400:700}">${esc(n.msg)}</div>
        <div style="font-size:10px;color:var(--mut);margin-top:3px">${n.createdAt||''}</div>
      </div>`).join(''):'<div class="empty"><div class="empty-icon">🔔</div><p>No notifications</p></div>';
  }catch(e){}
}
function drawTrend(canvasId,labelId,trend){
  const cv=$(canvasId);if(!cv)return;
  const w=cv.offsetWidth||300;cv.width=w;cv.height=100;
  const ctx=cv.getContext('2d');ctx.clearRect(0,0,w,100);
  const max=Math.max(...trend.map(t=>(t.present||0)+(t.absent||0)),1);
  const bw=Math.floor(w/trend.length)-4;
  trend.forEach((t,i)=>{
    const x=i*(bw+4)+2,ph=Math.round(((t.present||0)/max)*85),ah=Math.round(((t.absent||0)/max)*85);
    ctx.fillStyle='#E0305540';if(ctx.roundRect)ctx.roundRect(x,100-ph-ah,bw,ah,2);else ctx.fillRect(x,100-ph-ah,bw,ah);ctx.fill();
    ctx.fillStyle='#0A9E6E99';if(ctx.roundRect)ctx.roundRect(x,100-ph,bw,ph,2);else ctx.fillRect(x,100-ph,bw,ph);ctx.fill();
  });
  const lbl=$(labelId);
  if(lbl)lbl.innerHTML=trend.map(t=>{const d=new Date(t.date+'T12:00:00');return `<span style="font-size:9px;color:var(--mut)">${d.toLocaleDateString('en-IN',{weekday:'narrow'})}</span>`;}).join('');
}
// Countdown timer renderer
function renderCountdown(remainingMinutes){
  if(remainingMinutes===null||remainingMinutes===undefined)return'—';
  const cls=remainingMinutes<=5?'danger':remainingMinutes<=15?'warn':'';
  return `<span class="countdown ${cls}">${remainingMinutes} min left</span>`;
}
