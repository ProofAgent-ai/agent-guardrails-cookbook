"""Record real playground runs for the static GitHub Pages demo.

Runs every scenario through every integration (unguarded, API, MCP) and saves the
traces to playground/recordings/<guard>.json. The Pages site replays these.

    python playground/record.py                                   # local rules + stub model
    PROOFAGENT_NANO_API_KEY=pa_nano_... python playground/record.py --guard nano \\
        --llm lmstudio --model gemma-4-e4b-it-mlx                 # live Nano + a local model

Keys are read from the environment and never written to the recordings.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", default="local", choices=["local", "nano"])
    ap.add_argument("--llm", default="stub", help="stub, lmstudio, ollama, openai, anthropic")
    ap.add_argument("--model", default=None)
    ap.add_argument("--framework", default=next(iter(server.FRAMEWORKS)))
    a = ap.parse_args()
    if a.guard == "nano" and not os.environ.get("PROOFAGENT_NANO_API_KEY"):
        sys.exit("Set PROOFAGENT_NANO_API_KEY to record with Nano.")

    cfg = {"guard": a.guard, "framework": a.framework,
           "nano_key": os.environ.get("PROOFAGENT_NANO_API_KEY"), "nano_url": os.environ.get("PROOFAGENT_NANO_URL"),
           "llm": {"provider": a.llm, "model": a.model, "api_key": os.environ.get("LLM_API_KEY")}}
    r = server.record_all(cfg)
    print(f"Saved {r['scenarios']} scenarios ({r['runs']} runs, {r['errors']} errors) → {r['file']}")


if __name__ == "__main__":
    main()
