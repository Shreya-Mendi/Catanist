"""A small comparison index for a sweep: aggregate metrics + links to every scene."""
from __future__ import annotations

import json
from pathlib import Path

_TPL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Catan Arena — sweep index</title>
<style>
 body{margin:0;background:#f3e7d7;color:#43354f;
   font:15px/1.55 "Baloo 2",-apple-system,"Segoe UI",system-ui,sans-serif;padding:28px}
 h1{margin:0 0 4px}.sub{color:#8a7a96;margin-bottom:20px}
 .card{background:#fffdf9;border:2px solid #eadfce;border-radius:16px;padding:16px 18px;
   margin-bottom:16px;box-shadow:0 8px 18px -10px rgba(80,50,80,.25)}
 h2{margin:0 0 10px;font-size:15px;letter-spacing:.1em;text-transform:uppercase;color:#a2559f}
 table{border-collapse:collapse;width:100%;font-size:13.5px}
 th,td{text-align:left;padding:6px 12px;border-bottom:1px solid #eadfce}
 th{color:#8a7a96;font-weight:700}
 td.n{font-variant-numeric:tabular-nums}
 a{color:#b5791f;font-weight:700;text-decoration:none}a:hover{text-decoration:underline}
 .pill{display:inline-block;background:#fff2cf;color:#b5791f;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:700}
</style></head><body>
<h1>🏝️ Catan Arena</h1><div class="sub">sweep over <b>__FIELD__</b> · __NGAMES__ games</div>
__BODY__
</body></html>"""


def _table(title, rows, cols):
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td class="n">{v}</td>' if i else f"<td>{v}</td>"
            for i, v in enumerate(r)) + "</tr>"
    return (f'<div class="card"><h2>{title}</h2>'
            f"<table><tr>{head}</tr>{body}</table></div>")


def render_index(sweep: dict, out_path: Path) -> Path:
    agg = sweep["aggregate"]
    field = sweep["field"]

    winners = "  ".join(f'<span class="pill">{k}: {v}</span>'
                        for k, v in agg["winners"].items())
    cards = f'<div class="card"><h2>Winners</h2>{winners}</div>'

    for group in ("by_intent", "by_model"):
        data = agg.get(group, {})
        if not data:
            continue
        rows = [[k, d["seat_games"], d["win_rate"], d["mean_vp"],
                 d["mean_accept_rate"] if d["mean_accept_rate"] is not None else "—",
                 d["robber_on_leader_rate"] if d["robber_on_leader_rate"] is not None else "—"]
                for k, d in sorted(data.items(), key=lambda kv: -kv[1]["win_rate"])]
        cards += _table(
            group.replace("_", " "),
            rows,
            [group.split("_")[1], "seat-games", "win rate", "mean VP",
             "trade accept", "robber→leader"])

    links = "".join(
        f'<div style="margin:3px 0"><a href="{Path(p).with_name(Path(p).stem + "_scene.html").name}">'
        f'▶ {Path(p).stem}</a></div>' for p in sweep["paths"])
    cards += f'<div class="card"><h2>Replays</h2>{links}</div>'

    # write a scene next to each json so the links resolve
    from .scene import render as render_scene
    for p in sweep["paths"]:
        jp = Path(p)
        try:
            render_scene(json.loads(jp.read_text()),
                         jp.with_name(jp.stem + "_scene.html"))
        except Exception:
            pass

    html = (_TPL.replace("__FIELD__", field)
            .replace("__NGAMES__", str(agg["n_games"]))
            .replace("__BODY__", cards))
    out_path.write_text(html)
    return out_path
