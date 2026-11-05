"""Every scenario through unguarded, API guard nodes, MCP in the agent node and hybrid. Offline by default.

    python attack_demo.py                 # local guard + stub model
    python attack_demo.py --guard nano    # ProofAgent Nano
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "shared"))
from demo_runner import main  # noqa: E402

spec = importlib.util.spec_from_file_location("langgraph_playground", HERE / "playground.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
main(adapter)
