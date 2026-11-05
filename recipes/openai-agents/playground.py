"""Playground adapter for the OpenAI Agents SDK recipe (see recipes/langgraph/playground.py for the contract)."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "shared"))
import model_gateway  # noqa: E402

_spec = importlib.util.spec_from_file_location("openai_agents_recipe", HERE / "agent.py")
_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_agent)

NAME = "OpenAI Agents SDK"
MODES = ("unguarded", "api", "mcp", "hybrid")


def run(mode, message, guard, mcp, model, policy=None):
    # The SDK talks to an OpenAI-style endpoint: the gateway serves the playground's (traced) model.
    return _agent.run(message, mode, guard, mcp, policy, model_name=model_gateway.register(model))
