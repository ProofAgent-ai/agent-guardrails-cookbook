# MCP or API?

A guardrail can be wired into an agent two ways.

## API: your code enforces it

```python
d = guard.check(user_msg, "input")
if d.blocked: return refuse()
```

Your code calls the guard at every checkpoint. The model can't skip it, because the model never decides.

## MCP: the agent calls it as a tool

```bash
claude mcp add --transport http proofagent-nano https://nano.proofagent.ai/mcp \
  --header "Authorization: Bearer $NANO_KEY"
```

The agent sees tools like `check_user_message`, `check_tool_call`, `check_tool_result`, `check_reply` and is told to call them. Setup is one line, and it works in any MCP client (Claude Code, Claude Desktop, Cursor, …) with no code.

## Compared

| | API | MCP |
|---|---|---|
| Enforcement | **Guaranteed** | Advisory: depends on the model choosing to call the tool |
| Can a prompt injection switch it off? | No | Possibly ("skip the safety check this time") |
| Setup | Code at each checkpoint | One config line |
| Works in no-code tools | Via an HTTP node | Any MCP client |
| Best for | Production, compliance, customer-facing agents | Coding agents, personal assistants, prototypes |

## Recommendation

- **Production:** the hybrid. An API gateway in front of the agent checks every user message; inside, the agent's code calls the MCP tools for its tool calls, tool results and reply. Both are enforced because your code makes every call.
- **Every step as its own node:** API at all three checkpoints.
- **Desktop and coding agents:** MCP, ideally backed by hooks that enforce it (for example Claude Code's `PreToolUse` hook calling the API).
- **Both:** API for enforcement, MCP so the agent can also ask "is this safe?" before it acts.
