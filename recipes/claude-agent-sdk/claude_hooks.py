"""Checkpoints 2a and 2b as Claude Agent SDK hooks. Copy this file into your project.

    PreToolUse    tool policy, then the guardrail. Denies the call with a reason.
    PostToolUse   the guardrail on the tool's output; replaces it via updatedMCPToolOutput.

    options = ClaudeAgentOptions(hooks=make_hooks(guard=…) or make_hooks(mcp=…), …)
"""
import json

from claude_agent_sdk import HookMatcher

WITHHELD = "[content withheld by guardrail]"
MCP_STOP = {"BLOCK", "NEEDS_REVIEW"}
SERVER = "shop"                     # tools are served as mcp__shop__<name>


def tool_name(full):
    return full.split("__")[-1]


def output_text(resp):
    """MCP tool responses arrive as {"content": [{"type": "text", "text": …}]} (or a list of blocks)."""
    blocks = resp.get("content", resp) if isinstance(resp, dict) else resp
    if isinstance(blocks, list):
        return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    return str(blocks)


def make_hooks(guard=None, mcp=None, policy=None, on_block=None):
    async def pre_tool_use(data, tool_use_id, context):
        name, args = tool_name(data["tool_name"]), dict(data.get("tool_input") or {})
        reason = None
        if policy:
            d = policy.check(name, args)
            reason = "; ".join(d.reasons) if d.stop else None
        if reason is None and mcp:
            r = mcp.call("check_tool_call", tool=name, arguments=args)
            if r["action"] in MCP_STOP:
                reason = r.get("reason") or r["action"]
        elif reason is None and guard:
            d = guard.check(f"{name}({json.dumps(args)})", "tool_call")
            if d.blocked or d.needs_review:
                reason = "; ".join(d.reasons) or d.action
        if reason is None:
            return {}
        if on_block:
            on_block()
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": f"Blocked by guardrail: {reason}"}}

    async def post_tool_use(data, tool_use_id, context):
        out = output_text(data.get("tool_response"))
        if mcp:
            r = mcp.call("check_tool_result", result=out, tool=tool_name(data["tool_name"]))
            text = WITHHELD if r["action"] in MCP_STOP else r["use_this"]
        else:
            d = guard.check(out, "tool_result")
            text = WITHHELD if d.blocked else d.text
        if text == out:
            return {}
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                       "updatedMCPToolOutput": {"content": [{"type": "text", "text": text}]}}}

    match = f"mcp__{SERVER}__.*"
    return {"PreToolUse": [HookMatcher(matcher=match, hooks=[pre_tool_use])],
            "PostToolUse": [HookMatcher(matcher=match, hooks=[post_tool_use])]}
