"""Static SVG board snapshots for transcripts and the labeling view.

The log carries the board geometry (hex centres, vertex and edge coordinates,
ports, numbers) and every build / robber event, so the state at any point of a
game is a replay of those events. `state_at(log, upto)` replays them up to an
event index; `board_svg(board, state, colors)` draws hexes, numbers, ports,
the robber, settlements, cities and roads. Pure Python, no dependencies.
"""
from __future__ import annotations

import html
import math

RES_FILL = {"wood": "#4f8a4b", "brick": "#c2673a", "sheep": "#9fcf6b", "wheat": "#e2c04a",
            "ore": "#8d94a0", "desert": "#e8dcb8", None: "#e8dcb8"}
SIZE_GUESS = 54.0            # hex size when the board does not record it (see _hex_size)


def state_at(log: dict, upto: int | None = None) -> dict:
    """Replay builds and robber moves up to (not including) event index `upto`."""
    board = log.get("board") or {}
    st = {"vertex": {}, "edge": {}, "robber": board.get("robber")}
    events = log.get("events") or []
    end = len(events) if upto is None else max(0, min(upto, len(events)))
    for e in events[:end]:
        t = e.get("type")
        if t == "build":
            who = e.get("actor")
            if e.get("kind") in ("settlement", "city") and e.get("vertex") is not None:
                st["vertex"][int(e["vertex"])] = (who, e["kind"])
            elif e.get("kind") == "road" and e.get("edge") is not None:
                st["edge"][int(e["edge"])] = who
        elif t == "robber_move" and e.get("hex") is not None:
            st["robber"] = e["hex"]
    return st


def _hex_size(board: dict) -> float:
    hx = board.get("hexes") or []
    if len(hx) >= 2:
        a, b = hx[0], hx[1]
        d = math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])
        if d > 1:
            return d / math.sqrt(3)       # pointy-top: horizontal step = sqrt(3) * size
    return SIZE_GUESS


def board_svg(board: dict, state: dict, colors: dict, width: int = 360, title: str = "") -> str:
    hexes = board.get("hexes") or []
    verts = {v["id"]: v for v in board.get("vertices") or []}
    edges = {e["id"]: e for e in board.get("edges") or []}
    if not hexes or not verts:
        return ""
    size = _hex_size(board)
    xs = [h["cx"] for h in hexes]; ys = [h["cy"] for h in hexes]
    minx, maxx, miny, maxy = min(xs) - size * 1.3, max(xs) + size * 1.3, min(ys) - size * 1.3, max(ys) + size * 1.3
    w, h = maxx - minx, maxy - miny
    height = int(width * h / w)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx:.0f} {miny:.0f} {w:.0f} {h:.0f}" '
           f'width="{width}" height="{height}" style="background:#dfeaf2;border-radius:8px">']
    if title:
        out.append(f'<title>{html.escape(title)}</title>')
    for hx in hexes:
        pts = " ".join(f"{hx['cx'] + size * math.cos(math.radians(60 * k - 90)):.1f},"
                       f"{hx['cy'] + size * math.sin(math.radians(60 * k - 90)):.1f}" for k in range(6))
        out.append(f'<polygon points="{pts}" fill="{RES_FILL.get(hx.get("resource"))}" stroke="#f4efe4" stroke-width="2"/>')
        if hx.get("number"):
            red = hx["number"] in (6, 8)
            out.append(f'<circle cx="{hx["cx"]:.1f}" cy="{hx["cy"]:.1f}" r="{size * 0.3:.1f}" fill="#fbf6e8" stroke="#8a7f66"/>'
                       f'<text x="{hx["cx"]:.1f}" y="{hx["cy"] + size * 0.11:.1f}" text-anchor="middle" '
                       f'font-size="{size * 0.34:.0f}" font-family="sans-serif" font-weight="700" '
                       f'fill="{"#b3261e" if red else "#2b2b2b"}">{hx["number"]}</text>')
    for p in board.get("ports") or []:
        out.append(f'<text x="{p["cx"]:.1f}" y="{p["cy"]:.1f}" text-anchor="middle" font-size="{size * 0.22:.0f}" '
                   f'font-family="sans-serif" fill="#2f4858">{html.escape(str(p.get("type", "?")))[:5]} port</text>')
    for eid, who in (state.get("edge") or {}).items():
        e = edges.get(int(eid))
        if not e:
            continue
        a, b = verts.get(e["v"][0]), verts.get(e["v"][1])
        if a and b:
            out.append(f'<line x1="{a["cx"]:.1f}" y1="{a["cy"]:.1f}" x2="{b["cx"]:.1f}" y2="{b["cy"]:.1f}" '
                       f'stroke="{colors.get(who, "#333")}" stroke-width="{size * 0.16:.1f}" stroke-linecap="round"/>')
    for vid, (who, kind) in (state.get("vertex") or {}).items():
        v = verts.get(int(vid))
        if not v:
            continue
        c = colors.get(who, "#333")
        if kind == "city":
            r = size * 0.24
            out.append(f'<rect x="{v["cx"] - r:.1f}" y="{v["cy"] - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
                       f'fill="{c}" stroke="#fff" stroke-width="2" rx="3"><title>{html.escape(str(who))} city</title></rect>')
        else:
            out.append(f'<circle cx="{v["cx"]:.1f}" cy="{v["cy"]:.1f}" r="{size * 0.2:.1f}" fill="{c}" stroke="#fff" stroke-width="2">'
                       f'<title>{html.escape(str(who))} settlement</title></circle>')
    rob = state.get("robber")
    if rob is not None:
        hx = next((x for x in hexes if x["id"] == rob), None)
        if hx:
            out.append(f'<circle cx="{hx["cx"] - size * 0.42:.1f}" cy="{hx["cy"] - size * 0.42:.1f}" r="{size * 0.2:.1f}" '
                       f'fill="#1e1e1e" stroke="#fff" stroke-width="2"><title>robber</title></circle>')
    out.append("</svg>")
    return "".join(out)


def legend(colors: dict) -> str:
    return " ".join(f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{c};'
                    f'margin-right:3px"></span>{html.escape(str(n))}' for n, c in colors.items())
