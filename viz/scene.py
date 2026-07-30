"""Cute, illustrated spectator view of a Catan game.

Same soft flat-illustration language as the Mafia arena (pastel scenery, rounded
blob characters in costumes, messenger-style speech bubbles that pop as each model
speaks) — but the round table is replaced by a live-rendering Catan board. Roads,
settlements and cities appear in each player's colour as they are built, the
robber slinks between hexes, trade offers arc between seats, and a victory-point
leaderboard tracks the race to 10. Toggle "peek at thoughts" to read each model's
private reasoning next to what it tells the table.

    python -m viz.scene logs/demo_....json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ — Catan Arena</title>
<style>
  :root{--ink:#2f3b3a;--line:#34403f;--cream:#fbf6ea;--card:#fffdf9;--edge:#d9cdb5;
        --accent:#e0a93d;--shadow:rgba(20,40,40,.3)}
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:#f1e7d6;color:var(--ink);overflow:hidden;
       font:15.5px/1.5 "Chalkboard SE","Comic Sans MS",-apple-system,system-ui,sans-serif}
  .wrap{display:flex;flex-direction:column;height:100vh}
  #stage{position:relative;flex:1;overflow:hidden}
  #scene{position:absolute;inset:0;width:100%;height:100%}
  #world{position:absolute;inset:0}
  #board,#fx{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}

  .char{position:absolute;transform-origin:bottom center;transition:filter .5s,opacity .6s;
        cursor:default;will-change:transform}
  .char svg{display:block;overflow:visible}
  .char .nm{text-align:center;font-weight:700;font-size:12px;margin-top:-8px;
        color:#4a3a55;text-shadow:0 1px 0 #fff}
  .char.speaking{animation:bob .8s ease-in-out infinite}
  @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
  .char.turn .nm{color:#b5791f}
  .halo{position:absolute;left:50%;top:36%;width:130%;height:64%;
        transform:translate(-50%,-50%);border-radius:50%;opacity:0;
        background:radial-gradient(circle,rgba(255,225,150,.8),transparent 68%);
        transition:opacity .3s;pointer-events:none}
  .char.speaking .halo,.char.turn .halo{opacity:1}

  .bubble{position:absolute;left:50%;bottom:102%;transform:translateX(-50%) scale(.6);
        min-width:118px;max-width:224px;background:var(--card);color:var(--ink);
        border:2px solid var(--edge);border-radius:18px;padding:8px 12px;font-size:13px;
        line-height:1.4;box-shadow:0 10px 22px -6px var(--shadow);opacity:0;
        transition:opacity .22s,transform .22s cubic-bezier(.2,1.4,.4,1);
        pointer-events:none;z-index:50;text-align:left}
  .bubble.on{opacity:1;transform:translateX(-50%) scale(1)}
  .bubble::after{content:"";position:absolute;left:50%;top:100%;
        transform:translateX(-50%);border:9px solid transparent;
        border-top-color:var(--card);filter:drop-shadow(0 2px 0 var(--edge))}
  .bubble .who{font-weight:800;font-size:10.5px;letter-spacing:.02em;margin-bottom:2px;opacity:.7}
  .bubble.think{background:#efe7fb;border-color:#dcd0f2;font-style:italic;color:#5a4a72}
  .bubble.think::after{border-top-color:#efe7fb}
  .bubble.act{background:#fff0d9;border-color:#f2dcae}
  .bubble.act::after{border-top-color:#fff0d9}
  .bubble.trade{background:#e2f3ec;border-color:#bfe3d0}
  .bubble.trade::after{border-top-color:#e2f3ec}
  .bubble .th{display:none;margin-top:6px;padding-top:6px;border-top:1px dashed #cbb;
        font-style:italic;color:#7a6a8c;font-size:11.5px}
  body.grimoire .bubble .th{display:block}

  /* banner */
  #banner{position:absolute;left:50%;top:14px;transform:translateX(-50%);
        background:var(--card);border:2.5px solid var(--line);border-radius:999px;
        padding:6px 16px;font-weight:800;font-size:14px;box-shadow:3px 3px 0 var(--shadow);
        display:flex;gap:10px;align-items:center;z-index:60}
  .dice{display:inline-flex;gap:4px}
  .die{width:22px;height:22px;border-radius:6px;background:#fff;border:2px solid var(--line);
       display:grid;place-items:center;font-size:13px;font-weight:800;color:var(--ink)}
  .die.hot{border-color:#e0a93d;color:#c0392b}
  #winPill{padding:2px 12px;border-radius:999px;font-size:12px;display:none}
  .win-on{display:inline-block!important;background:#fff2cf;color:#b5791f}

  /* leaderboard */
  #board-lead{position:absolute;left:14px;top:60px;width:174px;z-index:40;
       background:rgba(255,253,249,.92);border:2.5px solid var(--line);border-radius:16px;
       padding:10px 11px;backdrop-filter:blur(4px);box-shadow:3px 3px 0 var(--shadow)}
  #board-lead h3{margin:0 0 7px;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:#a08}
  .lrow{display:flex;align-items:center;gap:6px;margin:5px 0;font-size:12px;font-weight:700}
  .lrow .dot{width:11px;height:11px;border-radius:50%;flex:none;box-shadow:0 0 0 2px #fff}
  .lrow .ln{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .lrow .vp{font-variant-numeric:tabular-nums}
  .track{height:7px;border-radius:4px;background:#eadfce;overflow:hidden;margin-top:2px}
  .track>i{display:block;height:100%;border-radius:4px;transition:width .5s}

  /* controls */
  .bar{display:flex;gap:10px;align-items:center;padding:11px 18px;background:var(--cream);
       border-top:2.5px solid var(--line);z-index:70}
  button{background:var(--cream);border:2.5px solid var(--line);color:var(--ink);font-weight:700;
       padding:7px 15px;border-radius:12px;cursor:pointer;font-size:14px;
       box-shadow:2px 2px 0 var(--shadow);transition:transform .06s,box-shadow .06s}
  button:active{transform:translate(2px,2px);box-shadow:0 0 0 var(--shadow)}
  button.pri{background:var(--accent);color:#fff;border-color:#c9922f;box-shadow:2px 2px 0 var(--shadow)}
  label{font-size:13px;color:#6b5a78;display:flex;gap:5px;align-items:center;cursor:pointer;font-weight:600}
  .sp{margin-left:auto;color:#8a7a96;font-size:12px;font-weight:600}
  /* chronicle */
  #log{position:absolute;right:14px;top:60px;bottom:14px;width:248px;overflow:auto;
       background:rgba(255,253,249,.94);border:2.5px solid var(--line);border-radius:16px;
       padding:12px;backdrop-filter:blur(4px);z-index:40;box-shadow:3px 3px 0 var(--shadow);
       transform:translateX(120%);transition:transform .3s;opacity:0}
  #log.show{transform:none;opacity:1}
  #log h3{margin:0 0 8px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#a08}
  .li{font-size:12px;padding:5px 7px;border-radius:9px;background:#fff;margin-bottom:5px;
      border:1px solid var(--edge)}
  .li.turn{background:transparent;border:0;text-align:center;color:#a99;font-weight:700;
          font-size:10px;letter-spacing:.1em;text-transform:uppercase;margin:9px 0 4px}
  .li b{color:#a2559f}
</style></head>
<body data-scene="harbor">
<div class="wrap">
  <div id="stage">
    <svg id="scene" viewBox="0 0 1000 680" preserveAspectRatio="xMidYMid slice"></svg>
    <svg id="board" viewBox="0 0 1000 680" preserveAspectRatio="xMidYMid meet"></svg>
    <div id="world"></div>
    <svg id="fx" viewBox="0 0 1000 680" preserveAspectRatio="xMidYMid meet"></svg>
    <div id="banner"><span class="dice"><span class="die" id="d1">·</span><span class="die" id="d2">·</span></span>
      <span id="phaseTxt">Setup</span><span id="winPill"></span></div>
    <div id="board-lead"><h3>✦ Victory Points ✦</h3><div id="leadbody"></div></div>
    <div id="log"><h3>✦ Chronicle ✦</h3><div id="logbody"></div></div>
  </div>
  <div class="bar">
    <button id="restart">⏮</button>
    <button id="step">Step ▶</button>
    <button id="play" class="pri">Play ⏵</button>
    <label><input type="checkbox" id="grim"> peek at thoughts 💭</label>
    <label>speed <input id="speed" type="range" min="220" max="2000" value="900" style="width:80px"></label>
    <button id="logtog">📜 Log</button>
    <span class="sp" id="prog"></span>
  </div>
</div>
<script>
const DATA = __DATA__;
const setup = DATA.setup, events = DATA.events, BOARD = DATA.board;
const scene = DATA.scene || 'harbor';
document.body.dataset.scene = scene;
const P = {}; setup.forEach(p=>P[p.name]=p);

const RES_COLOR = {wood:'#4a9d5b',brick:'#cf7043',sheep:'#a9d977',wheat:'#eec84a',
                   ore:'#9aa7b4',desert:'#e6d5a8'};
const RES_ICON = {wood:'🌲',brick:'🧱',sheep:'🐑',wheat:'🌾',ore:'⛰️'};
const SIZE = 54;  // must match arena/board.py SIZE

/* ---------------- background scenery ---------------- */
function stars(n,h){let s='';for(let i=0;i<n;i++){const x=Math.random()*1000,
  y=Math.random()*h,r=Math.random()*1.5+.5;
  s+=`<circle cx="${x|0}" cy="${y|0}" r="${r.toFixed(1)}" fill="#fff" opacity="${(Math.random()*.6+.3).toFixed(2)}"/>`;}
  return s;}
const SCENES = {
  harbor:()=>`<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#bfe6f2"/><stop offset="1" stop-color="#e8f6ee"/></linearGradient>
      <linearGradient id="sea" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#5cc0d4"/><stop offset="1" stop-color="#3f9fc4"/></linearGradient></defs>
    <rect width="1000" height="680" fill="url(#sky)"/>
    <circle cx="850" cy="110" r="46" fill="#fff3b0"/><circle cx="850" cy="110" r="66" fill="#fff3b0" opacity=".3"/>
    <g fill="#fff" opacity=".85"><ellipse cx="230" cy="130" rx="60" ry="24"/><ellipse cx="285" cy="120" rx="46" ry="22"/>
      <ellipse cx="700" cy="90" rx="52" ry="22"/><ellipse cx="745" cy="98" rx="40" ry="18"/></g>
    <rect y="150" width="1000" height="530" fill="url(#sea)"/>
    <g fill="#fff" opacity=".25"><path d="M0 250 q60 -12 120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 v14 H0z"/>
      <path d="M0 470 q60 -12 120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 v14 H0z" opacity=".7"/></g>`,
  desert:()=>`<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffd9a0"/><stop offset="1" stop-color="#ffe8c4"/></linearGradient></defs>
    <rect width="1000" height="680" fill="url(#sky)"/>
    <circle cx="500" cy="120" r="54" fill="#fff1c0"/>
    <rect y="430" width="1000" height="250" fill="#f0d69a"/>
    <ellipse cx="500" cy="440" rx="560" ry="46" fill="#e8ca86"/>
    <g fill="#e0bd78" opacity=".7"><ellipse cx="180" cy="520" rx="150" ry="40"/><ellipse cx="820" cy="540" rx="170" ry="46"/></g>`,
  vale:()=>`<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#cfeede"/><stop offset="1" stop-color="#eef6e6"/></linearGradient></defs>
    <rect width="1000" height="680" fill="url(#sky)"/>
    <circle cx="835" cy="110" r="48" fill="#fff3b0"/>
    <g fill="#7fbf74" opacity=".55"><ellipse cx="120" cy="250" rx="180" ry="120"/><ellipse cx="900" cy="240" rx="180" ry="130"/>
      <ellipse cx="500" cy="200" rx="150" ry="90"/></g>
    <rect y="430" width="1000" height="250" fill="#8fd07a"/><ellipse cx="500" cy="440" rx="560" ry="44" fill="#7cc267"/>`
};
document.getElementById('scene').innerHTML=(SCENES[scene]||SCENES.harbor)();

/* ---------------- board geometry (fit native coords into the stage) ---------------- */
const xs=BOARD.vertices.map(v=>v.cx), ys=BOARD.vertices.map(v=>v.cy);
const minX=Math.min(...xs)-SIZE, maxX=Math.max(...xs)+SIZE;
const minY=Math.min(...ys)-SIZE, maxY=Math.max(...ys)+SIZE;
const TW=500,TH=402,TCX=500,TCY=300;
const SC=Math.min(TW/(maxX-minX),TH/(maxY-minY));
const OX=TCX-SC*(minX+maxX)/2, OY=TCY-SC*(minY+maxY)/2;
const bx=x=>OX+SC*x, by=y=>OY+SC*y;   // board-native -> stage coords
const V={}, Hx={}; BOARD.vertices.forEach(v=>V[v.id]=v);
BOARD.hexes.forEach(h=>Hx[h.id]=h);
const EV={}; BOARD.edges.forEach(e=>EV[e.id]=e);

function hexPts(cx,cy,r){let s='';for(let k=0;k<6;k++){const a=Math.PI/180*(60*k-90);
  s+=(bx(cx+r*Math.cos(a)).toFixed(1))+','+(by(cy+r*Math.sin(a)).toFixed(1))+' ';}return s.trim();}
function pip(n){return n==null?0:6-Math.abs(7-n);}

let robberHex = BOARD.robber;
function paintBoard(){
  const s=document.getElementById('board'); let g='';
  // water disc behind the island
  g+=`<ellipse cx="${TCX}" cy="${TCY}" rx="${SC*(maxX-minX)/2+14}" ry="${SC*(maxY-minY)/2+14}"
        fill="#8fd6e6" stroke="#e7d9bf" stroke-width="6" opacity=".55"/>`;
  BOARD.hexes.forEach(h=>{
    g+=`<polygon points="${hexPts(h.cx,h.cy,SIZE)}" fill="${RES_COLOR[h.resource]}"
          stroke="#e7d9bf" stroke-width="3" stroke-linejoin="round"/>`;
    if(h.number!=null){
      const cx=bx(h.cx),cy=by(h.cy),hot=(h.number==6||h.number==8);
      g+=`<circle cx="${cx}" cy="${cy}" r="${13*SC}" fill="#f7efdd" stroke="#d9c9a6" stroke-width="1.5"/>`;
      g+=`<text x="${cx}" y="${cy+1}" text-anchor="middle" dominant-baseline="middle"
            font-size="${15*SC}" font-weight="800" fill="${hot?'#c0392b':'#5a4a3a'}">${h.number}</text>`;
      let dots='',pc=pip(h.number),dx=-(pc-1)*2.1;
      for(let i=0;i<pc;i++)dots+=`<circle cx="${cx+(dx+i*4.2)*SC}" cy="${cy+11*SC}" r="${1.3*SC}" fill="${hot?'#c0392b':'#7a6a55'}"/>`;
      g+=dots;
    }
  });
  // ports
  BOARD.ports.forEach(p=>{
    const cx=bx(p.cx),cy=by(p.cy);
    const lab=p.type==='3:1'?'3:1':RES_ICON[p.type]||'?';
    g+=`<circle cx="${cx}" cy="${cy}" r="${9*SC}" fill="#fffdf9" stroke="#c9922f" stroke-width="1.5"/>`;
    g+=`<text x="${cx}" y="${cy+1}" text-anchor="middle" dominant-baseline="middle" font-size="${8.5*SC}" font-weight="800" fill="#b5791f">${lab}</text>`;
  });
  s.innerHTML=g+'<g id="pieces"></g><g id="robber"></g>';
  drawRobber();
}
function drawRobber(){
  const h=Hx[robberHex],x=bx(h.cx),y=by(h.cy)-6*SC,r=document.getElementById('robber');
  r.innerHTML=`<g opacity=".92"><ellipse cx="${x}" cy="${y+14*SC}" rx="${9*SC}" ry="${3*SC}" fill="rgba(0,0,0,.25)"/>
    <path d="M${x-8*SC} ${y+13*SC} q0 -20 ${8*SC} -20 q${8*SC} 0 ${8*SC} 20 z" fill="#3a3340"/>
    <circle cx="${x}" cy="${y-9*SC}" r="${5*SC}" fill="#3a3340"/></g>`;
}
function moveRobber(hid){robberHex=hid;drawRobber();}

/* buildings */
function house(x,y,color,city){
  const dk='#2a2030';
  if(city) return `<g transform="translate(${x},${y})">
     <ellipse cx="0" cy="${9*SC}" rx="${11*SC}" ry="${3*SC}" fill="rgba(0,0,0,.22)"/>
     <path d="M${-11*SC} ${8*SC} h${22*SC} v${-9*SC} h${-8*SC} v${-6*SC} l${-3*SC} ${-4*SC} l${-3*SC} ${4*SC} v${6*SC} z"
        fill="${color}" stroke="${dk}" stroke-width="1.6" stroke-linejoin="round"/></g>`;
  return `<g transform="translate(${x},${y})">
     <ellipse cx="0" cy="${7*SC}" rx="${8*SC}" ry="${2.4*SC}" fill="rgba(0,0,0,.22)"/>
     <path d="M${-7*SC} ${6*SC} v${-6*SC} l${7*SC} ${-6*SC} l${7*SC} ${6*SC} v${6*SC} z"
        fill="${color}" stroke="${dk}" stroke-width="1.6" stroke-linejoin="round"/></g>`;
}
function addBuilding(vid,color,city){
  const v=V[vid],p=document.getElementById('pieces');
  const old=p.querySelector(`[data-v="${vid}"]`); if(old)old.remove();
  const g=document.createElementNS('http://www.w3.org/2000/svg','g');
  g.setAttribute('data-v',vid); g.innerHTML=house(bx(v.cx),by(v.cy),color,city);
  g.style.transformOrigin=`${bx(v.cx)}px ${by(v.cy)}px`;
  g.animate([{transform:'scale(0)'},{transform:'scale(1.15)'},{transform:'scale(1)'}],{duration:420});
  p.appendChild(g);
}
function addRoad(eid,color){
  const e=EV[eid],a=V[e.v[0]],b=V[e.v[1]],p=document.getElementById('pieces');
  const x1=bx(a.cx),y1=by(a.cy),x2=bx(b.cx),y2=by(b.cy);
  const dx=x2-x1,dy=y2-y1,L=Math.hypot(dx,dy)||1,pad=L*0.22;
  const ux=dx/L,uy=dy/L;
  const X1=x1+ux*pad,Y1=y1+uy*pad,X2=x2-ux*pad,Y2=y2-uy*pad;
  const g=document.createElementNS('http://www.w3.org/2000/svg','g');
  g.innerHTML=`<line x1="${X1}" y1="${Y1}" x2="${X2}" y2="${Y2}" stroke="#2a2030" stroke-width="${8.5*SC}" stroke-linecap="round"/>
    <line x1="${X1}" y1="${Y1}" x2="${X2}" y2="${Y2}" stroke="${color}" stroke-width="${5.5*SC}" stroke-linecap="round"/>`;
  const ln=g.querySelector('line + line');
  ln.style.strokeDasharray=L; ln.style.strokeDashoffset=L;
  ln.animate([{strokeDashoffset:L},{strokeDashoffset:0}],{duration:380,fill:'forwards'});
  p.appendChild(g);
}

/* ---------------- characters (blob + costume) ---------------- */
const COSTUMES = {
  wizard:c=>`<polygon points="70,-2 42,58 98,58" fill="#6b4bc9"/><polygon points="70,-2 70,58 98,58" fill="#5a3db0"/>
     <ellipse cx="70" cy="58" rx="34" ry="9" fill="#4a2f96"/>
     <path d="M70 12 l4 9 10 1 -8 7 3 10 -9 -6 -9 6 3 -10 -8 -7 10 -1z" fill="#ffe27a"/>`,
  knight:c=>`<path d="M44 40 q26 -30 52 0 v14 h-52z" fill="#c7ced8"/><rect x="44" y="40" width="52" height="8" fill="#9aa5b3"/>
     <rect x="60" y="22" width="20" height="6" rx="3" fill="#e05c5c"/><path d="M70 4 q10 8 4 20 q-4 -10 -4 -20z" fill="#e05c5c"/>`,
  vampire:c=>`<path d="M40 46 q30 -34 60 0 q-16 -8 -30 6 q-14 -14 -30 -6z" fill="#20141f"/>
     <path d="M70 30 v10" stroke="#20141f" stroke-width="5"/>
     <path d="M34 60 q36 22 72 0 l-6 -16 q-30 16 -60 0z" fill="#7a1f3d" opacity=".9"/>`,
  jester:c=>`<g><path d="M46 44 q-8 -34 -18 -30 q-4 8 6 16 q-14 -2 -12 8 q10 8 18 4z" fill="#e0556f"/>
     <path d="M94 44 q8 -34 18 -30 q4 8 -6 16 q14 -2 12 8 q-10 8 -18 4z" fill="#3d9bf2"/>
     <path d="M56 44 q14 -40 28 0z" fill="#f2c14b"/>
     <circle cx="28" cy="16" r="4" fill="#f2c14b"/><circle cx="112" cy="16" r="4" fill="#f2c14b"/>
     <circle cx="70" cy="6" r="4" fill="#e0556f"/></g>`,
  queen:c=>`<path d="M46 44 l0 -22 12 12 12 -18 12 18 12 -12 0 22z" fill="#f2c94c"/>
     <rect x="46" y="42" width="48" height="8" rx="3" fill="#e0b53a"/>
     <circle cx="58" cy="30" r="3" fill="#e05c8a"/><circle cx="70" cy="24" r="3" fill="#5cc2e0"/><circle cx="82" cy="30" r="3" fill="#7ad67a"/>`,
  monk:c=>`<path d="M34 60 q0 -46 36 -46 q36 0 36 46 q-36 -20 -72 0z" fill="#8a5a34"/>
     <path d="M40 54 q30 -14 60 0" fill="none" stroke="#6e4526" stroke-width="4"/>`,
  ranger:c=>`<path d="M40 48 q30 -22 60 0 q-30 -8 -60 0z" fill="#3f7d4a"/>
     <path d="M40 48 q30 -12 60 0 l0 6 q-30 -8 -60 0z" fill="#2f6238"/><path d="M98 40 q22 -12 26 2 q-16 -2 -26 4z" fill="#c0563d"/>`,
  bard:c=>`<path d="M38 50 q32 -26 64 0 q-6 -12 -32 -12 q-26 0 -32 12z" fill="#c96fae"/>
     <path d="M100 42 q24 -18 28 0 q-16 -4 -28 6z" fill="#f2e05c"/>`,
  merchant:c=>`<path d="M40 46 q30 -20 60 0 l0 8 q-30 -12 -60 0z" fill="#c98a3d"/>
     <rect x="46" y="30" width="48" height="12" rx="4" fill="#e0b060"/><rect x="64" y="20" width="12" height="12" rx="3" fill="#8a5a2a"/>`,
  default:c=>`<path d="M46 48 q24 -20 48 0z" fill="${c||'#c98bd6'}" opacity=".8"/>`
};
function shade(hex,amt){const n=parseInt((hex||'#c98bd6').slice(1),16);
  let r=(n>>16)+amt,g=((n>>8)&255)+amt,b=(n&255)+amt;
  r=Math.max(0,Math.min(255,r));g=Math.max(0,Math.min(255,g));b=Math.max(0,Math.min(255,b));
  return '#'+((r<<16)|(g<<8)|b).toString(16).padStart(6,'0');}
function charSVG(p,expr){
  const c=p.color||'#c98bd6',dark=shade(c,-28),light=shade(c,26);
  const face= expr==='dead'
    ? `<path d="M56 92 l10 10 M66 92 l-10 10" stroke="#5a4a55" stroke-width="3" stroke-linecap="round"/>
       <path d="M84 92 l10 10 M94 92 l-10 10" stroke="#5a4a55" stroke-width="3" stroke-linecap="round"/>`
    : `<ellipse cx="58" cy="96" rx="8" ry="9" fill="#fff"/><ellipse cx="86" cy="96" rx="8" ry="9" fill="#fff"/>
       <circle cx="${expr==='speak'?60:58}" cy="98" r="4" fill="#3a2f42"/><circle cx="${expr==='speak'?88:86}" cy="98" r="4" fill="#3a2f42"/>
       <circle cx="44" cy="110" r="7" fill="#ff9bb0" opacity=".55"/><circle cx="100" cy="110" r="7" fill="#ff9bb0" opacity=".55"/>
       ${expr==='speak'?'<ellipse cx="72" cy="118" rx="9" ry="7" fill="#7a3b52"/>'
         :'<path d="M60 116 q12 10 24 0" fill="none" stroke="#7a3b52" stroke-width="3.5" stroke-linecap="round"/>'}`;
  return `<svg width="132" height="172" viewBox="0 0 140 180">
    <defs><linearGradient id="b${p.name}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${c}"/></linearGradient></defs>
    <ellipse cx="70" cy="172" rx="40" ry="8" fill="rgba(60,40,60,.22)"/>
    <path d="M70 44 q52 0 52 78 q0 44 -52 44 q-52 0 -52 -44 q0 -78 52 -78z" fill="url(#b${p.name})"/>
    <path d="M70 44 q52 0 52 78 q0 20 -14 32 q10 -18 6 -48 q-8 -52 -44 -62z" fill="${dark}" opacity=".25"/>
    ${face}${(COSTUMES[p.costume]||COSTUMES.default)(c)}</svg>`;
}

/* ---------------- seat layout around the board ---------------- */
const world=document.getElementById('world'), fx=document.getElementById('fx');
const seat={}, pt={};
function buildSeats(){
  document.querySelectorAll('.char').forEach(e=>e.remove());
  const n=setup.length;
  setup.forEach((p,i)=>{
    const a=Math.PI/2 + Math.PI/n + i*2*Math.PI/n;  // offset so no seat sits under the banner
    const ex=50 + 39*Math.cos(a);
    const ey=50 + 38*Math.sin(a);
    const depth=(Math.sin(a)+1)/2, s=0.5+0.36*depth;
    const d=document.createElement('div');
    d.className='char'; d.dataset.name=p.name;
    d.style.left=ex+'%'; d.style.top=ey+'%';
    d.style.transform=`translate(-50%,-84%) scale(${s.toFixed(3)})`;
    d.style.zIndex=200+Math.round(depth*100);
    d.innerHTML=`<div class="halo"></div>${charSVG(p,'idle')}<div class="nm">${p.name}</div>
       <div class="bubble"><div class="who"></div><div class="say"></div><div class="th"></div></div>`;
    world.appendChild(d); seat[p.name]=d;
    pt[p.name]={x:ex/100*1000, y:ey/100*680 - 40};
  });
}
function setExpr(name,expr){const el=seat[name]; if(!el)return;
  el.querySelector('svg').outerHTML=charSVG(P[name],expr);}

/* ---------------- speech + fx ---------------- */
function clearBubbles(){document.querySelectorAll('.bubble.on').forEach(b=>b.classList.remove('on'));
  document.querySelectorAll('.char.speaking').forEach(c=>{c.classList.remove('speaking');
    setExpr(c.dataset.name,'idle');});}
function say(name,text,priv,kind){
  clearBubbles(); const el=seat[name]; if(!el)return;
  el.classList.add('speaking'); setExpr(name,'speak');
  const b=el.querySelector('.bubble');
  b.className='bubble '+(kind||'');
  b.querySelector('.who').textContent=name;
  b.querySelector('.say').innerHTML=text;
  b.querySelector('.th').textContent=priv?('💭 '+priv):'';
  void b.offsetWidth; b.classList.add('on');
}
function markTurn(name){document.querySelectorAll('.char.turn').forEach(c=>c.classList.remove('turn'));
  const el=seat[name]; if(el)el.classList.add('turn');}
function arrow(from,to,color,dash){
  const a=pt[from],b=pt[to]; if(!a||!b)return;
  const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,pad=40;
  const x1=a.x+dx/len*pad,y1=a.y+dy/len*pad,x2=b.x-dx/len*pad,y2=b.y-dy/len*pad;
  const mx=(x1+x2)/2,my=Math.min(y1,y2)-70;
  const l=document.createElementNS('http://www.w3.org/2000/svg','path');
  l.setAttribute('d',`M${x1} ${y1} Q${mx} ${my} ${x2} ${y2}`);
  l.setAttribute('fill','none');l.setAttribute('stroke',color);l.setAttribute('stroke-width','4.5');
  l.setAttribute('stroke-linecap','round');l.setAttribute('opacity','.9');
  if(dash)l.setAttribute('stroke-dasharray','9 9');
  fx.appendChild(l);
  const L=l.getTotalLength();
  if(!dash){l.style.strokeDasharray=L;l.style.strokeDashoffset=L;
    l.animate([{strokeDashoffset:L},{strokeDashoffset:0}],{duration:460,fill:'forwards'});}
  const head=document.createElementNS('http://www.w3.org/2000/svg','circle');
  head.setAttribute('cx',x2);head.setAttribute('cy',y2);head.setAttribute('r','6');head.setAttribute('fill',color);
  fx.appendChild(head);
}
function clearFx(){fx.innerHTML='';}
function bundle(b){return Object.entries(b||{}).map(([r,n])=>`${n}${RES_ICON[r]||r}`).join(' ')||'—';}

/* leaderboard */
function renderLead(totals){
  const body=document.getElementById('leadbody');
  const top=Math.max(0,...Object.values(totals||{}));
  body.innerHTML=setup.map(p=>{
    const vp=(totals&&totals[p.name])||0, crown=(vp===top&&top>0)?' 👑':'';
    return `<div class="lrow"><span class="dot" style="background:${p.color}"></span>
      <span class="ln">${p.name}${crown}</span><span class="vp">${vp}</span></div>
      <div class="track"><i style="width:${Math.min(100,vp*10)}%;background:${p.color}"></i></div>`;
  }).join('');
}

function logLine(html,cls){const d=document.createElement('div');d.className='li '+(cls||'');
  d.innerHTML=html;document.getElementById('logbody').appendChild(d);d.scrollIntoView({block:'end'});}

/* ---------------- playback ---------------- */
let idx=0, timer=null, speed=900;
function dice(d1,d2,total){
  const e1=document.getElementById('d1'),e2=document.getElementById('d2');
  e1.textContent=d1;e2.textContent=d2;
  const hot=total===7; e1.classList.toggle('hot',hot);e2.classList.toggle('hot',hot);
  document.getElementById('phaseTxt').textContent='rolled '+total;
}
function render(ev){
  switch(ev.type){
    case 'turn':
      markTurn(ev.actor);
      document.getElementById('phaseTxt').textContent='Turn '+ev.n+' · '+ev.actor;
      logLine('Turn '+ev.n+' — '+ev.actor,'turn'); return true;
    case 'roll': dice(ev.d1,ev.d2,ev.total);
      logLine(`<b>${ev.actor}</b> 🎲 ${ev.d1}+${ev.d2} = <b>${ev.total}</b>`); return true;
    case 'production':{
      const parts=Object.entries(ev.gains||{}).map(([n,g])=>`${n}: ${bundle(g)}`);
      if(!parts.length){logLine(`no one collects on ${ev.total}`);return false;}
      logLine('🎁 '+parts.join(' · ')); return false; }
    case 'build':{
      const col=P[ev.actor].color;
      if(ev.kind==='road') addRoad(ev.edge,col);
      else addBuilding(ev.vertex,col,ev.kind==='city');
      const icon=ev.kind==='city'?'🏛️':ev.kind==='settlement'?'🏠':'🛤️';
      if(!ev.setup) say(ev.actor,`${icon} built a ${ev.kind}`,ev.private,'act');
      logLine(`<b>${ev.actor}</b> ${icon} ${ev.kind}`); return !ev.setup; }
    case 'trade_proposal':
      say(ev.proposer,`🤝 give ${bundle(ev.give)} · want ${bundle(ev.want)}`,ev.private,'trade');
      arrow(ev.proposer,ev.target,'#3fae8f',true);
      logLine(`<b>${ev.proposer}</b> → ${ev.target}: give ${bundle(ev.give)} / want ${bundle(ev.want)}`); return true;
    case 'trade_response':
      say(ev.responder,(ev.accept?'✅ ':'🚫 ')+ (ev.public||(ev.accept?'Deal':'Pass')),ev.private,ev.accept?'trade':'');
      logLine(`<b>${ev.responder}</b> ${ev.accept?'accepts ✅':'declines 🚫'}`); return true;
    case 'trade_exec':
      arrow(ev.proposer,ev.target,'#2e8b57'); arrow(ev.target,ev.proposer,'#e0a93d');
      logLine(`🔄 ${ev.proposer} ⇄ ${ev.target}`); return false;
    case 'bank_trade':
      say(ev.actor,`🏦 ${bundle(ev.give)} → ${bundle(ev.want)}`,ev.private,'act');
      logLine(`<b>${ev.actor}</b> 🏦 ${bundle(ev.give)} → ${bundle(ev.want)}`); return true;
    case 'dev_buy': say(ev.actor,'🃏 buys a development card',ev.private,'act');
      logLine(`<b>${ev.actor}</b> 🃏 dev card`); return true;
    case 'dev_play':{
      const d=ev.detail||{}; let extra='';
      if(ev.card==='monopoly')extra=` (${d.resource}: +${d.taken})`;
      if(ev.card==='year_of_plenty')extra=` (+${(d.resources||[]).join(', ')})`;
      say(ev.actor,`✨ plays ${ev.card.replace('_',' ')}`,ev.private,'act');
      logLine(`<b>${ev.actor}</b> ✨ ${ev.card.replace('_',' ')}${extra}`); return true; }
    case 'robber_move':
      moveRobber(ev.hex);
      say(ev.actor,`🦹 robber → H${ev.hex}${ev.victim?` · rob ${ev.victim}`:''}`,ev.private,'act');
      if(ev.victim)arrow(ev.actor,ev.victim,'#c0392b');
      logLine(`<b>${ev.actor}</b> 🦹 robber → H${ev.hex}${ev.victim?`, steals from ${ev.victim}`:''}`); return true;
    case 'discard': logLine(`🗑️ ${ev.actor} discards ${bundle(ev.dropped)}`); return false;
    case 'award':
      logLine(`👑 <b>${ev.kind.replace('_',' ')}</b> → ${ev.holder} (${ev.value})`);
      document.getElementById('phaseTxt').textContent='👑 '+ev.kind.replace('_',' ')+' → '+ev.holder; return true;
    case 'vp': renderLead(ev.totals); return false;
    case 'game_over':{
      clearBubbles(); clearFx();
      const wp=document.getElementById('winPill');
      wp.textContent='🏆 '+ev.winner+' wins'; wp.className='win-on';
      document.getElementById('phaseTxt').textContent=ev.reason;
      const el=seat[ev.winner]; if(el){el.classList.add('turn');
        el.animate([{transform:el.style.transform},{transform:el.style.transform+' translateY(-14px)'},
          {transform:el.style.transform}],{duration:700,iterations:3});}
      logLine(`🏁 <b>${ev.winner} wins</b> — ${ev.reason}`); confetti(); return true; }
  }
  return false;
}
function confetti(){for(let i=0;i<80;i++){const c=document.createElement('div');
  c.style.cssText=`position:absolute;left:${Math.random()*100}%;top:-20px;width:8px;height:12px;
    background:${['#e0a93d','#e05c5c','#3d9bf2','#7ad67a','#c96fae'][i%5]};z-index:90;border-radius:2px`;
  document.getElementById('stage').appendChild(c);
  c.animate([{transform:'translateY(0) rotate(0)',opacity:1},
    {transform:`translateY(720px) rotate(${720+Math.random()*360}deg)`,opacity:.9}],
    {duration:1600+Math.random()*1200,easing:'ease-in'}).onfinish=()=>c.remove();}}

function step(){while(idx<events.length){const ok=render(events[idx]); idx++;
  document.getElementById('prog').textContent=idx+' / '+events.length;
  if(ok)return true;}
  if(timer){clearInterval(timer);timer=null;document.getElementById('play').textContent='Play ⏵';}return false;}
function reset(){idx=0;robberHex=BOARD.robber;
  document.getElementById('logbody').innerHTML='';clearFx();paintBoard();buildSeats();
  renderLead({});document.getElementById('winPill').className='';
  document.getElementById('phaseTxt').textContent='Setup';
  document.getElementById('d1').textContent='·';document.getElementById('d2').textContent='·';}

document.getElementById('step').onclick=step;
document.getElementById('restart').onclick=reset;
document.getElementById('play').onclick=e=>{if(timer){clearInterval(timer);timer=null;e.target.textContent='Play ⏵';return;}
  e.target.textContent='Pause ⏸';timer=setInterval(()=>{if(!step()){clearInterval(timer);timer=null;e.target.textContent='Play ⏵';}},speed);};
document.getElementById('speed').oninput=e=>{speed=+e.target.value;
  if(timer){clearInterval(timer);timer=setInterval(()=>{if(!step()){clearInterval(timer);timer=null;}},speed);}};
document.getElementById('grim').onchange=e=>document.body.classList.toggle('grimoire',e.target.checked);
document.getElementById('logtog').onclick=()=>document.getElementById('log').classList.toggle('show');
addEventListener('resize',()=>{const k=idx;paintBoard();buildSeats();});
reset();
</script>
</body></html>"""


def render(result: dict, out_path: Path | None = None) -> Path:
    title = result.get("config_name", "game")
    html = (_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__DATA__", json.dumps(result)))
    out_path = out_path or Path(f"{title}_scene.html")
    out_path.write_text(html)
    return out_path


def main(argv):
    src = Path(argv[1])
    result = json.loads(src.read_text())
    out = render(result, src.with_name(src.stem + "_scene.html"))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv)
