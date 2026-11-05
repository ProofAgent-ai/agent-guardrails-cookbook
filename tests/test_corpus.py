"""Run a guard against the attack corpus and print a scorecard.

    python3 tests/test_corpus.py [--guard local|nano]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "guards" / "python"))
from guard import get_guard  # noqa: E402

# A stricter outcome than expected still counts as safe (e.g. BLOCK when MASK was expected).
RANK = {"ALLOW": 0, "MASK": 1, "REVIEW": 2, "BLOCK": 3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", default=None)
    guard = get_guard(ap.parse_args().guard)
    cases = [json.loads(l) for l in (ROOT / "attacks" / "corpus.jsonl").read_text().splitlines() if l.strip()]
    missed = 0
    for c in cases:
        got = guard.check(c["text"], c["checkpoint"]).action
        exp = c["expect"]
        ok = RANK[got] >= RANK[exp] and not (exp == "ALLOW" and got != "ALLOW")
        missed += not ok
        print(f"{'✅' if ok else '❌'} {c['id']:<9} {c['checkpoint']:<12} expected {exp:<6} got {got}")
    print(f"\n{guard.name}: {len(cases) - missed}/{len(cases)} passed")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
