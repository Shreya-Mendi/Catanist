"""Local launcher for the Catan Arena — the interactive hub.

    python run.py serve         # then open http://localhost:8756

One page to (a) **replay any previous match** and (b) **start a new one** with a
custom cast: pick each seat's model, persona and personality/intent, hit Start,
and watch the illustrated replay when it finishes. Games run server-side (so real
GitHub Models work as long as the server's environment has the token — via the
shell or Catanist/.env), in a background thread with a live status poll.

Standard-library only; no web framework.
"""
from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from arena.intents import INTENTS
from arena.runner import LOG_DIR, load_env, run_one, save_result
from viz.gallery import build_gallery
from viz.scene import render as render_scene

ROOT = Path(__file__).resolve().parent
COSTUMES = ["wizard", "knight", "vampire", "jester", "queen", "monk",
            "ranger", "bard", "merchant"]
PALETTE = ["#7c5cff", "#e05c5c", "#b14b8a", "#3d9bf2", "#54c26a", "#f2a03d",
           "#2fae9e", "#d67ab5"]

_FALLBACK_MODELS = ["openai/gpt-4o", "openai/gpt-4o-mini",
                    "meta/llama-3.3-70b-instruct", "deepseek/deepseek-v3-0324",
                    "mistral-ai/mistral-medium-2505", "microsoft/phi-4"]


def catalog() -> list[str]:
    """The live GitHub Models catalogue (assets/models_catalog.json)."""
    p = ROOT / "assets" / "models_catalog.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return _FALLBACK_MODELS


JOBS: dict[str, dict] = {}


def _runs() -> list[dict]:
    out = []
    for jp in sorted(LOG_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime,
                     reverse=True):
        try:
            r = json.loads(jp.read_text())
            if "events" not in r or "setup" not in r:
                continue
            scene = jp.with_name(jp.stem + "_scene.html")
            if not scene.exists():
                render_scene(r, scene)
            out.append({
                "name": r.get("config_name", jp.stem),
                "winner": r.get("winner"), "reason": r.get("reason"),
                "vps": r.get("vps", {}),
                "players": [{"name": p["name"], "model": p.get("model"),
                             "intent": p.get("intent"), "color": p.get("color")}
                            for p in r.get("setup", [])],
                "scene": "/logs/" + scene.name,
                "stem": jp.stem,
            })
        except Exception:
            continue
    return out


def _run_job(job_id: str, cfg: dict):
    try:
        JOBS[job_id]["status"] = "running"
        res = run_one(cfg)
        path = save_result(res)
        scene = render_scene(res, path.with_name(path.stem + "_scene.html"))
        build_gallery()
        JOBS[job_id].update(status="done", scene="/logs/" + scene.name,
                            winner=res["winner"], reason=res["reason"],
                            vps=res["vps"])
    except Exception as e:
        JOBS[job_id].update(status="error", error=f"{type(e).__name__}: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the console quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, _PAGE(), "text/html; charset=utf-8")
        if path == "/api/runs":
            return self._send(200, _runs())
        if path == "/api/catalog":
            return self._send(200, catalog())
        if path.startswith("/api/job/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            return self._send(200, job or {"status": "unknown"})
        if path.startswith("/logs/"):
            return self._serve_file(path)
        return self._send(404, {"error": "not found"})

    def _serve_file(self, path):
        rel = unquote(path[len("/logs/"):])
        target = (LOG_DIR / rel).resolve()
        if LOG_DIR.resolve() not in target.parents or not target.exists():
            return self._send(404, {"error": "not found"})
        ctype = ("text/html; charset=utf-8" if target.suffix == ".html"
                 else "application/json" if target.suffix == ".json"
                 else "application/octet-stream")
        return self._send(200, target.read_bytes(), ctype)

    def do_POST(self):
        if self.path != "/api/run":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            cfg = json.loads(self.rfile.read(n) or "{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad JSON"})
        if not cfg.get("players"):
            return self._send(400, {"error": "need at least one player"})
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"status": "queued"}
        threading.Thread(target=_run_job, args=(job_id, cfg), daemon=True).start()
        return self._send(200, {"job_id": job_id})


def _PAGE() -> str:
    models = catalog()
    return (_HTML
            .replace("__INTENTS__", json.dumps(list(INTENTS)))
            .replace("__COSTUMES__", json.dumps(COSTUMES))
            .replace("__MODELS__", json.dumps(models))
            .replace("__PALETTE__", json.dumps(PALETTE))
            .replace("__MODELS_OPTS__", "".join(f"<option>{m}</option>" for m in models))
            .replace("__INTENT_OPTS__", "".join(f"<option>{i}</option>" for i in INTENTS)))


def serve(port: int = 8756):
    load_env()
    have_token = bool(__import__("os").environ.get("GITHUB_TOKEN")
                      or __import__("os").environ.get("GITHUB_MODELS_TOKEN"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Catan Arena launcher → http://localhost:{port}")
    print("GitHub Models token:", "detected ✅" if have_token
          else "NOT set (real models will error; mock works). "
               "Put GITHUB_TOKEN in Catanist/.env or export it before serving.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Catan Arena — Launcher</title>
<style>
 :root{--ink:#2f3b3a;--line:#34403f;--card:#fffdf9;--edge:#d9cdb5;--accent:#e0a93d;--green:#8a9b5f;--shadow:rgba(20,40,40,.3)}
 *{box-sizing:border-box}
 body{margin:0;background:#f1e7d6;color:var(--ink);
   font:15.5px/1.5 "Chalkboard SE","Comic Sans MS",-apple-system,system-ui,sans-serif;padding:24px;max-width:1180px;margin:auto}
 h1{margin:0 0 2px}.sub{color:#7c8a6a;margin-bottom:18px}
 h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--green);margin:26px 0 12px}
 .card{background:var(--card);border:2.5px solid var(--line);border-radius:18px;padding:16px 18px;
   box-shadow:3px 3px 0 var(--shadow)}
 button{background:#fbf6ea;border:2.5px solid var(--line);color:var(--ink);font-weight:700;
   padding:8px 15px;border-radius:11px;cursor:pointer;font-size:14px;box-shadow:2px 2px 0 var(--shadow);transition:transform .06s,box-shadow .06s}
 button:active{transform:translate(2px,2px);box-shadow:0 0 0 var(--shadow)}
 button.pri{background:var(--accent);color:#fff;border-color:#c9922f;box-shadow:2px 2px 0 var(--shadow)}
 input,select{font:inherit;padding:6px 8px;border:2px solid var(--line);border-radius:9px;background:#fff;color:var(--ink)}
 input[type=color]{padding:2px;width:38px;height:34px}
 label{font-size:12px;color:var(--green);font-weight:700}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
 /* previous runs */
 .run{display:flex;flex-direction:column;gap:8px}
 .run .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
 .run .nm{font-weight:800;font-size:15px}
 .win{background:#fff2cf;color:#b5791f;border-radius:999px;padding:2px 10px;font-weight:800;font-size:12.5px;width:fit-content}
 .cast{font-size:12px;color:#6b5a78}.cast .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;vertical-align:middle}
 a.play{margin-top:2px;text-align:center;background:var(--accent);color:#fff;border:2.5px solid var(--line);border-radius:11px;padding:6px;font-weight:800;text-decoration:none;box-shadow:2px 2px 0 var(--shadow)}
 /* new match form */
 .rowhead,.prow{display:grid;grid-template-columns:1.1fr .7fr 1.6fr 1.4fr 1.3fr 1fr 42px 34px;gap:8px;align-items:center}
 .rowhead{margin-bottom:6px;color:var(--green);font-weight:700;font-size:12px}
 .prow{margin-bottom:8px}
 .prow input,.prow select{width:100%}
 .prow .rm{background:#fff0f0;border-color:#f2caca;box-shadow:0 3px 0 #f2caca;padding:6px 8px}
 .toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:6px 0 14px}
 .toolbar .sp{margin-left:auto}
 .opts{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:10px 0}
 .opts>div{display:flex;flex-direction:column;gap:3px}
 #status{margin-top:12px;font-weight:700}
 .muted{color:#7c8a6a;font-weight:600;font-size:13px}
 .banner{background:#fff7e6;border:2.5px solid var(--line);border-radius:12px;padding:9px 13px;font-size:13px;margin-bottom:14px;box-shadow:2px 2px 0 var(--shadow)}
</style></head><body>
<h1>🏝️ Catan Arena</h1>
<div class="sub">Replay a previous match, or start a new one with your own cast.</div>
<div class="banner" id="tokline">Real models use <b>GitHub Models</b> — the server needs <code>GITHUB_TOKEN</code> (models:read) in its env or <code>Catanist/.env</code>. Seats set to <b>mock</b> need no key.</div>

<h2>▶ Start a new match</h2>
<div class="card">
  <div class="toolbar">
    <button onclick="preset('demo')">Load demo cast (mock)</button>
    <button onclick="preset('models')">Load models cast (GitHub)</button>
    <button onclick="addRow()">+ Add player</button>
    <span class="sp muted" id="pcount"></span>
  </div>
  <div class="rowhead">
    <span>Name</span><span>Provider</span><span>Model</span><span>Persona (free text)</span>
    <span>Personality / intent</span><span>Costume</span><span>Colour</span><span></span>
  </div>
  <div id="players"></div>
  <div class="opts">
    <div><label>Scene</label><select id="scene"><option>harbor</option><option>desert</option><option>vale</option></select></div>
    <div><label>Seed</label><input id="seed" type="number" value="11" style="width:90px"></div>
    <div style="align-self:end"><button class="pri" id="startBtn" onclick="start()">🎲 Start match</button></div>
    <div style="align-self:end"><span id="status" class="muted"></span></div>
  </div>
</div>

<h2>🗂️ Previous matches</h2>
<div class="grid" id="runs"><div class="muted">loading…</div></div>

<datalist id="models">__MODELS_OPTS__</datalist>
<datalist id="intents">__INTENT_OPTS__</datalist>

<script>
const INTENTS=__INTENTS__, COSTUMES=__COSTUMES__, MODELS=__MODELS__, PALETTE=__PALETTE__;
const DEMO=[
 ["Merlin","mock","openai/gpt-4o","calm, analytical, patient","balanced","wizard"],
 ["Roland","mock","meta/llama-3.3-70b-instruct","bold and aggressive","cutthroat","knight"],
 ["Vesper","mock","deepseek/deepseek-v3-0324","sly and secretive","deceptive","vampire"],
 ["Isolde","mock","mistral-ai/mistral-medium-2505","regal diplomat, seeks consensus","diplomatic","queen"]];
const MODELSCAST=[
 ["Merlin","github","openai/gpt-4o","calm, analytical, patient","balanced","wizard"],
 ["Pip","github","openai/gpt-4o-mini","playful opportunist","greedy","jester"],
 ["Roland","github","meta/llama-3.3-70b-instruct","bold and aggressive","cutthroat","knight"],
 ["Vesper","github","deepseek/deepseek-v3-0324","sly and secretive","deceptive","vampire"],
 ["Isolde","github","mistral-ai/mistral-medium-2505","regal diplomat, seeks consensus","diplomatic","queen"],
 ["Bram","github","microsoft/phi-4","quiet, methodical builder","builder","monk"]];

const $=s=>document.querySelector(s), players=$("#players");
function costumeSel(v){return `<select class="f-costume">`+COSTUMES.map(c=>`<option ${c===v?'selected':''}>${c}</option>`).join('')+`</select>`;}
function row(p){
  const [name,prov,model,persona,intent,costume]=p, color=PALETTE[players.children.length%PALETTE.length];
  const d=document.createElement('div'); d.className='prow';
  d.innerHTML=`
    <input class="f-name" value="${name||''}" placeholder="Name">
    <select class="f-prov"><option value="github" ${prov==='github'?'selected':''}>github</option><option value="mock" ${prov==='mock'?'selected':''}>mock</option></select>
    <input class="f-model" list="models" value="${model||''}" placeholder="publisher/model">
    <input class="f-persona" value="${persona||''}" placeholder="e.g. paranoid loner">
    <input class="f-intent" list="intents" value="${intent||'balanced'}" placeholder="preset or custom trait">
    ${costumeSel(costume||'wizard')}
    <input class="f-color" type="color" value="${color}">
    <button class="rm" title="remove" onclick="this.parentNode.remove();count()">✕</button>`;
  players.appendChild(d); count();
}
function addRow(){row(["Player"+(players.children.length+1),"github","","neutral","balanced","wizard"]);}
function preset(k){players.innerHTML='';(k==='demo'?DEMO:MODELSCAST).forEach(row);
  $("#scene").value = k==='demo'?'harbor':'harbor';}
function count(){$("#pcount").textContent=players.children.length+" seats";}

function collect(){
  const ps=[...players.children].map(r=>({
    name:r.querySelector('.f-name').value.trim()||'Player',
    provider:r.querySelector('.f-prov').value,
    model:r.querySelector('.f-model').value.trim()||'openai/gpt-4o',
    persona:r.querySelector('.f-persona').value.trim()||'neutral',
    intent:r.querySelector('.f-intent').value.trim()||'balanced',
    costume:r.querySelector('.f-costume').value,
    color:r.querySelector('.f-color').value,
  }));
  return {name:"custom", seed:+$("#seed").value||0, scene:$("#scene").value, players:ps};
}
let poll=null;
async function start(){
  const cfg=collect();
  if(cfg.players.length<2){$("#status").textContent="Add at least 2 players.";return;}
  $("#startBtn").disabled=true;
  const anyGithub=cfg.players.some(p=>p.provider==='github');
  $("#status").innerHTML='<span style="color:#b5791f">⏳ running…</span> '+(anyGithub?'real models can take a few minutes on the free tier':'');
  const res=await fetch('/api/run',{method:'POST',body:JSON.stringify(cfg)});
  const {job_id,error}=await res.json();
  if(error){$("#status").textContent="Error: "+error;$("#startBtn").disabled=false;return;}
  poll=setInterval(async()=>{
    const j=await (await fetch('/api/job/'+job_id)).json();
    if(j.status==='done'){clearInterval(poll);$("#startBtn").disabled=false;
      $("#status").innerHTML=`✅ <b>${j.winner}</b> wins (${j.reason}) — `+
        `<a class="play" style="display:inline-block;padding:5px 12px" href="${j.scene}" target="_blank">▶ Watch replay</a>`;
      loadRuns();}
    else if(j.status==='error'){clearInterval(poll);$("#startBtn").disabled=false;
      $("#status").innerHTML='<span style="color:#c0392b">✕ '+j.error+'</span>';}
  },1500);
}

async function loadRuns(){
  const runs=await (await fetch('/api/runs')).json();
  $("#runs").innerHTML = runs.length? runs.map(r=>{
    const top=Math.max(0,...Object.values(r.vps||{}));
    const cast=r.players.sort((a,b)=>(r.vps[b.name]||0)-(r.vps[a.name]||0)).map(p=>
      `<div><span class="dot" style="background:${p.color}"></span><b>${p.name}</b> `+
      `<span style="color:#8a7a96">${p.model} · ${p.intent}</span> — ${r.vps[p.name]||0}vp</div>`).join('');
    return `<div class="card run"><div class="top"><span class="nm">${r.name}</span></div>
      <span class="win">🏆 ${r.winner} · ${r.reason}</span>
      <div class="cast">${cast}</div>
      <a class="play" href="${r.scene}" target="_blank">▶ Replay</a></div>`;
  }).join('') : '<div class="muted">No matches yet — start one above.</div>';
}
preset('demo'); loadRuns();
</script></body></html>"""


if __name__ == "__main__":
    serve()
