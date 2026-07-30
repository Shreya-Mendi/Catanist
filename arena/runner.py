"""Build players from a config, run games (single or swept), and write logs.

A config is a dict:
{
  "name": "demo",
  "seed": 0,
  "scene": "harbor",
  "players": [
     {"name": "Merlin", "provider": "mock", "model": "openai/gpt-4o",
      "persona": "calm and analytical", "intent": "diplomatic",
      "costume": "wizard", "color": "#7c5cff"},
     ...
  ]
}

Sweeps reuse one config and vary a single field (every player's intent, or the
player count) so behaviour can be compared across conditions.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from .engine import Game
from .metrics import aggregate, game_metrics
from .player import PlayerAgent
from .providers import get_provider

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (without overriding
    anything already set). Lets the token live in Catanist/.env instead of the shell."""
    path = path or (ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _provider_cache():
    cache: dict[str, object] = {}

    def get(name, seed=None):
        key = f"{name}:{seed}" if name == "mock" else name
        if key not in cache:
            cache[key] = get_provider(name, seed=seed) if name == "mock" else get_provider(name)
        return cache[key]

    return get


def build_players(cfg: dict, provider_get) -> list[PlayerAgent]:
    players = []
    for i, spec in enumerate(cfg["players"]):
        prov = provider_get(spec["provider"], seed=cfg.get("seed", 0) + i)
        players.append(PlayerAgent(
            name=spec["name"], model=spec["model"],
            persona=spec.get("persona", "neutral"),
            intent=spec.get("intent", "balanced"),
            strategy=spec.get("strategy", "none"),
            costume=spec.get("costume", ""), color=spec.get("color", ""),
            provider=prov,
            rng=random.Random(cfg.get("seed", 0) + i),
        ))
    return players


def run_one(cfg: dict, provider_get=None) -> dict:
    provider_get = provider_get or _provider_cache()
    players = build_players(cfg, provider_get)
    game = Game(players, seed=cfg.get("seed", 0))
    result = game.run()
    result["config_name"] = cfg.get("name", "game")
    result["scene"] = cfg.get("scene", "harbor")   # viz theme
    return result


_SAVE_SEQ = 0


def save_result(result: dict, tag: str = "") -> Path:
    """Persist a game as JSON — the replayable source of truth. Filenames are
    made unique so games finishing in the same second never overwrite (matters
    for sweeps, which save many games per second)."""
    global _SAVE_SEQ
    LOG_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"{result.get('config_name','game')}_{tag}_{stamp}".strip("_")
    path = LOG_DIR / f"{base}.json"
    while path.exists():
        _SAVE_SEQ += 1
        path = LOG_DIR / f"{base}-{_SAVE_SEQ}.json"
    path.write_text(json.dumps(result, indent=2))
    return path


def run_sweep(base_cfg: dict, field: str, values: list, per_value: int = 1) -> dict:
    """Vary one field across conditions; returns aggregated metrics + saved paths.

    field == 'intent' -> set every player's intent to each value (model held fixed,
                         so intent is the only thing that varies between conditions)
    field == 'n'      -> repeat the roster to each size
    """
    provider_get = _provider_cache()
    all_metrics, paths = [], []
    for val in values:
        for rep in range(per_value):
            cfg = json.loads(json.dumps(base_cfg))
            cfg["seed"] = base_cfg.get("seed", 0) + rep
            if field == "intent":
                for p in cfg["players"]:
                    p["intent"] = val
            elif field == "strategy":
                for p in cfg["players"]:
                    p["strategy"] = val
            elif field == "n":
                base = base_cfg["players"]
                cfg["players"] = [dict(base[i % len(base)], name=f"P{i+1}")
                                  for i in range(int(val))]
            else:
                raise ValueError(f"unknown sweep field {field!r}")
            res = run_one(cfg, provider_get)
            paths.append(str(save_result(res, tag=f"{field}={val}_r{rep}")))
            all_metrics.append(game_metrics(res))
    return {"field": field, "values": values,
            "aggregate": aggregate(all_metrics), "paths": paths}
