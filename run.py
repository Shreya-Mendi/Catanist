"""CLI entry point for the Catan arena.

Examples:
    # one game from a config, then open the spectator scene
    python run.py play configs/demo.json --scene

    # sweep every player's intent across conditions and print aggregate metrics
    python run.py sweep configs/demo.json --field intent \\
        --values balanced diplomatic cutthroat deceptive greedy --reps 3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from arena.metrics import game_metrics
from arena.runner import load_env, run_one, run_sweep, save_result
from viz.gallery import build_gallery
from viz.index import render_index
from viz.scene import render as render_scene

load_env()          # pick up GITHUB_TOKEN etc. from Catanist/.env if present


def _load(path):
    return json.loads(Path(path).read_text())


def cmd_play(args):
    cfg = _load(args.config)
    try:
        result = run_one(cfg)
    except RuntimeError as e:              # e.g. missing GitHub Models token
        print(f"\n{e}")
        return
    path = save_result(result)
    print(f"winner: {result['winner']}  ({result['reason']})  ·  log: {path}")
    print("final VPs:", json.dumps(result["vps"]))
    if args.metrics:
        print(json.dumps(game_metrics(result), indent=2))
    # every run is saved as JSON (source of truth) + a scene replay
    html = render_scene(result, path.with_name(path.stem + "_scene.html"))
    print(f"scene:  {html}")
    gal = build_gallery()                 # refresh the persistent replay hub
    print(f"gallery: {gal}")


def cmd_gallery(args):
    gal = build_gallery()
    print(f"gallery: {gal}")


def cmd_serve(args):
    from serve import serve
    serve(port=args.port)


def cmd_site(args):
    from viz.site import build_site
    out, n = build_site()
    print(f"static Pages site: {out}  ({n} replays + index.html)")
    print("commit docs/ and enable GitHub Pages → Deploy from branch → main → /docs")


def cmd_sweep(args):
    cfg = _load(args.config)
    out = run_sweep(cfg, args.field, args.values, per_value=args.reps)
    print(json.dumps(out["aggregate"], indent=2))
    if args.viz:
        idx = render_index(out, Path("logs") / f"index_{args.field}.html")
        print(f"\nscenes: {len(out['paths'])} games · index: {idx}")
    gal = build_gallery()                 # swept games join the replay hub too
    print(f"gallery: {gal}")


def main():
    ap = argparse.ArgumentParser(description="LLM Catan arena")
    sub = ap.add_subparsers(required=True)

    p = sub.add_parser("play", help="run one game (saves JSON + scene replay + gallery)")
    p.add_argument("config")
    p.add_argument("--scene", action="store_true", help="(kept for compatibility; "
                   "a scene replay is always written)")
    p.add_argument("--metrics", action="store_true", help="print per-player metrics")
    p.set_defaults(func=cmd_play)

    g = sub.add_parser("gallery", help="rebuild logs/gallery.html from all saved games")
    g.set_defaults(func=cmd_gallery)

    sv = sub.add_parser("serve", help="launch the interactive web launcher")
    sv.add_argument("--port", type=int, default=8756)
    sv.set_defaults(func=cmd_serve)

    st = sub.add_parser("site", help="build the static GitHub Pages replay site (docs/)")
    st.set_defaults(func=cmd_site)

    s = sub.add_parser("sweep", help="vary one factor across conditions")
    s.add_argument("config")
    s.add_argument("--field", choices=["intent", "strategy", "n"], required=True)
    s.add_argument("--values", nargs="+", required=True)
    s.add_argument("--reps", type=int, default=1)
    s.add_argument("--viz", action="store_true",
                   help="render a scene per game plus a comparison index")
    s.set_defaults(func=cmd_sweep)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
