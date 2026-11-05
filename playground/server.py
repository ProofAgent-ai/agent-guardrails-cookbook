"""Local playground: run the real recipe graphs from a web page, with any LLM, and watch every checkpoint.

    python playground/server.py          # then open http://127.0.0.1:8765

It also previews the repo's Markdown the way GitHub shows it.
Binds to 127.0.0.1 only. Keys you type stay in the page and this process; nothing is stored.
"""
import importlib.util
import json
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "guards" / "python"))
sys.path.insert(0, str(ROOT / "shared"))

from guard import LocalGuard, NanoGuard  # noqa: E402
from mcp_client import LocalMCP, NanoMCP  # noqa: E402
from models import PROVIDERS, make_llm, naive  # noqa: E402


def discover_frameworks():
    """Every recipes/<name>/playground.py is a framework the playground can run."""
    found = {}
    for adapter in sorted((ROOT / "recipes").glob("*/playground.py")):
        key = adapter.parent.name
        try:
            spec = importlib.util.spec_from_file_location(f"pg_{key.replace('-', '_')}", adapter)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            found[key] = mod
        except Exception as e:  # noqa: BLE001  (a missing framework package shouldn't stop the others)
            print(f"  skipped {key}: {type(e).__name__}: {e}")
    return found


FRAMEWORKS = discover_frameworks()
PLANNED = sorted(p.name for p in (ROOT / "recipes").iterdir()
                 if p.is_dir() and p.name not in FRAMEWORKS and not p.name.startswith(("_", "00-")))

MCP_CHECKPOINT = {"check_user_message": "input", "check_tool_call": "tool_call",
                  "check_tool_result": "tool_result", "check_reply": "output"}


# --- Tracing wrappers: record every guard decision and model step --------------

def nano_detail(raw):
    """The parts of a Nano /v1/scan response worth showing: decision, recommendation, why, regulations."""
    if not isinstance(raw, dict) or "decision" not in raw:
        return None
    def finding(f):
        ex = f.get("explanation") or {}
        return {k: v for k, v in {
            "id": f.get("id"), "kind": f.get("kind"), "action": f.get("action"), "band": f.get("band"),
            "confidence": f.get("confidence"), "risk": f.get("id_risk"), "placeholder": f.get("placeholder"),
            "family": f.get("family"), "subfamily": f.get("subfamily"), "title": ex.get("title"),
            "what": ex.get("what"), "risk_family": ex.get("risk_family"), "what_to_do": ex.get("what_to_do"),
            "reason": f.get("reason")}.items() if v is not None}
    return {"decision": raw.get("decision"), "report": raw.get("report"), "messages": raw.get("messages"),
            "summary": raw.get("summary"), "findings": [finding(f) for f in raw.get("findings", [])],
            "regulations": [{k: r.get(k) for k in ("framework", "cite", "meaning", "findings")} for r in raw.get("regulations", [])],
            "obligations": raw.get("obligations"), "policy": raw.get("policy"),
            "request": {k: (raw.get("request") or {}).get(k) for k in ("id", "mode", "direction", "destination", "jurisdiction")},
            "nano": raw.get("nano"), "raw": raw}

class TraceGuard:
    def __init__(self, inner, events, via):
        self.inner, self.events, self.via, self.name = inner, events, via, inner.name

    def check(self, text, checkpoint="input"):
        t = time.time()
        d = self.inner.check(text, checkpoint)
        self.events.append({"type": "guard", "via": self.via, "checkpoint": checkpoint, "action": d.action,
                            "input": text, "output": d.text, "reasons": d.reasons,
                            "nano": nano_detail(d.raw), "ms": round((time.time() - t) * 1000)})
        return d


class TraceMCP:
    def __init__(self, inner, events, via):
        self.inner, self.events, self.via = inner, events, via

    def call(self, name, /, **arguments):
        t = time.time()
        r = self.inner.call(name, **arguments)
        text = (f"{arguments.get('tool')}({arguments.get('arguments')})" if name == "check_tool_call"
                else arguments.get("text") or arguments.get("result"))
        self.events.append({"type": "guard", "via": f"{self.via} · {name}", "checkpoint": MCP_CHECKPOINT[name],
                            "action": r.get("action"), "input": text,
                            "output": r.get("use_this") if isinstance(r.get("use_this"), str) else None,
                            "reasons": [r["reason"]] if r.get("reason") else [],
                            "nano": nano_detail(r.get("result")), "next_step": r.get("next_step"),
                            "nano_decision": r.get("nano_decision"), "ms": round((time.time() - t) * 1000)})
        return r


def traced_model(model, events, label):
    def call(turns):
        t = time.time()
        step = model(turns)
        out = f"{step['tool']}({json.dumps(step['args'])})" if "tool" in step else step["answer"]
        events.append({"type": "llm", "label": label, "tool_call": "tool" in step, "output": out,
                       "ms": round((time.time() - t) * 1000)})
        return step
    return call


def run_once(mode, message, cfg):
    events = []
    llm = cfg.get("llm") or {}
    provider = llm.get("provider", "stub")
    if provider == "stub":
        base_model, label = naive, "stub (obeys any instruction)"
    else:
        base_model = make_llm(provider, llm.get("model"), llm.get("api_key"), llm.get("base_url") or None)
        label = f"{provider} · {llm.get('model')}"
    model = traced_model(base_model, events, label)

    use_nano = cfg.get("guard") == "nano"
    key, url = cfg.get("nano_key") or None, cfg.get("nano_url") or None
    guard = TraceGuard(NanoGuard(api_key=key, url=url) if use_nano else LocalGuard(), events,
                       "Nano API /v1/scan" if use_nano else "local rules") if mode in ("api", "hybrid") else None
    mcp = TraceMCP(NanoMCP(url=url, api_key=key) if use_nano else LocalMCP(), events,
                   "Nano MCP" if use_nano else "local MCP stand-in") if mode in ("mcp", "hybrid") else None

    fw = FRAMEWORKS[cfg.get("framework") or next(iter(FRAMEWORKS))]
    t = time.time()
    out = fw.run(mode, message, guard, mcp, model)
    leaked = any("EMAIL SENT" in str(x["output"]) for x in out["tools"])
    tools = [{"type": "tool", **x} for x in out["tools"]]
    return {"mode": mode, "framework": fw.NAME, "answer": out["answer"], "events": _interleave(events, tools), "tools": out["tools"],
            "exfiltrated": leaked, "ms": round((time.time() - t) * 1000)}


def _interleave(events, tools):
    """Place each tool execution right after the model step that asked for it."""
    out, queue = [], list(tools)
    for e in events:
        out.append(e)
        if e["type"] == "guard" and e["checkpoint"] == "tool_call" and e["action"] in ("ALLOW", "MASK", "ALLOW_MASKED") and queue:
            out.append(queue.pop(0))
    if queue:  # unguarded runs have no tool_call guard: attach after the model step
        merged, q = [], list(queue)
        for e in out:
            merged.append(e)
            if e["type"] == "llm" and e["tool_call"] and q:
                merged.append(q.pop(0))
        out = merged + q
    return out


def list_models(provider, base_url=None, api_key=None):
    if provider == "anthropic":
        return ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    base = (base_url or PROVIDERS[provider]).rstrip("/")
    req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    with urllib.request.urlopen(req, timeout=5) as r:
        return sorted(m["id"] for m in json.load(r).get("data", []))


SCENARIOS_FILE = ROOT / "playground" / "scenarios.json"


def scenarios():
    return json.loads(SCENARIOS_FILE.read_text())


def record_all(cfg, log=print):
    """Run every scenario through every integration and save playground/recordings/<guard>.json.
    The key in cfg is used for the calls and never written to the file."""
    fw = FRAMEWORKS[cfg.get("framework") or next(iter(FRAMEWORKS))]
    runs, errors = [], 0
    for sc in scenarios():
        results = []
        for mode in fw.MODES:
            try:
                results.append(run_once(mode, sc["message"], cfg))
            except Exception as e:  # noqa: BLE001
                results.append({"mode": mode, "error": f"{type(e).__name__}: {e}"}); errors += 1
            log(f"  [record] {mode:<9} {sc['id']:<10} {'ERROR ' + results[-1]['error'] if results[-1].get('error') else 'ok'}")
        runs.append({"message": sc["message"], "results": results})
    llm = cfg.get("llm") or {}
    guard = cfg.get("guard") or "local"
    meta = {"guard": guard, "framework": fw.NAME, "recorded": time.strftime("%Y-%m-%d"),
            "llm": "stub" if llm.get("provider", "stub") == "stub" else f"{llm.get('provider')} · {llm.get('model')}"}
    out = ROOT / "playground" / "recordings" / f"{guard}.json"
    out.parent.mkdir(exist_ok=True)
    text = json.dumps({"meta": meta, "runs": runs}, ensure_ascii=False, indent=1)
    if cfg.get("nano_key") and cfg["nano_key"] in text:   # belt and braces: a key must never reach a recording
        raise RuntimeError("refusing to save: the API key appeared in the recording")
    out.write_text(text)
    return {"file": str(out.relative_to(ROOT)), "scenarios": len(runs), "runs": len(runs) * len(fw.MODES),
            "errors": errors, "meta": meta}


def _timed(fn):
    t = time.time()
    try:
        return {"ok": True, **fn(), "ms": round((time.time() - t) * 1000)}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        return {"ok": False, "error": f"HTTP {e.code}: {detail}", "ms": round((time.time() - t) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round((time.time() - t) * 1000)}


def test_nano(key, url):
    """Three checks that spend no scan calls: service up, key valid (with quota), MCP reachable."""
    base = (url or "https://nano.proofagent.ai").rstrip("/")
    auth = {"Authorization": f"Bearer {key}"}

    def get(path, headers=None):
        with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers or {}), timeout=10) as r:
            return json.load(r)

    def service():
        r = get("/readyz")
        return {"detail": f"{r.get('status')} · runtime {r.get('runtime') or 'n/a'}"}

    def api_key():
        u = get("/v1/usage", auth)
        left = "unlimited" if u.get("calls_remaining") is None else f"{u['calls_remaining']:,} of {u['monthly_calls']:,}"
        return {"detail": f"plan {u.get('plan')} · {left} calls left this month", "usage": u}

    def mcp():
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        req = urllib.request.Request(base + "/mcp", data=body, method="POST", headers={
            **auth, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=10) as r:
            tools = [t["name"] for t in json.load(r).get("result", {}).get("tools", [])]
        return {"detail": f"{len(tools)} tools: {', '.join(tools)}"}

    checks = [("Service", service), ("API key · /v1/usage", api_key), ("MCP · /mcp", mcp)]
    return {"checks": [{"name": n, **_timed(f)} for n, f in checks]}


def test_llm(llm):
    """One real call with the agent's prompt: does the model answer, and does it follow the JSON tool protocol?"""
    provider = llm.get("provider", "stub")
    if provider == "stub":
        return {"checks": [{"name": "Stub model", "ok": True, "detail": "built in, no connection needed", "ms": 0}]}
    model = make_llm(provider, llm.get("model"), llm.get("api_key"), llm.get("base_url") or None)

    def answer():
        step = model([{"role": "user", "content": "Hi! Reply with a short greeting."}])
        return {"detail": f"replied: {str(step.get('answer') or step)[:120]}"}

    def tool_protocol():
        step = model([{"role": "user", "content": "How long does shipping take?"}])
        if "tool" in step:
            return {"detail": f"called {step['tool']}({json.dumps(step['args'])})"}
        return {"ok": False, "detail": "answered without calling fetch_help_page; tool use may be unreliable with this model",
                "warn": True}

    checks = [("Model answers", answer), ("Tool calling (JSON protocol)", tool_protocol)]
    out = []
    for n, f in checks:
        r = _timed(f)
        if r.get("warn"):
            r["ok"] = None
        out.append({"name": n, **r})
    return {"checks": out}


def repo_files(*suffixes):
    skip = {".venv", ".git", "node_modules", "__pycache__"}
    return sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                  if p.suffix in suffixes and p.is_file() and not skip & set(p.parts))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  " + fmt % args + "\n")

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (Path(__file__).parent / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/scenarios":
                return self._send(200, {"scenarios": scenarios()})
            if u.path == "/api/frameworks":
                return self._send(200, {"frameworks": [{"key": k, "name": m.NAME, "modes": list(m.MODES)}
                                                       for k, m in FRAMEWORKS.items()], "planned": PLANNED})
            if u.path == "/api/models":
                return self._send(200, {"models": list_models(q.get("provider", "lmstudio"), q.get("base_url"))})
            if u.path == "/api/files":
                return self._send(200, {"files": repo_files(".md"), "code": repo_files(".py", ".jsonl", ".txt")})
            if u.path == "/api/file":
                p = (ROOT / q.get("path", "README.md")).resolve()
                if ROOT not in p.parents or p.suffix != ".md":
                    return self._send(403, {"error": "not allowed"})
                return self._send(200, {"path": q.get("path"), "content": p.read_text()})
            if u.path == "/api/source":
                p = (ROOT / q.get("path", "")).resolve()
                if ROOT not in p.parents or p.suffix not in (".py", ".jsonl", ".json", ".txt") or ".venv" in p.parts:
                    return self._send(403, {"error": "not allowed"})
                return self._send(200, {"path": q.get("path"), "content": p.read_text()})
            self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/run", "/api/test/nano", "/api/test/llm", "/api/record"):
            return self._send(404, {"error": "not found"})
        try:
            cfg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            if path == "/api/test/nano":
                r = test_nano(cfg.get("nano_key"), cfg.get("nano_url"))
                for c in r["checks"]:  # results only, never the key
                    print(f"  [nano test] {'OK ' if c['ok'] else 'ERR'} {c['name']}: {c.get('detail') or c.get('error')}", flush=True)
                return self._send(200, r)
            if path == "/api/test/llm":
                return self._send(200, test_llm(cfg.get("llm") or {}))
            if path == "/api/record":
                r = record_all(cfg, log=lambda m: print(m, flush=True))
                built = subprocess.run([sys.executable, str(ROOT / "playground" / "build_static.py")],
                                       capture_output=True, text=True)
                r["build"] = (built.stdout or built.stderr).strip().splitlines()[-1:] or [""]
                print(f"  [record] saved {r['file']} · {r['runs']} runs · {r['errors']} errors · {r['build'][0]}", flush=True)
                return self._send(200, r)
            fw = FRAMEWORKS[cfg.get("framework") or next(iter(FRAMEWORKS))]
            modes = list(fw.MODES) if cfg.get("mode") == "compare" else [cfg.get("mode", "api")]
            results = []
            for mode in modes:
                try:
                    results.append(run_once(mode, cfg["message"], cfg))
                except Exception as e:  # noqa: BLE001
                    results.append({"mode": mode, "error": f"{type(e).__name__}: {e}"})
                    traceback.print_exc()
            for r in results:  # outcome summary for the terminal; the message and key are not logged
                acts = [f"{e['checkpoint']}={e['action']}" for e in r.get("events", []) if e["type"] == "guard"]
                print(f"  [run] {r['mode']:<9} guard={cfg.get('guard')} llm={(cfg.get('llm') or {}).get('provider')} "
                      f"{'ERROR ' + r['error'] if r.get('error') else ('DATA SENT OUT' if r.get('exfiltrated') else 'safe')} "
                      f"{' '.join(acts)}", flush=True)
            self._send(200, {"results": results})
        except Exception as e:  # noqa: BLE001
            self._send(400, {"error": str(e)})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Agent Guardrails Playground → http://127.0.0.1:{port}  ·  frameworks: {', '.join(m.NAME for m in FRAMEWORKS.values())}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
