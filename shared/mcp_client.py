"""A minimal client for ProofAgent Nano's MCP server (Streamable HTTP, JSON-RPC).

Nano's MCP server is stateless and answers plain JSON, so a tools/call is one POST.
For a full MCP client in LangChain, see `langchain-mcp-adapters` (shown in the README).

Every check_* tool returns:
    {"action": "ALLOW | ALLOW_MASKED | NEEDS_REVIEW | BLOCK", "use_this": ..., "reason": ...}
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "guards" / "python"))
from guard import LocalGuard  # noqa: E402


class NanoMCP:
    def __init__(self, url=None, api_key=None, timeout=10):
        base = (url or os.environ.get("PROOFAGENT_NANO_URL", "https://nano.proofagent.ai")).rstrip("/")
        self.url = base + "/mcp"
        self.api_key = api_key or os.environ.get("PROOFAGENT_NANO_API_KEY")
        self.timeout = timeout
        self._id = 0
        if not self.api_key:
            raise RuntimeError("Set PROOFAGENT_NANO_API_KEY (get one at nano.proofagent.ai)")

    def call(self, name: str, /, **arguments) -> dict:
        self._id += 1
        body = {"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.load(resp).get("result", {})
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return {"action": "BLOCK", "use_this": None, "reason": f"guard unavailable, failing closed: {e}"}
        if result.get("isError"):
            return {"action": "NEEDS_REVIEW", "use_this": None, "reason": str(result.get("content"))}
        return result.get("structuredContent") or {"action": "BLOCK", "use_this": None, "reason": "no result"}


class LocalMCP:
    """Offline stand-in with the same check_* tools and result shape, so the demo runs without a key."""

    _MAP = {"ALLOW": "ALLOW", "MASK": "ALLOW_MASKED", "REVIEW": "NEEDS_REVIEW", "BLOCK": "BLOCK"}
    _CHECKPOINT = {"check_user_message": "input", "check_tool_call": "tool_call",
                   "check_tool_result": "tool_result", "check_reply": "output"}

    def __init__(self):
        self.guard = LocalGuard()

    def call(self, name: str, /, **arguments) -> dict:
        if name == "check_tool_call":
            text = f"{arguments['tool']}({arguments['arguments']})"
        else:
            text = str(arguments.get("text") or arguments.get("result"))
        d = self.guard.check(text, self._CHECKPOINT[name])
        use_this = arguments.get("arguments") if name == "check_tool_call" else d.text
        return {"action": self._MAP[d.action], "use_this": None if d.blocked else use_this,
                "reason": "; ".join(d.reasons), "result": d.raw}


def get_mcp(name=None):
    name = (name or os.environ.get("GUARD", "local")).lower()
    return NanoMCP() if name == "nano" else LocalMCP()
