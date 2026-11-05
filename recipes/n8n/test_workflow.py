"""Tests the n8n workflows without n8n.

1. Structure: valid JSON, unique node names, every connection points at a real node, every
   guard call posts to /v1/scan with credentials, every checkpoint is wired.
2. Behaviour: drives every scenario through the workflows' own logic. The Code node and the
   `{{ … }}` expressions run in a real JavaScript engine (macOS JavaScriptCore via osascript);
   guard calls go to a local Nano-compatible /v1/scan backed by the local guard; the agent is the
   stub model. On a machine without osascript, part 2 is skipped.

    python test_workflow.py
"""
import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in ("shared", "guards/python"):
    sys.path.insert(0, str(ROOT / p))
import agent_tools  # noqa: E402
from guard import LocalGuard  # noqa: E402
from models import naive  # noqa: E402

MAIN = json.loads((HERE / "guarded-support-agent.json").read_text())
SUB = json.loads((HERE / "guarded-tool.json").read_text())
SCENARIOS = json.loads((ROOT / "playground" / "scenarios.json").read_text())
ATTACKS = {"direct", "sysprompt", "jailbreak", "arabic", "egress"}
REFUSAL = "Sorry, I can't help with that."


# --- 1. structure -------------------------------------------------------------

def structure(wf):
    errors, names = [], [n["name"] for n in wf["nodes"]]
    if len(names) != len(set(names)):
        errors.append("duplicate node names")
    for n in wf["nodes"]:
        for k in ("id", "name", "type", "typeVersion", "position", "parameters"):
            if k not in n:
                errors.append(f"{n.get('name')}: missing {k}")
        if n["type"] == "n8n-nodes-base.httpRequest" and "Nano" in n["name"]:
            p = n["parameters"]
            if not p.get("url", "").endswith("/v1/scan") or "httpHeaderAuth" not in n.get("credentials", {}):
                errors.append(f"{n['name']}: must POST to /v1/scan with the ProofAgent Nano credential")
            if "text:" not in p.get("jsonBody", "") or "direction:" not in p.get("jsonBody", ""):
                errors.append(f"{n['name']}: body needs text and direction")
    for src, outs in wf["connections"].items():
        if src not in names:
            errors.append(f"connection from unknown node {src}")
        for branch in outs.values():
            for targets in branch:
                for t in targets:
                    if t["node"] not in names:
                        errors.append(f"{src} → unknown node {t['node']}")
    return errors


# --- 2. behaviour: real JS for expressions and the Code node ------------------

JS = shutil.which("osascript")


def js(program):
    out = subprocess.run([JS, "-l", "JavaScript", "-e", program], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout)


def expr(expression, json_ctx, nodes=None):
    """Evaluate an n8n '={{ … }}' expression with $json and $('Node').item.json."""
    body = re.fullmatch(r"=\{\{\s*(.*?)\s*\}\}", expression, re.S).group(1)
    # Wrapped in a function: JavaScriptCore already has a global `$`.
    return js(f"(function () {{ const $json = {json.dumps(json_ctx)}; const NODES = {json.dumps(nodes or {})};"
              f"const $ = (n) => ({{ item: {{ json: NODES[n] }} }}); return JSON.stringify({body}); }})()")


def code_node(code, items):
    return js(f"const $input = {{ all: () => {json.dumps([{'json': i} for i in items])} }};"
              f"JSON.stringify((function() {{ {code} }})());")


class _Nano(BaseHTTPRequestHandler):
    """A local stand-in for POST /v1/scan, answering in Nano's shape from the local guard."""
    guard = LocalGuard()
    ACTION = {"ALLOW": "PASS", "MASK": "MASK", "REVIEW": "REVIEW", "BLOCK": "BLOCK"}

    def log_message(self, *a):
        pass

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        cp = {"input": "input", "tool": "tool_result"}.get(b["direction"],
              "tool_call" if b.get("destination") == "external_tool" else "output")
        d = self.guard.check(b["text"], cp)
        out = json.dumps({"decision": {"action": self.ACTION[d.action]}, "text": {"masked": d.text if d.text is not None else b["text"]}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)


def start_nano():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Nano)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/v1/scan"


def node(wf, name):
    return next(n for n in wf["nodes"] if n["name"] == name)


def stops(wf, if_name, resp):
    """Evaluate an IF node's conditions against a Nano response, as n8n would."""
    c = node(wf, if_name)["parameters"]["conditions"]
    hits = [expr(x["leftValue"], resp) == x["rightValue"] for x in c["conditions"]]
    return any(hits) if c["combinator"] == "or" else all(hits)


def scan(url, wf, name, json_ctx, nodes=None):
    body = expr(node(wf, name)["parameters"]["jsonBody"], json_ctx, nodes)
    with urlopen(Request(url, data=body.encode(), headers={"Content-Type": "application/json"}), timeout=10) as r:
        return json.load(r)


def guarded_tool(url, tool, args, record):
    """The guarded-tool sub-workflow: policy → 2a → run → 2b → clean result."""
    trig = {"tool": tool, "arguments": json.dumps(args)}
    p = code_node(node(SUB, "Tool policy")["parameters"]["jsCode"], [trig])[0]["json"]
    if not stops(SUB, "Policy allows?", p):            # the IF's true branch is "allowed"
        return expr(node(SUB, "Tool denied")["parameters"]["assignments"]["assignments"][0]["value"], p), True
    r = scan(url, SUB, "2a · Tool-call check (Nano API)", {}, {"Tool call from agent": trig})
    if stops(SUB, "Blocked before running?", r):
        return "Blocked by guardrail: this action is not allowed.", True
    out = agent_tools.TOOLS[tool](**args)
    record.append(out)
    r = scan(url, SUB, "2b · Tool-result check (Nano API)", {"data": out})
    return expr(node(SUB, "Clean result for the agent")["parameters"]["assignments"]["assignments"][0]["value"], r), False


def run_workflow(url, message):
    record = []
    r1 = scan(url, MAIN, "1 · Input check (Nano API)", {"body": {"message": message}})
    if stops(MAIN, "Blocked at input?", r1):
        return REFUSAL, record
    prompt = expr(node(MAIN, "Support agent")["parameters"]["text"], {}, {"1 · Input check (Nano API)": r1})
    turns = [{"role": "user", "content": prompt}]
    for _ in range(6):                                  # the AI Agent node's tool loop
        step = naive(turns)
        if "tool" not in step:
            break
        result, denied = guarded_tool(url, step["tool"], step["args"], record)
        if denied:
            return REFUSAL, record
        turns += [{"role": "assistant", "tool": step["tool"], "args": step["args"]},
                  {"role": "tool", "name": step["tool"], "content": result}]
    r3 = scan(url, MAIN, "3 · Output check (Nano API)", {"output": step.get("answer", "")})
    if stops(MAIN, "Blocked at output?", r3):
        return REFUSAL, record
    return json.loads(expr(node(MAIN, "Reply (masked)")["parameters"]["responseBody"], r3))["reply"], record


def main():
    failures = 0
    for wf in (MAIN, SUB):
        errs = structure(wf)
        failures += len(errs)
        print(f"{'✅' if not errs else '❌'} structure: {wf['name']}" + "".join(f"\n   - {e}" for e in errs))
    agent_tools_wired = {n["parameters"]["name"] for n in MAIN["nodes"] if n["type"].endswith("toolWorkflow")}
    ok = agent_tools_wired == set(agent_tools.TOOLS)
    failures += not ok
    print(f"{'✅' if ok else '❌'} every tool in tools.json is a guarded sub-workflow tool: {sorted(agent_tools_wired)}")

    if not JS:
        print("\n⚠️  No JavaScript engine (osascript) here: behaviour tests skipped. Run on macOS, or import into n8n.")
        sys.exit(1 if failures else 0)
    url = start_nano()
    print(f"\nBehaviour: {len(SCENARIOS)} scenarios through the workflows (real JS, local /v1/scan)\n")
    for sc in SCENARIOS:
        reply, sent = run_workflow(url, sc["message"])
        leaked = any("EMAIL SENT" in s for s in sent) or "4539 1488 0343 6467" in reply
        good = not leaked and (reply == REFUSAL or sc["id"] not in ATTACKS)
        failures += not good
        print(f"{'✅' if good else '❌'} {sc['label']:<30} {reply[:70]}")
    print("\nAll n8n tests passed." if not failures else f"\n{failures} failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
