"""Guard nodes for any LangGraph graph. Copy this file into your project.

Four nodes, one per checkpoint. Each one either lets the state through (rewriting
messages with the masked or sanitised text) or ends the run with a refusal.

    START → guard_input → agent ⇄ [guard_tool_call → tools → guard_tool_result] → guard_output → END
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import Command

REFUSAL = "Sorry, I can't help with that."


def make_guard_nodes(guard, agent="agent", tools="tools"):
    """Return the four guard nodes, bound to a `Guard` (see guards/python/guard.py)."""

    def refuse(replace_id=None):
        # Reusing the id of the last AI message replaces it, so no dangling tool_calls are left.
        msg = AIMessage(content=REFUSAL, id=replace_id) if replace_id else AIMessage(content=REFUSAL)
        return Command(update={"messages": [msg]}, goto=END)

    # 1. INPUT: before the agent sees the user's message.
    def guard_input(state):
        msg = state["messages"][-1]
        d = guard.check(msg.content, "input")
        if d.blocked or d.needs_review:
            return refuse()
        # Same id → add_messages replaces the original, so the model only ever sees the masked text.
        return Command(update={"messages": [HumanMessage(content=d.text, id=msg.id)]}, goto=agent)

    # 2a. TOOL CALL: before any tool runs. Checks the action, not just words.
    def guard_tool_call(state):
        ai = state["messages"][-1]
        for call in ai.tool_calls:
            d = guard.check(f"{call['name']}({call['args']})", "tool_call")
            if d.blocked or d.needs_review:
                return refuse(replace_id=ai.id)
        return Command(goto=tools)

    # 2b. TOOL RESULT: untrusted content (pages, files, APIs) before the model reads it.
    def guard_tool_result(state):
        updates = []
        for msg in reversed(state["messages"]):
            if not isinstance(msg, ToolMessage):
                break
            d = guard.check(str(msg.content), "tool_result")
            text = "[content withheld by guardrail]" if d.blocked else d.text
            if text != msg.content:
                updates.append(ToolMessage(content=text, tool_call_id=msg.tool_call_id, name=msg.name, id=msg.id))
        return Command(update={"messages": updates}, goto=agent)

    # 3. OUTPUT: before the reply reaches the user.
    def guard_output(state):
        ai = state["messages"][-1]
        d = guard.check(ai.content, "output")
        if d.blocked or d.needs_review:
            return refuse(replace_id=ai.id)
        return Command(update={"messages": [AIMessage(content=d.text, id=ai.id)]}, goto=END)

    return guard_input, guard_tool_call, guard_tool_result, guard_output


def route_after_agent(state):
    """Tool calls go to the tool-call guard, final answers to the output guard."""
    return "guard_tool_call" if state["messages"][-1].tool_calls else "guard_output"
