"""Checkpoints 2a and 2b as native OpenAI Agents SDK tool guardrails. Copy this file into your project.

    check_tool_call   (tool_input_guardrail)   tool policy, then the guardrail, before a tool runs
    check_tool_result (tool_output_guardrail)  the guardrail on what the tool returned, before the model reads it

Give them a `Guard` for the API pattern, or an MCP client for the MCP and hybrid patterns.
"""
import json

from agents import ToolGuardrailFunctionOutput, tool_input_guardrail, tool_output_guardrail

WITHHELD = "[content withheld by guardrail]"
MCP_STOP = {"BLOCK", "NEEDS_REVIEW"}


def make_tool_guardrails(guard=None, mcp=None, policy=None):
    """Return ([check_tool_call], [check_tool_result]) for function_tool(...)."""

    @tool_input_guardrail
    def check_tool_call(data):
        name = data.context.tool_name
        args = json.loads(data.context.tool_arguments or "{}")
        if policy and policy.check(name, args).stop:                  # schema, allowlist, approval
            return ToolGuardrailFunctionOutput.raise_exception(output_info="tool policy")
        if mcp:
            stop = mcp.call("check_tool_call", tool=name, arguments=args)["action"] in MCP_STOP
        else:
            d = guard.check(f"{name}({args})", "tool_call")
            stop = d.blocked or d.needs_review
        return ToolGuardrailFunctionOutput.raise_exception(output_info="guardrail") if stop \
            else ToolGuardrailFunctionOutput.allow()

    @tool_output_guardrail
    def check_tool_result(data):
        out = str(data.output)
        if mcp:
            r = mcp.call("check_tool_result", result=out, tool=data.context.tool_name)
            text = WITHHELD if r["action"] in MCP_STOP else r["use_this"]
        else:
            d = guard.check(out, "tool_result")
            text = WITHHELD if d.blocked else d.text
        # reject_content hands the model this text instead of the raw output: the injection is gone, the facts stay.
        return ToolGuardrailFunctionOutput.allow() if text == out else ToolGuardrailFunctionOutput.reject_content(message=text)

    return [check_tool_call], [check_tool_result]
