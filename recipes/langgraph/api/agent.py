"""API version: guard nodes in the graph. The graph enforces every checkpoint;
the model can't skip one, because the model never decides whether to check.

    python api/agent.py                 # local guard, offline
    python api/agent.py --guard nano    # ProofAgent Nano via POST /v1/scan
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import SCENARIOS, TOOLS, naive_model  # noqa: E402  (also puts guards/python on the path)
from guard import get_guard  # noqa: E402
from guard_nodes import make_guard_nodes, route_after_agent  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.graph import START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode  # noqa: E402


def build_graph(guard, model=naive_model, policy=None):
    """`model` is any function messages -> AIMessage: the stub, or one from llm.make_model."""
    def agent(state: MessagesState):
        return {"messages": [model(state["messages"])]}

    guard_input, guard_tool_call, guard_tool_result, guard_output = make_guard_nodes(guard, policy=policy)
    g = StateGraph(MessagesState)
    g.add_node("guard_input", guard_input, destinations=("agent", "__end__"))
    g.add_node("agent", agent)
    g.add_node("guard_tool_call", guard_tool_call, destinations=("tools", "__end__"))
    g.add_node("tools", ToolNode(TOOLS))
    g.add_node("guard_tool_result", guard_tool_result, destinations=("agent",))
    g.add_node("guard_output", guard_output, destinations=("__end__",))
    g.add_edge(START, "guard_input")
    g.add_conditional_edges("agent", route_after_agent, ["guard_tool_call", "guard_output"])
    g.add_edge("tools", "guard_tool_result")
    return g.compile()


def ask(graph, text: str) -> str:
    return graph.invoke({"messages": [HumanMessage(content=text)]})["messages"][-1].content


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", default=None, help="local (default) or nano")
    graph = build_graph(get_guard(ap.parse_args().guard))
    for title, msg in SCENARIOS:
        print(f"── {title}\n   user:  {msg}\n   agent: {ask(graph, msg)}\n")
