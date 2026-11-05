"""Playground adapter: lets playground/server.py run this recipe.

Every framework recipe ships one of these with the same interface:

    NAME, MODES
    run(mode, message, guard, mcp, model) -> {"answer": str, "tools": [{"name", "output"}]}

`guard` is a Guard (API and hybrid), `mcp` has .call(tool, **args) (MCP and hybrid),
`model` is framework-neutral (shared/models.py: turns -> step). The server passes traced versions.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import TOOLS, lc_model  # noqa: E402
from langchain_core.messages import HumanMessage, ToolMessage  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.prebuilt import ToolNode, tools_condition  # noqa: E402

NAME = "LangGraph"
MODES = ("unguarded", "api", "mcp", "hybrid")


def _load(rel):
    path = HERE / rel
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(f"langgraph_{rel.replace('/', '_')[:-3]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_API, _MCP, _HYBRID = _load("api/agent.py"), _load("mcp/agent.py"), _load("hybrid/agent.py")


def _unguarded(model):
    g = StateGraph(MessagesState)
    g.add_node("agent", lambda s: {"messages": [model(s["messages"])]})
    g.add_node("tools", ToolNode(TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition, ["tools", END])
    g.add_edge("tools", "agent")
    return g.compile()


def run(mode, message, guard, mcp, model):
    model = lc_model(model)
    graph = {"unguarded": lambda: _unguarded(model),
             "api": lambda: _API.build_graph(guard, model),
             "mcp": lambda: _MCP.build_graph(mcp, model),
             "hybrid": lambda: _HYBRID.build_graph(guard, mcp, model)}[mode]()
    messages = graph.invoke({"messages": [HumanMessage(content=message)]})["messages"]
    return {"answer": messages[-1].content,
            "tools": [{"name": m.name, "output": m.content} for m in messages if isinstance(m, ToolMessage)]}
