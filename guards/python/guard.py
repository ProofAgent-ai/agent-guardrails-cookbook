"""A tiny, vendor-neutral guard interface used by every recipe.

    guard = get_guard()                       # from GUARD env var, default "local"
    d = guard.check(text, checkpoint="input") # "input" | "tool_call" | "tool_result" | "output"
    if d.blocked: ...
    use(d.text)                               # masked or sanitised text

No dependencies: standard library only.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

CHECKPOINTS = ("input", "tool_call", "tool_result", "output")


@dataclass
class Decision:
    action: str                     # ALLOW | MASK | REVIEW | BLOCK
    text: str | None                # text to use instead of the original; None on BLOCK
    reasons: list[str] = field(default_factory=list)
    raw: dict | None = None         # the guard's full response, if any

    @property
    def blocked(self) -> bool:
        return self.action == "BLOCK"

    @property
    def needs_review(self) -> bool:
        return self.action == "REVIEW"


class Guard:
    name = "base"

    def check(self, text: str, checkpoint: str = "input") -> Decision:
        raise NotImplementedError


# --- Local guard: regex rules, offline, for learning only -------------------

_INJECTION = [
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"disregard (your|the) (instructions|system prompt|rules)",
    r"(reveal|print|show|repeat) (your|the) (system prompt|instructions)",
    r"you are now (dan|in developer mode|unrestricted)",
    r"ignore[sz]? (les|toutes les) instructions",       # French
    r"تجاهل (جميع |كل )?التعليمات",                      # Arabic
]
_EXFIL = [
    r"(send|email|post|upload|forward) .{0,40}(customer list|all (users|customers)|database|credentials|api keys?)",
    r"curl .{0,80}(\| *sh|-d @)",
]
_DANGEROUS_TOOL = [r"rm -rf /", r"drop table", r"chmod 777", r"mkfs", r":\(\)\{"]
_HIDDEN = re.compile(r"<!--.*?-->", re.S)
_PII = {
    "EMAIL": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "CARD": r"\b(?:\d[ -]?){13,16}\b",
    "PHONE": r"\+?\d[\d -]{8,}\d",
    "IBAN": r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b",
}


class LocalGuard(Guard):
    """Good enough to learn the pattern. Not a production guardrail."""
    name = "local"

    def check(self, text: str, checkpoint: str = "input") -> Decision:
        low = text.lower()
        reasons = []
        if checkpoint == "tool_result" and _HIDDEN.search(text):
            text = _HIDDEN.sub("", text)
            reasons.append("hidden instructions removed")
        rules = _INJECTION + _EXFIL + (_DANGEROUS_TOOL if checkpoint == "tool_call" else [])
        for p in rules:
            if re.search(p, low if p.isascii() else text):
                if checkpoint == "tool_result":   # sanitise content, don't kill the step
                    text = re.sub(p, "[removed]", text, flags=re.I)
                    reasons.append(f"injection removed: {p}")
                else:
                    return Decision("BLOCK", None, [f"matched: {p}"])
        masked = text
        for kind, p in _PII.items():
            n = 0
            def sub(_m, kind=kind):
                nonlocal n
                n += 1
                return f"[{kind}#{n}]"
            masked = re.sub(p, sub, masked)
        if masked != text:
            reasons.append("PII masked")
        action = "MASK" if reasons else "ALLOW"
        return Decision(action, masked, reasons)


# --- ProofAgent Nano over HTTP ----------------------------------------------

# Nano's direction for each checkpoint, and how its actions map to ours.
_NANO_DIRECTION = {"input": "input", "tool_call": "output", "tool_result": "tool", "output": "output"}
_NANO_ACTION = {"PASS": "ALLOW", "FLAG": "ALLOW", "MASK": "MASK", "SANITISE": "MASK",
                "REVIEW": "REVIEW", "GUARDIAN_ALERT": "REVIEW", "BLOCK": "BLOCK"}


class NanoGuard(Guard):
    """ProofAgent Nano (https://nano.proofagent.ai). Fails closed on any error."""
    name = "nano"

    def __init__(self, api_key: str | None = None, url: str | None = None, timeout: float = 10):
        self.api_key = api_key or os.environ.get("PROOFAGENT_NANO_API_KEY")
        self.url = (url or os.environ.get("PROOFAGENT_NANO_URL", "https://nano.proofagent.ai")).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("Set PROOFAGENT_NANO_API_KEY (get one at nano.proofagent.ai)")

    def check(self, text: str, checkpoint: str = "input") -> Decision:
        body = {"text": text, "direction": _NANO_DIRECTION[checkpoint]}
        if checkpoint == "tool_call":
            body["destination"] = "external_tool"
        req = urllib.request.Request(
            f"{self.url}/v1/scan", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                r = json.load(resp)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return Decision("BLOCK", None, [f"guard unavailable, failing closed: {e}"])
        action = _NANO_ACTION.get(r.get("decision", {}).get("action"), "BLOCK")
        masked = (r.get("text") or {}).get("masked") or text
        summary = (r.get("report") or {}).get("summary")
        return Decision(action, None if action == "BLOCK" else masked,
                        [summary] if summary else [], raw=r)


def get_guard(name: str | None = None) -> Guard:
    name = (name or os.environ.get("GUARD", "local")).lower()
    if name == "local":
        return LocalGuard()
    if name == "nano":
        return NanoGuard()
    raise ValueError(f"unknown guard {name!r}: use 'local' or 'nano'")
