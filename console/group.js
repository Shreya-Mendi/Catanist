/* group.js: the hypothesis page (/group/<id>). Members, spend against caps,
   combined metrics, files rendered inline, notes, activity, upload. */
(async function(){
  const root=document.getElementById("g"), gid=root.dataset.gid;
  const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;");
  const api=async(p,b)=>{const r=await fetch(p,b?{method:"POST",credentials:"same-origin",body:JSON.stringify(b)}:{credentials:"same-origin"}); if(r.status===401){root.innerHTML="<p>Log in on the console first, then reload this page.</p>"; throw new Error("login");} return r.json();};
  const g=await api("/api/group/"+gid);
  if(g.err){ root.innerHTML="<p>"+esc(g.err)+"</p>"; return; }
  const money=x=>x==null?"—":"$"+(+x).toFixed(2);
  const cap=(spent,c)=>c?`${money(spent)} of ${money(c)} cap${spent>c?' <span class="err">over</span>':''}`:money(spent);
  const members=g.members.map(m=>`<tr><td>#${m.id}</td><td>${esc(m.name)}</td><td>${esc(m.owner)}</td><td>${m.done}/${m.total}</td><td>${g.spend?money(m.spend_usd):""}</td>
    <td><a href="/api/metrics/${m.id}" target="_blank">metrics</a> · <a href="/api/export-statements?experiment=${m.id}">statements csv</a></td></tr>`).join("");
  const metricRows=[];
  for(const m of g.members){ const mm=g.metrics[String(m.id)]||{};
    for(const [cond,cls] of Object.entries(mm)) for(const [seatcls,v] of Object.entries(cls)){
      const p=v.pooled||{}; metricRows.push(`<tr><td>#${m.id}</td><td>${esc(cond)}</td><td>${esc(seatcls)}</td><td>${p.viol??"—"} <span class="small">(${p.n?.viol||""})</span></td><td>${p.false??"—"} <span class="small">(${p.n?.false||""})</span></td><td>${p.break??"—"}</td><td>${p.info??"—"}</td><td>${v.trades?v.trades.mean:"—"}</td><td>${p.seats||0}${p.thin_seats?` <span class="small">(${p.thin_seats} thin)</span>`:""}</td></tr>`);
    }}
  const files=await Promise.all(g.files.map(async f=>{
    const url=`/groups/${gid}/${encodeURIComponent(f.name)}`;
    let body="";
    if(/\.md$/i.test(f.name)){ const t=await (await fetch(url,{credentials:"same-origin"})).text(); body=renderMarkdown(t); }
    else if(/\.(png|jpe?g|gif|svg|webp)$/i.test(f.name)) body=`<img src="${url}" style="max-width:100%">`;
    else if(/\.(json|csv|txt)$/i.test(f.name)&&f.size<200000){ const t=await (await fetch(url,{credentials:"same-origin"})).text(); body=`<pre class="mono" style="max-height:320px;overflow:auto">${esc(t.slice(0,20000))}</pre>`; }
    return `<details class="file" ${/\.md$/i.test(f.name)?"open":""}><summary>${esc(f.name)} <span class="small">· ${(f.size/1024).toFixed(0)} KB · ${esc(f.uploader||"")} · <a href="${url}" target="_blank">open</a></span></summary>${body}</details>`;
  }));
  const notes=(g.notes||[]).map(n=>`<div class="note"><b>${esc(n.author)}</b> <span class="small">${new Date(n.created*1000).toLocaleDateString()}</span><div>${esc(n.text)}</div></div>`).join("")||"<p class='small'>no notes yet</p>";
  const act=(g.activity||[]).map(a=>`<div class="small">${new Date(a.created*1000).toLocaleString()} · ${esc(a.who)} · ${esc(a.what)} · ${esc(a.detail)}</div>`).join("");
  root.innerHTML=`<header class="slim"><a href="/" class="ghost">← console</a><h1>${esc(g.name)}</h1><span class="badge dim">${esc(g.kind)}</span></header>
  <div class="card"><p>${esc(g.description||"")}</p>
    <p class="kv">${g.spend?`OpenAI ${cap(g.spend.openai,g.cap_openai)} · Tinker ${cap(g.spend.tinker,g.cap_tinker)} · ${g.spend.games_done} finished games · `:""}<a href="/api/export-statements?group=${gid}">statements csv for the whole group</a></p></div>
  <div class="card"><h2>Experiments</h2><table><tr><th>id</th><th>name</th><th>owner</th><th>done</th><th>spend</th><th></th></tr>${members||"<tr><td colspan=6 class='small'>none yet</td></tr>"}</table></div>
  <div class="card"><h2>Pooled battery per condition</h2><p class="lede">violations / checkable, false claims / claims, promise+plan breaks, informativeness, trades proposed (seat mean); raw metrics, no overlay.</p>
    <table><tr><th>exp</th><th>condition</th><th>seats</th><th>viol</th><th>false</th><th>break</th><th>info</th><th>trades</th><th>n seats</th></tr>${metricRows.join("")||"<tr><td colspan=9 class='small'>no finished games</td></tr>"}</table></div>
  <div class="card"><h2>Files</h2><p class="lede">write-ups, tables, figures, notes. Markdown and images render inline.</p>${files.join("")||"<p class='small'>nothing attached yet</p>"}
    <div class="row" style="margin-top:10px"><input type="file" id="up" multiple><button class="ghost" id="upbtn">upload</button><span class="small" id="upmsg"></span></div></div>
  <div class="card"><h2>Notes</h2>${notes}<div class="row" style="margin-top:8px"><input id="note" placeholder="add a note" style="flex:1"><button class="ghost" id="notebtn">add</button></div></div>
  <div class="card"><h2>Activity</h2>${act||"<p class='small'>nothing yet</p>"}</div>`;
  document.getElementById("upbtn").onclick=async()=>{
    const files=[...document.getElementById("up").files]; const msg=document.getElementById("upmsg");
    for(const f of files){ const b64=await new Promise(res=>{const r=new FileReader(); r.onload=()=>res(r.result.split(",")[1]); r.readAsDataURL(f);});
      const j=await api("/api/group/file",{group_id:+gid,name:f.name,data_b64:b64}); msg.textContent=j.err?("failed: "+j.err):("uploaded "+j.name); }
    if(files.length) setTimeout(()=>location.reload(),600);
  };
  document.getElementById("notebtn").onclick=async()=>{ const t=document.getElementById("note").value.trim(); if(!t) return; await api("/api/group/note",{group_id:+gid,text:t}); location.reload(); };
})();
