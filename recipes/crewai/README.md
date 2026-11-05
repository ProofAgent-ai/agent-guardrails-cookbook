# CrewAI

🚧 **Planned.** Want to build it? See [CONTRIBUTING.md](../../CONTRIBUTING.md).

Where the three checkpoints go in CrewAI:

- **Input:** check the task inputs before `crew.kickoff()`.
- **Tools:** wrap each tool's `_run` so calls and results pass through the guard.
- **Output:** a task guardrail on each task's output.

Layout when done: `api/` (enforced via `POST /v1/scan`), `mcp/` (agent calls the guard as a tool), `attack_demo.py`.
