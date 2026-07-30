"""Build a static GitHub Pages site (``docs/``) from the saved games.

GitHub Pages serves static files only, so this publishes the *read-only* replay
experience — the gallery as ``index.html`` plus every scene replay (each carries
its game data inline). The interactive launcher (``serve.py``) stays local; to add
matches to the site, generate them locally (``run.py play`` / ``serve``), then
``python run.py site`` and commit ``docs/``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from viz.gallery import LOG_DIR, build_gallery
from viz.scene import render as render_scene

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def build_site(out: Path | None = None) -> tuple[Path, int]:
    out = out or DOCS
    out.mkdir(exist_ok=True)
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
    gallery = build_gallery()
    # the gallery's ▶ Replay links are bare "<stem>_scene.html" names, so putting
    # the gallery (as index.html) and the scenes side by side makes them resolve
    shutil.copy(gallery, out / "index.html")
    n = 0
    for sc in LOG_DIR.glob("*_scene.html"):
        shutil.copy(sc, out / sc.name)
        n += 1
    (out / ".nojekyll").write_text("")   # let Pages serve files verbatim (no Jekyll)
    return out, n


if __name__ == "__main__":
    d, n = build_site()
    print(f"built static site at {d} ({n} replays + index.html)")
