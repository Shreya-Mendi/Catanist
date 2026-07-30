"""A persistent replay hub for every saved game.

Scans ``logs/*.json`` (the source-of-truth game logs), (re)renders any missing
scene HTML, and writes ``logs/gallery.html`` — a browsable index of every match
ever run, newest first, with the cast (model + intent), the winner, final scores,
and a one-click **▶ Replay** link. Rebuilt automatically after each ``play`` and
on demand with ``python run.py gallery``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .scene import render as render_scene

_STAMP_RE = re.compile(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})")

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

_TPL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Catan Arena — replays</title>
<style>
 body{margin:0;background:#f1e7d6;color:#2f3b3a;
   font:15.5px/1.5 "Chalkboard SE","Comic Sans MS",-apple-system,system-ui,sans-serif;padding:26px}
 h1{margin:0 0 2px}.sub{color:#7c8a6a;margin-bottom:22px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
 .card{background:#fffdf9;border:2.5px solid #34403f;border-radius:18px;padding:15px 17px;
   box-shadow:3px 3px 0 rgba(20,40,40,.3);display:flex;flex-direction:column;gap:9px}
 .top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
 .nm{font-weight:800;font-size:16px}.when{color:#a99;font-size:11.5px;font-variant-numeric:tabular-nums}
 .win{display:inline-flex;align-items:center;gap:6px;background:#fff2cf;color:#b5791f;
   border-radius:999px;padding:3px 11px;font-weight:800;font-size:13px;width:fit-content}
 .cast{display:flex;flex-direction:column;gap:3px;font-size:12.5px}
 .row{display:flex;align-items:center;gap:7px}
 .dot{width:11px;height:11px;border-radius:50%;flex:none;box-shadow:0 0 0 2px #fff}
 .row .pn{font-weight:700}.row .mi{color:#8a7a96}
 .row .vp{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:800}
 .row.w .pn{color:#b5791f}
 a.play{margin-top:4px;text-align:center;background:#e0a93d;color:#fff;border:2.5px solid #34403f;border-radius:12px;
   padding:7px;font-weight:800;text-decoration:none;box-shadow:2px 2px 0 rgba(20,40,40,.3)}
 a.play:hover{filter:brightness(1.05)}
 .empty{color:#8a7a96}
</style></head><body>
<h1>🏝️ Catan Arena — Replays</h1>
<div class="sub">__COUNT__ saved matches · newest first</div>
<div class="grid">__CARDS__</div>
</body></html>"""


def _stamp(path: Path) -> str:
    m = _STAMP_RE.search(path.stem)
    if not m:
        return ""
    y, mo, d, h, mi, _ = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}"


def _card(path: Path, result: dict) -> str:
    setup = result.get("setup", [])
    vps = result.get("vps", {})
    winner = result.get("winner", "?")
    name = result.get("config_name", path.stem)
    scene_file = path.with_name(path.stem + "_scene.html").name
    rows = ""
    for p in sorted(setup, key=lambda p: -(vps.get(p["name"], 0))):
        w = " w" if p["name"] == winner else ""
        rows += (f'<div class="row{w}"><span class="dot" style="background:{p.get("color","#ccc")}"></span>'
                 f'<span class="pn">{p["name"]}</span>'
                 f'<span class="mi">{p.get("model","?")} · {p.get("intent","?")}</span>'
                 f'<span class="vp">{vps.get(p["name"],0)}</span></div>')
    reason = result.get("reason", "")
    return (f'<div class="card"><div class="top"><span class="nm">{name}</span>'
            f'<span class="when">{_stamp(path)}</span></div>'
            f'<span class="win">🏆 {winner} <span style="opacity:.7;font-weight:600">· {reason}</span></span>'
            f'<div class="cast">{rows}</div>'
            f'<a class="play" href="{scene_file}">▶ Replay</a></div>')


def build_gallery(out_path: Path | None = None, rerender_missing: bool = True) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    out_path = out_path or (LOG_DIR / "gallery.html")
    logs = sorted([p for p in LOG_DIR.glob("*.json")],
                  key=lambda p: p.stat().st_mtime, reverse=True)
    cards = []
    for jp in logs:
        try:
            result = json.loads(jp.read_text())
            if "events" not in result or "setup" not in result:
                continue
            scene = jp.with_name(jp.stem + "_scene.html")
            if rerender_missing and not scene.exists():
                try:
                    render_scene(result, scene)
                except Exception:
                    pass
            cards.append(_card(jp, result))
        except Exception:
            continue
    body = "".join(cards) or '<div class="empty">No games yet — run <code>python run.py play configs/demo.json --scene</code>.</div>'
    html = (_TPL.replace("__COUNT__", str(len(cards)))
            .replace("__CARDS__", body))
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    print("wrote", build_gallery())
