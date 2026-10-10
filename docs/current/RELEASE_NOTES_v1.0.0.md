# Arbiter Arena v1.0.0

> Draft for the GitHub release page. Fill in the two links, then paste it in.

The first release of Arbiter Arena: a deterministic evaluation harness for tool-using
LLM agents, built on an SRD 5.1-compatible tactical combat engine. It ships with one
pre-registered study and the complete data behind it.

## The study

**How does the shape of an agent's action interface affect its reliability, cost and
tactics?** Three models played four tactical scenarios over ten paired seeds, under
four conditions. Only the way the model expresses its action changed: free text (C1),
raw tool calls (C2), tool calls with the legal options shown (C2+M), and choosing from
the list of legal options (C3).

First-attempt action validity:

| Model | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Nemotron 3.5 Lightning | 0.33 | 0.58 | 0.85 | 1.00 |
| Gemini 3.8 Flash | 0.99 | 0.99 | 1.00 | 1.00 |
| Claude Sonnet 5.5 | 0.98 | 0.89 | 0.98 | 1.00 |

- For the small model, the interface decides the result: it wins 13 of 40 matches in
  C1 and 25 of 40 in C3.
- Sonnet is the exception to the predicted ordering. It is worse with bare tool calls
  than with free text, and simply showing it the legal options restores it.
- Choosing from the menu all but ended friendly fire with area spells: no allies
  caught by Gemini or Sonnet, and 2 in 15 casts by Nemotron.

The write-up: **[TODO: article link]**

## What's in this release

- **The harness.** Four interface conditions over one observation contract, typed
  rejection codes, a resumable study runner, and replay verification of every match.
  A browser viewer shows each decision beside the board.
- **The study.** The pre-registration was frozen at the `study-freeze` tag before the
  final run. 600 matches, no exclusions, and every match replays exactly.
- **The data** (release asset `arbiter-arena-study-1.0.0.zip`): every transcript, the
  report and its CSVs, the blind parser audit, each condition's exact prompt, and both
  versions of the pre-registration, with checksums.

## Check it yourself

```bash
pip install -e ".[web,dev]"
python -m src.arena.study run examples/study/demo.toml --out results/demo   # no API key
# unzip the data asset into the repository root, then:
python -m src.arena.study verify results/final   # 600/600 must replay
python -m src.arena.study report results/final   # rebuilds the report byte for byte
```

See [CHANGELOG.md](../../CHANGELOG.md) for the full list of changes. Licensed under
Apache-2.0; SRD 5.1 attribution is in `NOTICE`.
