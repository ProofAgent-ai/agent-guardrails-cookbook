"""Checkpoints 2a and 2b as native CrewAI tool hooks. Copy this file into your project.

    before_tool_call   tool policy, then the guardrail. Returning False blocks the tool.
    after_tool_call    the guardrail on the tool's output. Returning a string replaces what the agent reads.

Give it a `Guard` (API pattern) or an MCP client (MCP and hybrid patterns).
"""
WITHHELD = "[content withheld by guardrail]"
MCP_STOP = {"BLOCK", "NEEDS_REVIEW"}


def make_tool_hooks(guard=None, mcp=None, policy=None, on_block=None):
    """Return (before_tool_call, after_tool_call). `on_block()` is called when a tool is stopped."""

    def before_tool_call(ctx):
        name, args = ctx.tool_name, dict(ctx.tool_input or {})
        if policy and policy.check(name, args).stop:                  # schema, allowlist, approval
            stop = True
        elif mcp:
            stop = mcp.call("check_tool_call", tool=name, arguments=args)["action"] in MCP_STOP
        else:
            d = guard.check(f"{name}({args})", "tool_call")
            stop = d.blocked or d.needs_review
        if stop and on_block:
            on_block()
        return False if stop else None

    def after_tool_call(ctx):
        out = str(ctx.tool_result)
        if mcp:
            r = mcp.call("check_tool_result", result=out, tool=ctx.tool_name)
            text = WITHHELD if r["action"] in MCP_STOP else r["use_this"]
        else:
            d = guard.check(out, "tool_result")
            text = WITHHELD if d.blocked else d.text
        return None if text == out else text

    return before_tool_call, after_tool_call
