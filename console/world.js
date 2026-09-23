/* The living world behind the console: drifting low-poly hex islands, soft
   clouds, and every so often a plump pigeon crossing the sky. Pure canvas. */
(function(){
  const cv=document.getElementById("world"),cx=cv.getContext("2d");
  let W,H,t=0;
  const fit=()=>{W=cv.width=innerWidth*devicePixelRatio;H=cv.height=innerHeight*devicePixelRatio;
    cx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);};
  addEventListener("resize",fit);fit();
  const w=()=>innerWidth,h=()=>innerHeight;
  const TOPS=["#8fd0a5","#a6dbba","#7cc9b0","#b9e3c6","#89c9d8","#9ad4c3"];
  const isl=[];
  const R=(a,b)=>a+Math.random()*(b-a);
  function cluster(cxp,cyp,n,s){
    for(let i=0;i<n;i++) isl.push({x:cxp+R(-2.2,2.2)*s,y:cyp+R(-1.1,1.1)*s*.62,
      s:R(.55,1)*s,c:TOPS[Math.floor(Math.random()*TOPS.length)],
      ph:R(0,6.28),sp:R(.4,.9)});
  }
  cluster(w()*.86,h()*.78,7,46); cluster(w()*.10,h()*.86,5,34);
  cluster(w()*.72,h()*.16,3,22);
  const clouds=Array.from({length:6},()=>({x:R(0,w()),y:R(.05,.5)*h(),
    s:R(50,120),v:R(6,14)}));
  const bird={t:-1,x:0,y:0};
  function hex(x,y,s,top,bob){
    const yy=y+Math.sin(bob)*4, d=s*.32;
    cx.beginPath();
    for(let i=0;i<6;i++){const a=Math.PI/3*i+Math.PI/6;
      cx[i?"lineTo":"moveTo"](x+s*Math.cos(a),yy+s*.58*Math.sin(a));}
    cx.closePath();
    const g=cx.createLinearGradient(x,yy-s,x,yy+s);
    g.addColorStop(0,top);g.addColorStop(1,shade(top,-14));
    cx.fillStyle=g;cx.fill();
    cx.beginPath();
    cx.moveTo(x-s*Math.cos(Math.PI/6),yy+s*.58*Math.sin(Math.PI/6));
    cx.lineTo(x-s*Math.cos(Math.PI/6),yy+s*.58*Math.sin(Math.PI/6)+d);
    cx.lineTo(x,yy+s*.58+d);cx.lineTo(x+s*Math.cos(Math.PI/6),yy+s*.58*Math.sin(Math.PI/6)+d);
    cx.lineTo(x+s*Math.cos(Math.PI/6),yy+s*.58*Math.sin(Math.PI/6));
    cx.lineTo(x,yy+s*.58);cx.closePath();
    cx.fillStyle=shade(top,-32);cx.fill();
  }
  function shade(hexc,amt){
    const n=parseInt(hexc.slice(1),16),r=Math.max(0,Math.min(255,(n>>16)+amt)),
      g=Math.max(0,Math.min(255,((n>>8)&255)+amt)),b=Math.max(0,Math.min(255,(n&255)+amt));
    return `rgb(${r},${g},${b})`;
  }
  function cloud(c){
    cx.fillStyle="rgba(255,255,255,.75)";
    for(const[dx,dy,r]of[[0,0,.5],[.4,.08,.36],[-.42,.1,.32],[.15,-.16,.3]])
      cx.beginPath(),cx.ellipse(c.x+dx*c.s,c.y+dy*c.s,c.s*r,c.s*r*.6,0,0,7),cx.fill();
  }
  function pigeon(p){
    const flap=Math.sin(t*14)*7;
    cx.save();cx.translate(p.x,p.y);cx.fillStyle="#fff";
    cx.strokeStyle="#c6d6e0";cx.lineWidth=1.4;
    cx.beginPath();cx.ellipse(0,0,11,7.5,0,0,7);cx.fill();cx.stroke();
    cx.beginPath();cx.ellipse(9,-4,4.6,3.8,0,0,7);cx.fill();cx.stroke();
    cx.fillStyle="#e88b4a";cx.beginPath();cx.moveTo(13,-4);cx.lineTo(17,-3);cx.lineTo(13,-2);cx.fill();
    cx.fillStyle="#fff";cx.strokeStyle="#c6d6e0";
    cx.beginPath();cx.moveTo(-2,-2);cx.quadraticCurveTo(-6,-10-flap,-14,-6-flap);
    cx.quadraticCurveTo(-7,-2,-2,-2);cx.fill();cx.stroke();
    cx.fillStyle="#25313c";cx.beginPath();cx.arc(10,-4.6,.9,0,7);cx.fill();
    cx.restore();
  }
  function frame(){
    t+=1/60;cx.clearRect(0,0,w(),h());
    for(const c of clouds){c.x+=c.v/60;if(c.x-c.s*1.6>w())c.x=-c.s*1.6;cloud(c);}
    cx.globalAlpha=.9;
    for(const i of isl) hex(i.x,i.y,i.s,i.c,t*i.sp+i.ph);
    cx.globalAlpha=1;
    if(bird.t<0 && Math.random()<.0012){bird.t=0;bird.y=R(.08,.4)*h();}
    if(bird.t>=0){bird.t+=1/60;bird.x=-30+bird.t*95;
      const y=bird.y+Math.sin(bird.t*1.3)*22; pigeon({x:bird.x,y});
      if(bird.x>w()+40)bird.t=-1;}
    requestAnimationFrame(frame);
  }
  frame();
})();
