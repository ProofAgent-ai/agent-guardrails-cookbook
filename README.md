# Agent Guardrails Cookbook

**Build secure AI agents with guardrails at every checkpoint.**

Practical, framework-agnostic recipes for protecting AI agents against prompt injection, jailbreaks, PII exposure, unsafe tool execution, and data exfiltration, through MCP or API.

[![Live demo](https://img.shields.io/badge/▶_live_demo-GitHub_Pages-4f46e5)](https://proofagent-ai.github.io/agent-guardrails-cookbook/)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/ProofAgent-ai/agent-guardrails-cookbook?quickstart=1)

**[▶ Try the playground](https://proofagent-ai.github.io/agent-guardrails-cookbook/)**: watch real attacks hit an agent and see each checkpoint stop them, in your browser. **[Run it live](https://codespaces.new/ProofAgent-ai/agent-guardrails-cookbook?quickstart=1)** with your own message and key in one click.

---

## The pattern: three checkpoints

Every agent, in every framework, has the same three places where untrusted text crosses a boundary:

```
            ┌──────────── 1. INPUT ────────────┐
 user ────▶ │ check the message before acting  │ ────▶ agent / LLM
            └──────────────────────────────────┘          │
                                                          ▼
            ┌──────────── 2. TOOLS ────────────┐   wants to call a tool
            │ check the call before it runs    │ ◀────────┘
            │ check the result before reading  │ ────▶ back to the agent
            └──────────────────────────────────┘          │
                                                          ▼
            ┌──────────── 3. OUTPUT ───────────┐
 user ◀──── │ check the reply before sending   │ ◀──── final answer
            └──────────────────────────────────┘
```

Guard all three and an attacker has nowhere to get in. See [docs/three-checkpoints.md](docs/three-checkpoints.md).

## Quick start (60 seconds, no key needed)

```bash
git clone https://github.com/ProofAgent-ai/agent-guardrails-cookbook
cd agent-guardrails-cookbook
python3 recipes/00-plain-python/agent.py
```

This runs a small agent against real attacks using the built-in **local guard** (regex rules, no network). Then switch to a production guardrail. Get a free ProofAgent Nano key (250 calls a month) at [app.proofagent.ai](https://app.proofagent.ai):

```bash
cp .env.example .env          # add your key from app.proofagent.ai
export $(cat .env | xargs)
python3 recipes/00-plain-python/agent.py --guard nano
```

## Playground

Three ways to use it:

| | Where | What you can do |
|---|---|---|
| **Replay demo** | [GitHub Pages](https://proofagent-ai.github.io/agent-guardrails-cookbook/) | Watch recorded real runs of every scenario. Nothing to install |
| **Live in the cloud** | [Open in Codespaces](https://codespaces.new/ProofAgent-ai/agent-guardrails-cookbook?quickstart=1) | The full playground starts by itself: your own messages, your Nano key, hosted LLMs |
| **Live on your machine** | Below | Everything, including local models in LM Studio or Ollama |

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python playground/server.py      # → http://127.0.0.1:8765
```

Pick a framework, a guard (local or ProofAgent Nano), an integration (API or MCP) and any LLM, including a local model in LM Studio or Ollama, and watch every checkpoint. See [playground/README.md](playground/README.md).

## Recipes

| Framework | API | MCP | Status |
|---|---|---|---|
| [Plain Python (reference)](recipes/00-plain-python) | ✅ | — | Ready |
| [LangGraph](recipes/langgraph) | ✅ | ✅ | Ready |
| [CrewAI](recipes/crewai) | 🚧 | 🚧 | Planned |
| [OpenAI Agents SDK](recipes/openai-agents) | 🚧 | 🚧 | Planned |
| [Claude Agent SDK](recipes/claude-agent-sdk) | 🚧 | 🚧 | Planned |
| [n8n](recipes/n8n) | 🚧 | 🚧 | Planned |
| **Your framework** | | | [Add a recipe →](CONTRIBUTING.md) |

Every recipe follows the same layout: a README with a diagram, an `api/` and an `mcp/` version, and an attack demo showing the agent **unguarded** and **guarded**.

## MCP or API?

| | API (`POST /v1/scan`) | MCP (`/mcp`) |
|---|---|---|
| Who decides to check | **Your code**, every time | **The agent**, by calling a tool |
| Guarantee | Enforced: nothing skips a checkpoint | Advisory: a model can forget or be tricked into skipping |
| Best for | Production pipelines, compliance | Coding agents, desktop assistants, fast prototyping |
| Setup | A few lines of code | One line of config |

**Rule of thumb:** use the API to *enforce*, MCP to *assist*, both when you can. Full guide: [docs/mcp-vs-api.md](docs/mcp-vs-api.md).

## Bring your own guard

Recipes depend on a tiny `Guard` interface ([guards/python/guard.py](guards/python/guard.py)), not on a vendor:

```python
from guard import get_guard
guard = get_guard()                              # "local" or "nano"
d = guard.check(text, checkpoint="input")
if d.blocked: return refuse()
text = d.text                                    # masked / sanitised text
```

Built in: `LocalGuard` (free, offline, for learning) and `NanoGuard` ([ProofAgent Nano](https://nano.proofagent.ai): 134 PII types, 41 AI risks, English/French/Arabic, regulation mapping). Adapters for other guardrails are welcome.

## Attack corpus

[attacks/corpus.jsonl](attacks/corpus.jsonl) holds labelled test cases: direct and indirect injection, jailbreaks, PII, exfiltration, unsafe tool calls, in several languages. Run every guard against it:

```bash
python3 tests/test_corpus.py            # local guard
python3 tests/test_corpus.py --guard nano
```

## Threat coverage

Mapped to the [OWASP Top 10 for LLM Applications](https://genai.owasp.org/): LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM06 Excessive Agency, LLM07 System Prompt Leakage.

## Contributing

New recipes, attacks and guard adapters are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. Maintained by [ProofAgent](https://proofagent.ai).
