"""MCP version: the agent node guards itself by calling Nano's MCP tools.

There are no guard nodes in the graph. Before the agent node reasons, it calls
`check_user_message` / `check_tool_result`; before it acts, `check_tool_call`;
before it answers, `check_reply`. The graph is the plain agent ⇄ tools loop.

    python mcp/agent.py                 # offline stand-in with the same tools
    python mcp/agent.py --guard nano    # ProofAgent Nano at https://nano.proofagent.ai/mcp
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import REFUSAL, SCENARIOS, TOOLS, naive_model  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode, tools_condition  # noqa: E402
from mcp_client import get_mcp  # noqa: E402  (shared/mcp_client.py)

STOP = {"BLOCK", "NEEDS_REVIEW"}


def make_guarded_agent(mcp, model=naive_model, check_input=True, policy=None):
    """check_input=False when something in front of the agent (an API gateway) already checks user messages."""
    def agent(state: MessagesState):
        messages = list(state["messages"])
        last = messages[-1]
        rewrites = []

        # Before reasoning: check what just arrived.
        if isinstance(last, HumanMessage) and check_input:
            r = mcp.call("check_user_message", text=last.content)
            if r["action"] in STOP:
                return {"messages": [AIMessage(content=REFUSAL)]}
            messages[-1] = HumanMessage(content=r["use_this"], id=last.id)
            rewrites.append(messages[-1])
        elif isinstance(last, ToolMessage):
            r = mcp.call("check_tool_result", result=str(last.content), tool=last.name)
            text = "[content withheld by guardrail]" if r["action"] in STOP else r["use_this"]
            messages[-1] = ToolMessage(content=text, tool_call_id=last.tool_call_id, name=last.name, id=last.id)
            rewrites.append(messages[-1])

        reply = model(messages)

        # Before acting: check every tool call.
        for call in reply.tool_calls:
            if policy and policy.check(call["name"], call["args"]).stop:      # schema, allowlist, approval
                return {"messages": rewrites + [AIMessage(content=REFUSAL)]}
            r = mcp.call("check_tool_call", tool=call["name"], arguments=call["args"])
            if r["action"] in STOP:
                return {"messages": rewrites + [AIMessage(content=REFUSAL)]}

        # Before answering: check the reply.
        if not reply.tool_calls:
            r = mcp.call("check_reply", text=reply.content)
            reply = AIMessage(content=REFUSAL if r["action"] in STOP else r["use_this"])

        return {"messages": rewrites + [reply]}

    return agent


def build_graph(mcp, model=naive_model, policy=None):
    g = StateGraph(MessagesState)
    g.add_node("agent", make_guarded_agent(mcp, model, policy=policy))
    g.add_node("tools", ToolNode(TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile()


def ask(graph, text: str) -> str:
    return graph.invoke({"messages": [HumanMessage(content=text)]})["messages"][-1].content


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", default=None, help="local (default) or nano")
    graph = build_graph(get_mcp(ap.parse_args().guard))
    for title, msg in SCENARIOS:
        print(f"── {title}\n   user:  {msg}\n   agent: {ask(graph, msg)}\n")
