"""Hybrid version: an API gateway in front of the agent, MCP inside it.

    user → [guard_input: POST /v1/scan] → agent ⇄ tools → reply
                                            └ check_tool_call / check_tool_result / check_reply over MCP

The gateway checks every user message before the agent exists for it, so it can't be
skipped. Inside, the agent node checks its own tool calls, tool results and reply with
Nano's MCP tools: no extra API plumbing around the tools.

    python hybrid/agent.py                 # local guard + offline MCP stand-in
    python hybrid/agent.py --guard nano    # ProofAgent Nano: /v1/scan for input, /mcp for the rest
"""
import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from common import SCENARIOS, TOOLS, naive_model  # noqa: E402
from guard import get_guard  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode, tools_condition  # noqa: E402
from mcp_client import get_mcp  # noqa: E402


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, HERE / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str((HERE / rel).parent))
    spec.loader.exec_module(mod)
    return mod


_nodes = _load("api/guard_nodes.py", "hybrid_guard_nodes")
_mcp_agent = _load("mcp/agent.py", "hybrid_mcp_agent")


def build_graph(guard, mcp, model=naive_model, policy=None):
    guard_input = _nodes.make_guard_nodes(guard)[0]          # checkpoint 1 over the API
    g = StateGraph(MessagesState)
    g.add_node("guard_input", guard_input, destinations=("agent", "__end__"))
    g.add_node("agent", _mcp_agent.make_guarded_agent(mcp, model, check_input=False, policy=policy))   # 2a, 2b, 3 over MCP
    g.add_node("tools", ToolNode(TOOLS))
    g.add_edge(START, "guard_input")
    g.add_conditional_edges("agent", tools_condition, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile()


def ask(graph, text: str) -> str:
    return graph.invoke({"messages": [HumanMessage(content=text)]})["messages"][-1].content


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", default=None, help="local (default) or nano")
    name = ap.parse_args().guard
    graph = build_graph(get_guard(name), get_mcp(name))
    for title, msg in SCENARIOS:
        print(f"── {title}\n   user:  {msg}\n   agent: {ask(graph, msg)}\n")
