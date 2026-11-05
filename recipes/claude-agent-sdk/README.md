# Claude Agent SDK

🚧 **Planned.** Want to build it? See [CONTRIBUTING.md](../../CONTRIBUTING.md).

Where the three checkpoints go in Claude Agent SDK:

- **Input:** check the prompt before `query()`.
- **Tools:** `PreToolUse` and `PostToolUse` hooks.
- **Output:** check the final message before returning it.
- **MCP:** add the guard as a remote MCP server so the agent can call `check_*` tools itself.

Layout when done: `api/` (enforced via `POST /v1/scan`), `mcp/` (agent calls the guard as a tool), `attack_demo.py`.
