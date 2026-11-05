"""Build the static GitHub Pages demo: the playground page replaying recorded runs.

    python playground/build_static.py            # → _site/
    python -m http.server -d _site 8000           # preview at http://127.0.0.1:8000

Standard library only, so CI needs no dependencies. Record runs first with record.py.
"""
import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "playground"
SKIP = {".venv", ".git", "node_modules", "__pycache__", "_site"}


def repo_files(*suffixes):
    return sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                  if p.suffix in suffixes and p.is_file() and not SKIP & set(p.parts))


def frameworks():
    """Read NAME and MODES from each recipes/<name>/playground.py without importing it."""
    found = []
    for adapter in sorted((ROOT / "recipes").glob("*/playground.py")):
        src = adapter.read_text()
        name = re.search(r'^NAME\s*=\s*"([^"]+)"', src, re.M)
        modes = re.search(r'^MODES\s*=\s*\(([^)]*)\)', src, re.M)
        found.append({"key": adapter.parent.name, "name": name.group(1) if name else adapter.parent.name,
                      "modes": re.findall(r'"([^"]+)"', modes.group(1)) if modes else ["unguarded", "api", "mcp"]})
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="ProofAgent-ai/agent-guardrails-cookbook", help="owner/name on GitHub")
    ap.add_argument("--out", default=str(ROOT / "_site"))
    a = ap.parse_args()
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    (out / "data").mkdir(parents=True)

    recordings = {p.stem: json.loads(p.read_text()) for p in sorted((HERE / "recordings").glob("*.json"))}
    if not recordings:
        raise SystemExit("No recordings: run playground/record.py first.")
    fws = frameworks()
    ready = {f["key"] for f in fws}
    md, code = repo_files(".md"), repo_files(".py", ".jsonl", ".txt")
    site = {
        "frameworks": fws,
        "planned": sorted(p.name for p in (ROOT / "recipes").iterdir()
                          if p.is_dir() and p.name not in ready and not p.name.startswith(("_", "00-"))),
        "files": md, "code": code,
        "contents": {f: (ROOT / f).read_text() for f in md + code},
        "recordings": recordings,
        "scenarios": json.loads((HERE / "scenarios.json").read_text()),
        "codespaces": f"https://codespaces.new/{a.repo}?quickstart=1",
        "repo": f"https://github.com/{a.repo}",
    }
    (out / "data" / "site.json").write_text(json.dumps(site, ensure_ascii=False))

    page = (HERE / "index.html").read_text()
    page = page.replace('<html lang="en">', '<html lang="en" data-mode="static">', 1)
    page = page.replace("</title>", '</title>\n<script src="static-shim.js"></script>', 1)
    (out / "index.html").write_text(page)
    shutil.copy(HERE / "static-shim.js", out / "static-shim.js")
    (out / ".nojekyll").write_text("")
    kb = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) // 1024
    print(f"Built {out.relative_to(ROOT)}/ · {len(fws)} framework(s) · recordings: {', '.join(recordings)} · {kb} KB")


if __name__ == "__main__":
    main()
