# n8n

🚧 **Planned.** Want to build it? See [CONTRIBUTING.md](../../CONTRIBUTING.md).

Where the three checkpoints go in n8n:

- **Input:** an HTTP Request node calling the guard right after the trigger, then an IF node on the action.
- **Tools:** the same check around each tool or HTTP node the AI Agent node uses.
- **Output:** a final check before the reply node.
- Ships as an importable workflow JSON.

Layout when done: `api/` (enforced via `POST /v1/scan`), `mcp/` (agent calls the guard as a tool), `attack_demo.py`.
