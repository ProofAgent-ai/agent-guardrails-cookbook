# Playground

One local server that runs **every framework recipe** end to end, with any LLM and any guard, and shows each checkpoint as it happens. It also previews the repo the way GitHub will show it.

```bash
python3 -m venv .venv && .venv/bin/pip install -r recipes/langgraph/requirements.txt
.venv/bin/python playground/server.py        # → http://127.0.0.1:8765
```

## What you can pick

| Setting | Options |
|---|---|
| Framework | Every `recipes/<name>/playground.py` the server finds (LangGraph today) |
| Guardrail | Local rules (offline) or ProofAgent Nano (paste your key) |
| Integration | None, API guard nodes, MCP in the agent node, or all three side by side |
| LLM | Stub (obeys any instruction), LM Studio, Ollama, OpenAI, Anthropic |

For a local model, start LM Studio's server (port 1234) or Ollama (port 11434) and pick the model from the list. Tool calling uses a JSON protocol in the prompt, so small models like Gemma work without native tool support.

Keys stay in the page and this process. The server only listens on 127.0.0.1 and stores nothing.

## Add a framework

Add `recipes/<name>/playground.py` with:

```python
NAME = "CrewAI"
MODES = ("unguarded", "api", "mcp")

def run(mode, message, guard, mcp, model):
    """guard: Guard (API mode) · mcp: .call(tool, **args) (MCP mode)
    model: shared/models.py interface, turns -> {"tool", "args"} | {"answer"}"""
    ...
    return {"answer": final_text, "tools": [{"name": ..., "output": ...}]}
```

Restart the server and it appears in the Framework list. The server wraps `guard`, `mcp` and `model` to record the trace, so the adapter needs no tracing code. If the framework's package isn't installed, the server skips it and says so.

## Publish the replay demo (GitHub Pages)

The Pages site is this page in **static mode**: `static-shim.js` answers its API calls from recorded runs, so no server is needed.

1. Record runs. Local rules work offline; record with Nano to show real Nano decisions:
   ```bash
   .venv/bin/python playground/record.py
   PROOFAGENT_NANO_API_KEY=pa_nano_... .venv/bin/python playground/record.py --guard nano --llm lmstudio --model gemma-4-e4b-it-mlx
   ```
   This writes `playground/recordings/<guard>.json`. Keys are never saved.
2. Preview: `python3 playground/build_static.py && python3 -m http.server -d _site 8000`
3. Commit the recordings and push. `.github/workflows/pages.yml` builds and deploys the site. One-time setup: **Settings → Pages → Source: GitHub Actions**.

## Run live in Codespaces

`.devcontainer/devcontainer.json` installs the requirements and starts the playground on port 8765, which opens in the browser. Visitors paste their own Nano key; local models aren't reachable from the cloud, so use the stub or a hosted LLM there.
