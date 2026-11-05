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

# Each rule: (pattern, risk id, title, risk class). Same finding shape as Nano, so the playground can show it.
_INJECTION = [
    (r"ignore (all |any )?(previous|prior|above) (instructions|rules)", "prompt_injection", "Prompt injection", "OWASP LLM01 · Prompt injection"),
    (r"disregard (your|the) (instructions|system prompt|rules)", "prompt_injection", "Prompt injection", "OWASP LLM01 · Prompt injection"),
    (r"(reveal|print|show|repeat) (your|the) (system prompt|instructions)", "system_prompt_leak", "System prompt extraction", "OWASP LLM07 · System prompt leakage"),
    (r"you are now (dan|in developer mode|unrestricted)", "jailbreak", "Jailbreak (role-play override)", "OWASP LLM01 · Prompt injection"),
    (r"ignore[sz]? (les|toutes les) instructions", "prompt_injection", "Prompt injection (French)", "OWASP LLM01 · Prompt injection"),
    (r"تجاهل (جميع |كل )?التعليمات", "prompt_injection", "Prompt injection (Arabic)", "OWASP LLM01 · Prompt injection"),
]
_EXFIL = [
    (r"(send|email|post|upload|forward) .{0,40}(customer list|all (users|customers)|database|credentials|api keys?)", "data_exfiltration", "Data exfiltration", "OWASP LLM02 · Sensitive information disclosure"),
    (r"curl .{0,80}(\| *sh|-d @)", "data_exfiltration", "Data exfiltration (shell)", "OWASP LLM02 · Sensitive information disclosure"),
]
_DANGEROUS_TOOL = [(p, "dangerous_tool", "Destructive tool call", "OWASP LLM06 · Excessive agency")
                   for p in (r"rm -rf /", r"drop table", r"chmod 777", r"mkfs", r":\(\)\{")]
_HIDDEN = re.compile(r"<!--.*?-->", re.S)
_PII = {
    "EMAIL": (r"[\w.+-]+@[\w-]+\.[\w.]+", "Email address"),
    "CARD": (r"\b(?:\d[ -]?){13,16}\b", "Payment card number"),
    "PHONE": (r"\+?\d[\d -]{8,}\d", "Phone number"),
    "IBAN": (r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", "Bank account (IBAN)"),
}
_REGS = {
    "pii": ("EU GDPR", "Art. 5(1)(c), Art. 32", "Personal data must be minimised and protected."),
    "CARD": ("PCI DSS", "Req. 3.4", "Card numbers must be unreadable wherever they are stored or shown."),
    "risk": ("OWASP Top 10 for LLM Apps", "2025", "A known attack pattern against language-model applications."),
}


class LocalGuard(Guard):
    """Good enough to learn the pattern. Not a production guardrail.

    Returns a Nano-shaped result in `raw` (findings, PII, regulations) so tools can show it the same way.
    Regex rules have no confidence score: each finding says "rule match" instead.
    """
    name = "local"

    def check(self, text: str, checkpoint: str = "input") -> Decision:
        original, low = text, text.lower()
        reasons, risks = [], []
        def risk(rid, title, family, action, what):
            risks.append({"id": rid, "kind": "risk", "action": action, "band": "rule match", "confidence": None,
                          "id_risk": rid, "explanation": {"title": title, "what": what, "risk_family": family}})
        if checkpoint == "tool_result" and _HIDDEN.search(text):
            text = _HIDDEN.sub("", text)
            reasons.append("hidden instructions removed")
            risk("indirect_injection", "Hidden instructions in tool output", "OWASP LLM01 · Indirect prompt injection",
                 "SANITISE", "An HTML comment carried instructions for the model; it was removed.")
        rules = _INJECTION + _EXFIL + (_DANGEROUS_TOOL if checkpoint == "tool_call" else [])
        for p, rid, title, family in rules:
            if re.search(p, low if p.isascii() else text):
                if checkpoint == "tool_result":   # sanitise content, don't kill the step
                    text = re.sub(p, "[removed]", text, flags=re.I)
                    reasons.append(f"injection removed: {p}")
                    risk(rid, title, family, "SANITISE", f"Matched rule {p!r}; the text was removed.")
                else:
                    reasons.append(f"matched: {p}")
                    risk(rid, title, family, "BLOCK", f"Matched rule {p!r}.")
                    return Decision("BLOCK", None, reasons, raw=self._raw("BLOCK", original, None, risks, [], checkpoint))
        masked, spans = text, []
        for kind, (p, title) in _PII.items():
            def sub(_m, kind=kind, title=title):
                n = sum(s["subfamily"] == kind for s in spans) + 1
                spans.append({"id": f"{kind}#{n}", "kind": "span", "action": "MASK", "family": "pii", "subfamily": kind,
                              "placeholder": f"[{kind}#{n}]", "confidence": None, "band": "rule match",
                              "explanation": {"title": title, "what_to_do": "Masked before the model or the user sees it."}})
                return f"[{kind}#{n}]"
            masked = re.sub(p, sub, masked)
        if spans:
            reasons.append("PII masked")
        action = "MASK" if reasons else "ALLOW"
        return Decision(action, masked, reasons, raw=self._raw(action, original, masked, risks, spans, checkpoint))

    @staticmethod
    def _raw(action, text, masked, risks, spans, checkpoint):
        regs = []
        if spans:
            regs.append(_REGS["pii"])
            if any(s["subfamily"] == "CARD" for s in spans):
                regs.append(_REGS["CARD"])
        if risks:
            regs.append(_REGS["risk"])
        n_pii = len(spans)
        headline = {"BLOCK": f"Blocked: {risks[0]['explanation']['title'].lower()}" if risks else "Blocked",
                    "MASK": "Allowed after cleaning" + (f" · {n_pii} personal data item{'s' * (n_pii != 1)} masked" if n_pii else ""),
                    "ALLOW": "Nothing risky found"}[action]
        todo = {"BLOCK": "Do not pass this to the agent. Reply with a refusal.",
                "MASK": "Use the cleaned text instead of the original.",
                "ALLOW": "Safe to continue."}[action]
        return {
            "decision": {"action": action, "severity": "high" if action == "BLOCK" else "medium" if action == "MASK" else "low",
                         "reasons": [r["id"] for r in risks] or [s["subfamily"] for s in spans]},
            "report": {"headline": headline, "what_to_do": todo, "summary": headline},
            "findings": risks + spans,
            "regulations": [{"framework": f, "cite": c, "meaning": m} for f, c, m in regs],
            "text": {"original": text, "masked": masked},
            "request": {"mode": "local rules", "direction": checkpoint},
            "nano": {"engine": "Local rules (offline, regex)"},
        }


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
