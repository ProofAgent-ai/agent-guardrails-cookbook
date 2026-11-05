# Contributing

Thanks for helping make agents safer.

## Add a framework recipe

1. Copy the layout: `recipes/<framework>/` with `README.md`, `api/`, `mcp/` (if the framework supports MCP), `attack_demo.py`.
2. Use the `Guard` interface from `guards/python/guard.py` (or an equivalent for your language). Don't call a vendor directly in the recipe.
3. Guard all three checkpoints. Show the agent unguarded and guarded.
4. The demo must run with `GUARD=local` and no API keys, so anyone can try it.
5. Add `playground.py` so the local playground can run it (see [playground/README.md](playground/README.md)).
6. Add a row to the recipes table in the main README.

## Add attacks

Append lines to `attacks/corpus.jsonl`: `id`, `checkpoint`, `category`, `lang`, `text`, `expect` (`ALLOW`, `MASK`, `REVIEW`, `BLOCK`). Only synthetic data: no real people, cards or keys.

## Add a guard adapter

Subclass `Guard` in `guards/python/guard.py`, map its result to a `Decision`, fail closed on errors, and register it in `get_guard`.

## Security issues

Don't open a public issue for a vulnerability. Email security@proofagent.ai.
