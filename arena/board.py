"""Standard Catan board generation with real topology.

The classic board is a radius-2 hexagon of 19 hexes laid out in rows of
3-4-5-4-3 (pointy-top hexes). From the hex centres we derive every corner
(vertex) and side (edge), de-duplicating the ones shared between hexes, which
yields the canonical **19 hexes · 54 vertices · 72 edges**. Coastal edges (those
touching only one hex) carry the trading ports.

Everything is plain, JSON-serialisable data with pixel coordinates baked in, so
the same structure feeds both the engine (adjacency, production) and the
spectator scene (drawing). Given a seed the resource + number shuffle is
deterministic.
"""
from __future__ import annotations

import math
import random

# --- resource economy (standard 3-4 Catan) ---------------------------------
RESOURCES = ("wood", "brick", "sheep", "wheat", "ore")
# 4 wood, 4 sheep, 4 wheat, 3 brick, 3 ore, 1 desert = 19 hexes
_RESOURCE_BAG = (["wood"] * 4 + ["sheep"] * 4 + ["wheat"] * 4
                 + ["brick"] * 3 + ["ore"] * 3 + ["desert"])
# the 18 number tokens dealt to the non-desert hexes (no 7)
_NUMBER_BAG = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]

# ports: 4 generic 3:1 and one 2:1 for each resource
_PORT_BAG = ["3:1", "3:1", "3:1", "3:1", "wood", "brick", "sheep", "wheat", "ore"]

HEX_ROWS = (3, 4, 5, 4, 3)
SIZE = 54.0               # hex centre -> corner, in px
_CENTER_X = 500.0
_TOP_Y = 150.0
_SNAP = 6.0               # px tolerance for merging shared corners


def _hex_centers() -> list[tuple[float, float]]:
    """Centres for the 3-4-5-4-3 pointy-top layout, top row first."""
    w = math.sqrt(3) * SIZE      # horizontal step between hexes in a row
    vstep = 1.5 * SIZE           # vertical step between rows
    out = []
    for r, count in enumerate(HEX_ROWS):
        cy = _TOP_Y + r * vstep
        cx0 = _CENTER_X - (count - 1) * w / 2
        for c in range(count):
            out.append((cx0 + c * w, cy))
    return out


def _corners(cx: float, cy: float) -> list[tuple[float, float]]:
    """Six corners of a pointy-top hex (first corner points straight up)."""
    pts = []
    for k in range(6):
        ang = math.radians(60 * k - 90)
        pts.append((cx + SIZE * math.cos(ang), cy + SIZE * math.sin(ang)))
    return pts


class _PointIndex:
    """Merge points that fall within _SNAP px into one id (shared corners)."""

    def __init__(self):
        self.pts: list[tuple[float, float]] = []

    def get(self, x: float, y: float) -> int:
        for i, (px, py) in enumerate(self.pts):
            if abs(px - x) <= _SNAP and abs(py - y) <= _SNAP:
                return i
        self.pts.append((x, y))
        return len(self.pts) - 1


def make_board(seed: int = 0) -> dict:
    rng = random.Random(seed)

    # 1) hexes with shuffled resources + numbers
    centers = _hex_centers()
    bag = _RESOURCE_BAG[:]
    rng.shuffle(bag)
    numbers = _NUMBER_BAG[:]
    rng.shuffle(numbers)
    hexes, robber = [], 0
    ni = 0
    for hid, (cx, cy) in enumerate(centers):
        res = bag[hid]
        if res == "desert":
            num = None
            robber = hid              # robber starts on the desert
        else:
            num = numbers[ni]
            ni += 1
        hexes.append({"id": hid, "cx": round(cx, 1), "cy": round(cy, 1),
                      "resource": res, "number": num})

    # 2) vertices + edges, de-duplicated across hexes
    vindex = _PointIndex()
    hex_corner_ids: list[list[int]] = []
    for cx, cy in centers:
        ids = [vindex.get(x, y) for x, y in _corners(cx, cy)]
        hex_corner_ids.append(ids)

    vertices = [{"id": i, "cx": round(x, 1), "cy": round(y, 1)}
                for i, (x, y) in enumerate(vindex.pts)]

    vertex_hexes: dict[int, list[int]] = {v["id"]: [] for v in vertices}
    vertex_adj: dict[int, set[int]] = {v["id"]: set() for v in vertices}
    edge_map: dict[tuple[int, int], int] = {}
    edges: list[dict] = []
    hex_edges: list[list[int]] = []

    def edge_id(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in edge_map:
            va, vb = vertices[key[0]], vertices[key[1]]
            edge_map[key] = len(edges)
            edges.append({"id": len(edges), "v": list(key),
                          "cx": round((va["cx"] + vb["cx"]) / 2, 1),
                          "cy": round((va["cy"] + vb["cy"]) / 2, 1),
                          "hexes": []})
        return edge_map[key]

    for hid, ids in enumerate(hex_corner_ids):
        eids = []
        for k in range(6):
            a, b = ids[k], ids[(k + 1) % 6]
            vertex_hexes[a].append(hid) if hid not in vertex_hexes[a] else None
            vertex_adj[a].add(b)
            vertex_adj[b].add(a)
            eid = edge_id(a, b)
            edges[eid]["hexes"].append(hid)
            eids.append(eid)
        hex_edges.append(eids)

    vertex_edges: dict[int, list[int]] = {v["id"]: [] for v in vertices}
    for e in edges:
        for v in e["v"]:
            vertex_edges[v].append(e["id"])

    # 3) ports on coastal edges (those touching exactly one hex), spread evenly
    coastal = [e for e in edges if len(e["hexes"]) == 1]
    coastal.sort(key=lambda e: math.atan2(e["cy"] - 330, e["cx"] - _CENTER_X))
    ports = []
    if coastal:
        pbag = _PORT_BAG[:]
        rng.shuffle(pbag)
        step = len(coastal) / len(pbag)
        for i, kind in enumerate(pbag):
            e = coastal[int(i * step)]
            ports.append({"edge": e["id"], "type": kind, "v": e["v"],
                          "cx": e["cx"], "cy": e["cy"]})

    return {
        "hexes": hexes,
        "vertices": vertices,
        "edges": [{"id": e["id"], "v": e["v"], "cx": e["cx"], "cy": e["cy"]}
                  for e in edges],
        "vertex_hexes": {k: sorted(v) for k, v in vertex_hexes.items()},
        "vertex_adj": {k: sorted(v) for k, v in vertex_adj.items()},
        "vertex_edges": vertex_edges,
        "edge_vertices": {e["id"]: e["v"] for e in edges},
        "ports": ports,
        "robber": robber,
    }


def pip_count(number: int | None) -> int:
    """Probability 'dots' under a number token (how many dice combos make it)."""
    return 0 if number is None else 6 - abs(7 - number)


if __name__ == "__main__":
    b = make_board(0)
    print(f"hexes={len(b['hexes'])} vertices={len(b['vertices'])} "
          f"edges={len(b['edges'])} ports={len(b['ports'])} robber@{b['robber']}")
