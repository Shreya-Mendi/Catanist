"""Build a static GitHub Pages site (``docs/``) from the saved games.

GitHub Pages serves static files only, so this publishes the *read-only* replay
experience — the gallery as ``index.html`` plus every scene replay (each carries
its game data inline). The interactive launcher (``serve.py``) stays local; to add
matches to the site, generate them locally (``run.py play`` / ``serve``), then
``python run.py site`` and commit ``docs/``.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from viz.gallery import LOG_DIR, build_gallery
from viz.scene import render as render_scene

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _safe(name: str) -> str:
    """URL/Pages-safe filename. GitHub Pages' deploy step rejects names with
    characters like '=' (the sweep tags produce e.g. intent=balanced), so map
    anything outside [A-Za-z0-9._-] to a dash."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", name)


def build_site(out: Path | None = None) -> tuple[Path, int]:
    out = out or DOCS
    out.mkdir(exist_ok=True)
    # start clean so renamed/removed games don't leave stale files behind
    for old in list(out.glob("*_scene.html")) + [out / "index.html"]:
        old.unlink(missing_ok=True)
    # make sure every saved game has a rendered scene, then rebuild the gallery
    for jp in sorted(LOG_DIR.glob("*.json")):
        try:
            r = json.loads(jp.read_text())
            if "events" not in r:
                continue
            sc = jp.with_name(jp.stem + "_scene.html")
            if not sc.exists():
                render_scene(r, sc)
        except Exception:
            continue
    gallery_html = build_gallery().read_text()
    # copy scenes under Pages-safe names, rewriting the gallery's ▶ Replay links
    n = 0
    for sc in sorted(LOG_DIR.glob("*_scene.html")):
        safe = _safe(sc.name)
        shutil.copy(sc, out / safe)
        if safe != sc.name:
            gallery_html = gallery_html.replace(sc.name, safe)
        n += 1
    (out / "index.html").write_text(gallery_html)
    (out / ".nojekyll").write_text("")   # let Pages serve files verbatim (no Jekyll)
    return out, n


if __name__ == "__main__":
    d, n = build_site()
    print(f"built static site at {d} ({n} replays + index.html)")
