"""A local, OpenAI-compatible model endpoint for the recipes. Standard library only.

Frameworks that talk to "an OpenAI-style chat model" (OpenAI Agents SDK, CrewAI, LangChain…)
point their base URL here. The gateway answers /v1/chat/completions with native tool calls,
backed by any framework-neutral model from shared/models.py:

    model="stub"                         the stub that obeys any instruction (no key, repeatable)
    model="lmstudio/<id>", "ollama/<id>" a local model through the JSON tool protocol, so even
                                         models without native tool support work

    base_url = start()          # http://127.0.0.1:<port>/v1, served from a background thread
    api_key="gw:<model>"        # optional: pick the backend in the key when the framework needs a known model name
"""
import json
import re
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import models

_SERVERS = {}
_REGISTERED = {}


def register(model_fn):
    """Serve any turns -> step function under a fresh model name (the playground passes traced models)."""
    name = f"registered/{uuid.uuid4().hex[:10]}"
    _REGISTERED[name] = model_fn
    return name


def backend(model_name, api_key=None):
    """Map an OpenAI 'model' string to a framework-neutral model (turns -> step)."""
    if model_name in _REGISTERED:
        return _REGISTERED[model_name]
    name = (model_name or "stub").split("/", 1)
    if name[0] in ("stub", "naive"):
        return models.naive
    provider, model = name[0], name[1] if len(name) > 1 else None
    return models.make_llm(provider, model, api_key)


def to_turns(messages):
    """OpenAI chat messages -> the neutral turn list."""
    names, turns = {}, []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if isinstance(content, list):          # content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if role == "user":
            turns.append({"role": "user", "content": content or ""})
        elif role == "assistant" and m.get("tool_calls"):
            for c in m["tool_calls"]:
                names[c["id"]] = c["function"]["name"]
                args = c["function"].get("arguments") or "{}"
                turns.append({"role": "assistant", "tool": c["function"]["name"],
                              "args": json.loads(args) if isinstance(args, str) else args})
        elif role == "assistant":
            turns.append({"role": "assistant", "answer": content or ""})
        elif role == "tool":
            turns.append({"role": "tool", "name": names.get(m.get("tool_call_id"), "tool"), "content": content or ""})
    return turns


_ACTION = re.compile(r"Action:\s*(\S+)\s*\nAction Input:\s*(\{.*?\})\s*(?:\n|$)", re.S)
_OBS = re.compile(r"Observation:\s*(.*?)(?=\n\s*Thought:|\nAction:|\Z)", re.S)


def is_react(body):
    """Frameworks that describe tools in the prompt (CrewAI's ReAct format) instead of sending `tools`."""
    system = " ".join(str(m.get("content")) for m in body.get("messages", []) if m.get("role") == "system")
    return not body.get("tools") and "Action Input:" in system


def react_turns(messages):
    """CrewAI's Thought / Action / Action Input / Observation transcript -> neutral turns."""
    rest = [m for m in messages if m.get("role") != "system"]
    first = str(rest[0].get("content", "")) if rest else ""
    task = re.search(r"Current Task:\s*(.*?)(?:\n\nThis is the expected|$)", first, re.S)
    turns = [{"role": "user", "content": (task.group(1) if task else first).strip()}]
    # Actions and their observations are in the assistant messages; user messages after the first are reminders.
    later = "\n".join(str(m.get("content", "")) for m in rest[1:] if m.get("role") == "assistant")
    events = sorted([(m.start(), "a", m) for m in _ACTION.finditer(later)] + [(m.start(), "o", m) for m in _OBS.finditer(later)],
                    key=lambda e: e[0])
    last_tool = "tool"
    for _, kind, m in events:
        if kind == "a":
            last_tool = m.group(1)
            try:
                args = json.loads(m.group(2))
            except ValueError:
                args = {}
            turns.append({"role": "assistant", "tool": last_tool, "args": args})
        else:
            turns.append({"role": "tool", "name": last_tool, "content": m.group(1).strip()})
    return turns


def react_completion(body, api_key=None):
    step = backend(body.get("model"), api_key)(react_turns(body.get("messages", [])))
    text = (f"Thought: I need to use a tool.\nAction: {step['tool']}\nAction Input: {json.dumps(step['args'])}"
            if "tool" in step else f"Thought: I now know the final answer\nFinal Answer: {step.get('answer', '')}")
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "stub"), "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def completion(body, api_key=None):
    if is_react(body):
        return react_completion(body, api_key)
    step = backend(body.get("model"), api_key)(to_turns(body.get("messages", [])))
    offered = {t["function"]["name"] for t in body.get("tools", []) if t.get("type") == "function"}
    if "tool" in step and (not offered or step["tool"] in offered):
        msg = {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"call_{uuid.uuid4().hex[:12]}", "type": "function",
            "function": {"name": step["tool"], "arguments": json.dumps(step["args"])}}]}
        finish = "tool_calls"
    else:
        msg, finish = {"role": "assistant", "content": step.get("answer", "")}, "stop"
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "stub"), "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": "stub", "object": "model"}]})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "not found"}})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if body.get("stream"):
            return self._json(400, {"error": {"message": "streaming isn't supported by the local gateway"}})
        key = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if key.startswith("gw:"):
            # Frameworks that only enable native tool calling for model names they know (CrewAI) can send a
            # known name such as "gpt-4o" and choose the gateway's backend in the key: api_key="gw:stub".
            body["model"], key = key[3:], ""
        try:
            self._json(200, completion(body, None if key in ("", "local", "sk-local") else key))
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": {"message": f"{type(e).__name__}: {e}"}})


def start(port=0):
    """Start (once per process) and return the base URL, e.g. http://127.0.0.1:53111/v1."""
    if "url" in _SERVERS:
        return _SERVERS["url"]
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        port = s.getsockname()[1]
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _SERVERS["url"] = f"http://127.0.0.1:{port}/v1"
    return _SERVERS["url"]


if __name__ == "__main__":
    print("Model gateway:", start(8780))
    threading.Event().wait()
