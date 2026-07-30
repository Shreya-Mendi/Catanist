# 🏝️ Catan Arena

An instrumented arena where LLM players compete at **Settlers of Catan** — the
sister project to the Mafia Arena. Different models (via GitHub Models) sit around
one board, each primed with a controlled **intent** (diplomatic, cutthroat,
deceptive, greedy, …), and you **spectate the match** in a cute illustrated replay
to see who reaches 10 victory points first.

Catan's social layer is *trade and blocking*, so on every decision each player
emits a **private reasoning trace** and a **public statement** — you can see (and
measure) when what a model tells the table diverges from what it privately plans.

## Quick start (no API keys needed)

Runs offline on the `mock` provider — the whole pipeline works before you spend a cent.

```bash
cd Catanist
python run.py play configs/demo.json      # one game -> JSON + HTML replay + gallery
open logs/gallery.html                     # browse & replay every match
```

Each `play` prints the winner and writes three things to `logs/`:

| file | what |
|---|---|
| `<game>.json` | the full event log — **the replayable source of truth** |
| `<game>_scene.html` | the illustrated spectator replay of that game |
| `gallery.html` | a persistent hub of **every** match, newest first, with ▶ Replay links |

## Interactive launcher (recommended)

One page to **replay any previous match** or **start a new one with your own cast** —
pick each seat's model, persona and personality/intent, hit Start, and watch the
replay when it finishes.

```bash
python run.py serve            # then open http://localhost:8756
```

- **Previous matches** — every saved game with its cast, winner and a ▶ Replay link.
- **New match** — add/remove seats; set each player's provider (`github`/`mock`),
  **model** (the full live GitHub Models catalogue from `assets/models_catalog.json`,
  or type any `publisher/model` id), a free-text **persona**, and a
  **personality/intent** (any of the 12 presets *or* a custom trait like
  `chaotic-gremlin`), plus costume, colour, scene and seed. Games run server-side
  with a live status and a "▶ Watch replay" link on completion.

The server reads `GITHUB_TOKEN` from its environment or `Catanist/.env`, so real
GitHub Models work as long as that token is present.

## Play across models (GitHub Models)

[GitHub Models](https://github.com/marketplace/models) is an OpenAI-compatible
endpoint with a free tier — one token gets you GPT-4o, Llama, DeepSeek, Mistral,
Phi, etc., perfect for a mixed table.

1. Create a GitHub Personal Access Token with the **`models:read`** permission.
2. Enable it — either export it, or drop it in `Catanist/.env` (git-ignored,
   auto-loaded by every command incl. the launcher):
   ```bash
   pip install openai
   export GITHUB_TOKEN=github_pat_...          # or:  cp .env.example .env  &&  edit
   ```
3. Run the cross-model config — six model families, six different intents:
   ```bash
   python run.py play configs/models.json
   open logs/gallery.html
   ```

Model ids are namespaced — `openai/gpt-4o`, `meta/Llama-3.3-70B-Instruct`,
`deepseek/DeepSeek-V3-0324`, `mistral-ai/Mistral-Large-2411`. The catalogue
shifts; check the marketplace and edit each player's `model` field to match
what's live. Any player can be set to `"provider": "mock"` to fill a seat with no
key. The GitHub backend retries with backoff on rate-limits, and any call that
still fails degrades to a safe legal move — so a game always finishes and saves.

> A full LLM game is call-heavy (many decisions per turn). On the free tier expect
> it to take a while and occasionally hit rate limits; it will keep going and the
> result is saved to `logs/` either way, so you can always replay it later.

## Watching a match

The scene is a live **Catan board** ringed by costumed characters (à la
messenger.abeto.co). Roads, settlements and cities pop up in each player's colour
as they are built; the robber slinks between hexes; trade offers arc between seats
(green = proposal, orange = executed swap); a victory-point leaderboard tracks the
race to 10. Controls: **Step / Play**, a speed slider, **📜 Log** (the chronicle),
and **peek at thoughts 💭** — which reveals every model's private reasoning next to
what it says out loud.

Re-render a replay from any saved log at any time:

```bash
python -m viz.scene logs/<game>.json      # writes <game>_scene.html
python run.py gallery                      # rebuild the replay hub from all logs
```

## Publish replays to GitHub Pages

The replays are static, self-contained HTML, so the **read-only replay site** (the
gallery + every scene) deploys to GitHub Pages. The interactive launcher stays
local (Pages can't run the Python server — and the token must never be committed).

```bash
python run.py site      # builds docs/ : index.html (gallery) + *_scene.html + .nojekyll
```

Commit `docs/`, push, then in the repo: **Settings → Pages → Deploy from a branch →
`main` / `/docs`**. Regenerate games locally, re-run `python run.py site`, and commit
`docs/` to update the published site.

## Detailed thinking (the private trace)

On every decision each player emits a **detailed, step-by-step `private_reasoning`
trace** — it reads the board and dice, takes stock of its resources and next build,
weighs the real options, accounts for opponents, and commits to a move in character
(`arena/player.py`). Toggle **peek at thoughts 💭** in the replay to read it beside
the one-line public statement — that gap is the whole point (a `deceptive` seat's
public line rarely matches its plan). The offline `mock` fills the same trace with a
state-aware template, so the thinking is populated even with no key.

## Intents — the controlled knob

Set per player via `"intent"` (`arena/intents.py`). Each is a rich priming block
spelling out how the disposition shapes **trading, the robber, blocking, and table
talk**. Twelve are built in — and any **custom** trait works too (a free-text intent
like `chaotic-gremlin` is honoured, not ignored):

| intent | plays like | | intent | plays like |
|---|---|---|---|---|
| `balanced` | steady, textbook value | | `aggressive` | constant pressure, races Largest Army |
| `diplomatic` | fair trades, keeps its word | | `cautious` | low-variance, punishes mistakes |
| `cutthroat` | denies the leader, robs the front-runner | | `opportunist` | no fixed plan, pounces on openings |
| `deceptive` | words needn't match the plan | | `vengeful` | targets whoever wronged it |
| `greedy` | hoards ore/wheat, refuses most trades | | `generous` | keeps the economy flowing, wins on volume |
| `builder` | races road & board presence | | `isolationist` | banks/ports only, out-builds the table |

## Strategy priming — a game-theory arm

An optional second knob (`arena/strategy.py`), set per player via `"strategy"`,
mirrors the Mafia arena's experimental design:

| arm | prompt block |
|---|---|
| `none` | baseline — no strategy text (the control) |
| `placebo` | length-matched Catan history trivia, zero strategy content |
| `taught` | explicit Catan theory: pip-probability, diversification, ports, trade EV, deny-the-leader, Longest-Road/Largest-Army tempo |

The **placebo is what makes it an experiment**: it isolates "the theory helped" from
"we added ~1.5k tokens telling it to try hard" (the blocks are length-matched,
taught/placebo ≈ 1.15).

## Sweeps

Vary one factor across conditions, model held fixed so the knob is the only thing
that moves:

```bash
python run.py sweep configs/demo.json --field intent \
    --values balanced diplomatic cutthroat deceptive greedy --reps 3 --viz
python run.py sweep configs/demo.json --field strategy --values none placebo taught --reps 4
open logs/index_intent.html
```

Sweeps report `by_intent`, `by_strategy` and `by_model` roll-ups — win rate, mean VP,
mean trade **accept rate**, and how often each condition aims the **robber at the
current leader** (a blocking signal). `--field n` instead varies the table size.

## What to measure

- **Promise faithfulness**: does a player accept the trades it talks up, or aim the
  robber at a partner it claimed to trust? Deceptive/cutthroat should diverge.
- **Intent effect**: does telling a model to be "cutthroat" vs "diplomatic" actually
  change its trading and blocking, or does it revert to a default settler?
- **Who wins**: win rate and mean VP by model and by intent.

## Layout

| Path | What |
|---|---|
| `arena/board.py` | standard 19-hex board — real vertex/edge topology + ports |
| `arena/engine.py` | Catan state machine → flat event log (source of truth) |
| `arena/player.py` | seat = model + persona + intent + strategy; detailed-reasoning prompt |
| `arena/intents.py` | the 12 intent priming blocks (the controlled knob) |
| `arena/strategy.py` | game-theory priming arm (none / placebo / taught) |
| `arena/providers.py` | multi-provider adapters + offline `mock` |
| `arena/runner.py` | build players from config, run games/sweeps, save logs |
| `arena/metrics.py` | win/VP tallies, trade accept rate, robber-on-leader rate |
| `viz/scene.py` | illustrated spectator replay (board + characters + thoughts) |
| `viz/gallery.py` | persistent replay hub of every saved game |
| `viz/index.py` | sweep comparison index |
| `serve.py` | interactive web launcher (replay past runs / start custom ones) |
| `configs/` | `demo.json` (mock) · `models4.json` · `models.json` (GitHub Models) |
| `logs/` | per-game JSON + rendered replays + `gallery.html` |

## Other backends

```bash
export OPENAI_API_KEY=...      # provider: openai
export ANTHROPIC_API_KEY=...   # provider: anthropic
export GOOGLE_API_KEY=...      # provider: google
```

Add a backend by dropping a `Provider` subclass into `arena/providers.py` and
registering it in `_REGISTRY`.

## Notes on the rules modelled

Full base-game Catan: dice production, the robber (with a 7 forcing discards),
road/settlement/city building with the distance rule, 4:1 bank trades plus 3:1 and
2:1 ports, player-to-player trading, the development deck (knight, victory point,
road building, year of plenty, monopoly), Longest Road (≥5) and Largest Army (≥3),
and the race to 10 VP. Simplifications for tractability: discards on a 7 are
resolved automatically, and free roads from Road Building are auto-placed. If no
one reaches 10 within the turn budget, the current VP leader is declared the winner.
