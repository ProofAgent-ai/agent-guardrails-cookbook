# OpenAI Agents SDK

🚧 **Planned.** Want to build it? See [CONTRIBUTING.md](../../CONTRIBUTING.md).

Where the three checkpoints go in OpenAI Agents SDK:

- **Input:** an `input_guardrail` on the agent.
- **Tools:** wrap function tools so calls and results pass through the guard.
- **Output:** an `output_guardrail` on the agent.

Layout when done: `api/` (enforced via `POST /v1/scan`), `mcp/` (agent calls the guard as a tool), `attack_demo.py`.
