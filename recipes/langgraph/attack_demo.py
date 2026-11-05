"""Run the same 4 scenarios through three graphs: unguarded, API guard nodes, MCP in the agent node.

    python attack_demo.py                 # offline
    python attack_demo.py --guard nano    # ProofAgent Nano (API and MCP)
"""
import argparse
import importlib.util
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import SCENARIOS, TOOLS, naive_model  # noqa: E402
from guard import get_guard  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode, tools_condition  # noqa: E402


def load(rel):
    """Import api/agent.py and mcp/agent.py side by side (both are named agent.py)."""
    path = HERE / rel
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(rel.replace("/", "_")[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def unguarded():
    g = StateGraph(MessagesState)
    g.add_node("agent", lambda s: {"messages": [naive_model(s["messages"])]})
    g.add_node("tools", ToolNode(TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile()


def ask(graph, text):
    return graph.invoke({"messages": [HumanMessage(content=text)]})["messages"][-1].content


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", default=None, help="local (default) or nano")
    name = ap.parse_args().guard
    api, mcp, hyb = load("api/agent.py"), load("mcp/agent.py"), load("hybrid/agent.py")
    graphs = {"unguarded": unguarded(),
              "API guard nodes": api.build_graph(get_guard(name)),
              "MCP in agent node": mcp.build_graph(mcp.get_mcp(name)),
              "Hybrid": hyb.build_graph(get_guard(name), mcp.get_mcp(name))}
    for title, msg in SCENARIOS:
        print(f"\n── {title}\n   user: {msg}")
        for label, graph in graphs.items():
            out = ask(graph, msg)
            mark = "❌" if "EMAIL SENT" in out or "4539" in out else "✅"
            print(f"   {mark} {label:<18} {out}")
