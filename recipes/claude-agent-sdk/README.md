# Guarding a Claude Agent SDK agent

Add input, tool and output guardrails to an agent on the **Claude Agent SDK** using its **`PreToolUse` and `PostToolUse` hooks**, through the API, MCP or the hybrid. The shop's tools run as an in-process MCP server built from `shared/agent/tools.json`, with Claude's built-in tools (Bash, files) switched off.

## Try it

```bash
pip install -r requirements.txt
python test_hooks.py                   # 14 hook tests in the SDK's hook format (offline)
python attack_demo.py                  # 9 attacks × 4 integrations (offline, simulated loop)
python agent.py --live --mode hybrid "How long does shipping take?"   # real SDK, uses your Claude account
```

**Offline vs live.** The SDK runs the Claude Code CLI against Anthropic's API, so a real run needs a signed-in Claude account. The offline demo calls **the same hook functions** from a small loop that follows the SDK's contract (the model proposes a tool, `PreToolUse` may deny, the tool runs, `PostToolUse` may rewrite), so you can see every checkpoint without an account. `--live` runs the real SDK.

| Attack | Unguarded | API · MCP · Hybrid |
|---|---|---|
| Direct injection | 🚨 email sent | ✅ refused at checkpoint 1 |
| Hidden instruction in a help page | 🚨 email sent to x@evil.io | ✅ instruction removed at 2b |
| Email to an outside address | 🚨 data sent outside | ✅ denied at 2a with a reason |
| Order record with card and email | 🚨 personal data exposed | ✅ masked at 2b |

## Where the checkpoints go

```mermaid
flowchart LR
  U([user]) --> C1[1 · input check<br/>before query]
  C1 -->|BLOCK| X([refuse])
  C1 --> Q
  subgraph Q[query · Claude Code]
    A[Claude] -->|tool_use| P[2a · PreToolUse]
    P -->|permissionDecision: deny| A
    P --> T[mcp__shop__tool]
    T --> O[2b · PostToolUse]
    O -->|updatedMCPToolOutput| A
  end
  Q --> C3[3 · output check]
  C3 --> Y([reply])
  classDef g fill:#fde68a,stroke:#b45309,color:#000
  class C1,P,O,C3 g
```

| Checkpoint | Hook | File |
|---|---|---|
| 1 Input | before `query()` (it can mask; `UserPromptSubmit` can only block or add context) | [`agent.py`](agent.py) |
| 2a Tool call | `PreToolUse`: tool policy, then the guardrail → `permissionDecision: "deny"` with a reason | [`claude_hooks.py`](claude_hooks.py) |
| 2b Tool result | `PostToolUse` → `updatedMCPToolOutput` replaces what Claude reads | [`claude_hooks.py`](claude_hooks.py) |
| 3 Output | on the final `ResultMessage` | [`agent.py`](agent.py) |

```python
options = ClaudeAgentOptions(
    hooks=make_hooks(mcp=get_mcp("nano"), policy=ToolPolicy.load()),
    mcp_servers={"shop": create_sdk_mcp_server("shop", tools=sdk_tools())},
    allowed_tools=["mcp__shop__fetch_help_page", "mcp__shop__lookup_order", "mcp__shop__send_email"],
    tools=[],                      # no Bash, no file access: only the shop's tools
)
```

## Gotchas

- **Turn off what you don't use.** `tools=[]` removes Claude Code's built-in tools; `setting_sources=[]` ignores local settings files.
- **Matchers:** the hooks match `mcp__shop__.*`, so they only see this agent's tools.
- **Guardrail reasons:** a guard that explains its *allow* decisions (Nano does) must not be mistaken for a deny. `test_hooks.py` checks exactly that.

## Files

```
claude-agent-sdk/
├── agent.py          the guarded agent: live query() and the offline loop
├── claude_hooks.py   ← copy into your project: PreToolUse / PostToolUse hooks for 2a and 2b
├── test_hooks.py     hook unit tests in the SDK's input format
├── attack_demo.py    every scenario × every integration (exit 1 on any failure)
├── playground.py     adapter for the local playground (offline loop)
└── requirements.txt  claude-agent-sdk 0.2.178
```
