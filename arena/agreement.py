"""Label agreement (2026-10-25): Cohen's kappa between labelers on a shared
task, and each labeler against the engine's verdict, computed in the console."""
from __future__ import annotations

import itertools
import json
from collections import Counter

LIE_VERDICTS = ("false claim", "promise broken", "plan broken", "promise or plan broken")


def cohen_kappa(a: list, b: list) -> float | None:
    """Unweighted kappa over two equally long label lists."""
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return 1.0
    return round((po - pe) / (1 - pe), 3)


def engine_label(verdict: str | None) -> str:
    """Collapse the engine's reading to the labeler's scale: lie / honest / unclear."""
    if not verdict:
        return "unclear"
    v = verdict.lower()
    if any(k in v for k in ("false claim", "broken")):
        return "lie"
    if any(k in v for k in ("true claim", "kept", "declined", "excused")):
        return "honest"
    return "unclear"


def task_agreement(con, task_items: list) -> dict:
    """task_items: [{"run_id", "event_idx"}]. Returns per-pair kappa, per-labeler
    agreement with the engine, coverage per labeler, and the confusion counts."""
    keys = [(it["run_id"], it["event_idx"]) for it in task_items]
    keyset = set(keys)
    by_labeler = {}
    engine = {}
    for r in con.execute("SELECT run_id, event_idx, labeler, label, context FROM labels"):
        k = (r["run_id"], r["event_idx"])
        if k not in keyset:
            continue
        by_labeler.setdefault(r["labeler"], {})[k] = r["label"]
        try:
            engine.setdefault(k, engine_label(json.loads(r["context"] or "{}").get("verdict")))
        except Exception:
            engine.setdefault(k, "unclear")
    out = {"items": len(keys), "labelers": {lab: len(d) for lab, d in by_labeler.items()}, "pairs": [], "vs_engine": {}}
    for la, lb in itertools.combinations(sorted(by_labeler), 2):
        common = sorted(set(by_labeler[la]) & set(by_labeler[lb]))
        if len(common) < 5:
            out["pairs"].append({"a": la, "b": lb, "n": len(common), "kappa": None, "note": "fewer than 5 shared items"})
            continue
        A = [by_labeler[la][k] for k in common]; B = [by_labeler[lb][k] for k in common]
        lie_a = ["lie" if x == "lie" else "not" for x in A]; lie_b = ["lie" if x == "lie" else "not" for x in B]
        conf = Counter(zip(A, B))
        out["pairs"].append({"a": la, "b": lb, "n": len(common), "kappa": cohen_kappa(A, B),
                             "kappa_lie_vs_not": cohen_kappa(lie_a, lie_b),
                             "agree": round(sum(1 for x, y in zip(A, B) if x == y) / len(common), 3),
                             "confusion": {f"{x}|{y}": n for (x, y), n in conf.items()}})
    for lab, d in by_labeler.items():
        ks = [k for k in d if k in engine]
        if not ks:
            continue
        H = ["lie" if d[k] == "lie" else "not" for k in ks]
        E = ["lie" if engine[k] == "lie" else "not" for k in ks]
        out["vs_engine"][lab] = {"n": len(ks), "kappa_lie_vs_not": cohen_kappa(H, E),
                                 "agree": round(sum(1 for x, y in zip(H, E) if x == y) / len(ks), 3)}
    return out
