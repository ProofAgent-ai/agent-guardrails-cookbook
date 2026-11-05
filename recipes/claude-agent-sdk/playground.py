"""Playground adapter for the Claude Agent SDK recipe. Offline: the real hooks in a simulated agent loop
(the live SDK needs a Claude account; run agent.py --live for that)."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("claude_agent_recipe", HERE / "agent.py")
_agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_agent)

NAME = "Claude Agent SDK"
MODES = ("unguarded", "api", "mcp", "hybrid")


def run(mode, message, guard, mcp, model, policy=None):
    return _agent.run(message, mode, guard, mcp, policy, live=False, model=model)
