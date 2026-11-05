"""Deterministic tool policy for checkpoint 2a, from shared/agent/tools.json.

Runs before the guardrail model on every tool call. It catches what rules are best at:
unknown tools, arguments that break the schema, and actions that send data outside an
allowlist. The guardrail (Nano) then judges the intent of whatever passes.

    from tool_policy import ToolPolicy
    d = ToolPolicy.load().check("send_email", {"to": "a@b.com", "body": "…"})
    d.action  # ALLOW | REVIEW | BLOCK
"""
import json
import re

# A guardrail placeholder such as [CONTACT:EMAIL#1] or [EMAIL#1]: masked personal data.
PLACEHOLDER = re.compile(r"^\[[A-Z_]+(?::[A-Z_]+)?#\d+\]$")
from dataclasses import dataclass, field
from pathlib import Path

SPEC = Path(__file__).resolve().parent / "agent" / "tools.json"


@dataclass
class PolicyDecision:
    action: str
    reasons: list = field(default_factory=list)

    @property
    def stop(self):
        return self.action in ("BLOCK", "REVIEW")


def _validate(schema, args):
    """The subset of JSON Schema the tool specs use: object, required, string, pattern, maxLength."""
    if not isinstance(args, dict):
        return ["arguments must be an object"]
    errors, props = [], schema.get("properties", {})
    errors += [f"missing required argument '{k}'" for k in schema.get("required", []) if k not in args]
    if schema.get("additionalProperties") is False:
        errors += [f"unexpected argument '{k}'" for k in args if k not in props]
    for k, v in args.items():
        p = props.get(k)
        if not p:
            continue
        if p.get("type") == "string" and not isinstance(v, str):
            errors.append(f"'{k}' must be a string"); continue
        if "maxLength" in p and len(v) > p["maxLength"]:
            errors.append(f"'{k}' is longer than {p['maxLength']} characters")
        if "pattern" in p and not re.search(p["pattern"], v):
            errors.append(f"'{k}' doesn't match {p['pattern']}")
    return errors


class ToolPolicy:
    def __init__(self, spec):
        self.spec = spec
        self.tools = {t["name"]: t for t in spec["tools"]}
        self.allowed_domains = [d.lower() for d in spec.get("allow", {}).get("email_domains", [])]

    @classmethod
    def load(cls, path=SPEC):
        return cls(json.loads(Path(path).read_text()))

    def check(self, name, args):
        tool = self.tools.get(name)
        if not tool:
            return PolicyDecision("BLOCK", [f"'{name}' is not one of the agent's tools"])
        risk = tool.get("risk", {})
        dest_arg = risk.get("destination_arg")
        if dest_arg and PLACEHOLDER.match(str(args.get(dest_arg, ""))):
            return PolicyDecision("REVIEW", [f"{name} destination is masked personal data ({args[dest_arg]}): "
                                             "resolve it from your placeholder vault and get approval before sending"])
        errors = _validate(tool["input_schema"], args)
        if errors:
            return PolicyDecision("BLOCK", [f"invalid arguments for {name}: " + "; ".join(errors)])
        if risk.get("egress") and risk.get("requires_approval") == "outside_allowlist":
            dest = str(args.get(risk.get("destination_arg", "to"), ""))
            domain = dest.rsplit("@", 1)[-1].lower()
            if domain not in self.allowed_domains:
                return PolicyDecision("REVIEW", [f"{name} to '{dest}' leaves the allowlist "
                                                 f"({', '.join(self.allowed_domains)}): needs human approval"])
        return PolicyDecision("ALLOW", [f"{name}: schema valid, risk {risk.get('level', 'unknown')}"])
