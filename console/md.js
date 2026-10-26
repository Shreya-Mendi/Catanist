/* md.js: a small markdown renderer for the console (docs, group pages, notes).
   Headings, paragraphs, lists, tables, fenced code, blockquotes, bold, italic,
   inline code, links, images. Escapes HTML first; links open in a new tab. */
(function(){
  const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  function inline(t){
    t=esc(t);
    t=t.replace(/`([^`]+)`/g,(m,c)=>`<code>${c}</code>`);
    t=t.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,(m,a,u)=>`<img alt="${a}" src="${u}" style="max-width:100%">`);
    t=t.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,(m,a,u)=>`<a href="${u}" target="_blank" rel="noopener">${a}</a>`);
    t=t.replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>").replace(/(^|[^*])\*([^*\n]+)\*/g,"$1<i>$2</i>");
    return t;
  }
  function table(lines){
    const rows=lines.map(l=>l.replace(/^\||\|$/g,"").split("|").map(c=>c.trim()));
    const head=rows[0], body=rows.slice(2);
    return `<table><tr>${head.map(h=>`<th>${inline(h)}</th>`).join("")}</tr>${body.map(r=>`<tr>${r.map(c=>`<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</table>`;
  }
  function render(src){
    const lines=String(src||"").replace(/\r/g,"").split("\n"); const out=[]; let i=0;
    while(i<lines.length){
      const l=lines[i];
      if(/^```/.test(l)){ const buf=[]; i++; while(i<lines.length&&!/^```/.test(lines[i])) buf.push(lines[i++]); i++; out.push(`<pre class="mono">${esc(buf.join("\n"))}</pre>`); continue; }
      if(/^\|/.test(l)&&i+1<lines.length&&/^\|?\s*:?-{2,}/.test(lines[i+1])){ const buf=[]; while(i<lines.length&&/^\|/.test(lines[i])) buf.push(lines[i++]); out.push(table(buf)); continue; }
      const h=l.match(/^(#{1,6})\s+(.*)$/); if(h){ out.push(`<h${h[1].length+1}>${inline(h[2])}</h${h[1].length+1}>`); i++; continue; }
      if(/^>\s?/.test(l)){ const buf=[]; while(i<lines.length&&/^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/,"")); out.push(`<blockquote>${inline(buf.join(" "))}</blockquote>`); continue; }
      if(/^(\s*)[-*]\s+/.test(l)){ const buf=[]; while(i<lines.length&&/^(\s*)[-*]\s+/.test(lines[i])) buf.push(lines[i++].replace(/^(\s*)[-*]\s+/,"")); out.push(`<ul>${buf.map(x=>`<li>${inline(x)}</li>`).join("")}</ul>`); continue; }
      if(/^\s*\d+[.)]\s+/.test(l)){ const buf=[]; while(i<lines.length&&/^\s*\d+[.)]\s+/.test(lines[i])) buf.push(lines[i++].replace(/^\s*\d+[.)]\s+/,"")); out.push(`<ol>${buf.map(x=>`<li>${inline(x)}</li>`).join("")}</ol>`); continue; }
      if(!l.trim()){ i++; continue; }
      const buf=[]; while(i<lines.length&&lines[i].trim()&&!/^(#{1,6}\s|```|\||>|\s*[-*]\s|\s*\d+[.)]\s)/.test(lines[i])) buf.push(lines[i++]);
      if(buf.length) out.push(`<p>${inline(buf.join(" "))}</p>`); else i++;
    }
    return `<div class="md">${out.join("\n")}</div>`;
  }
  window.renderMarkdown=render;
})();
