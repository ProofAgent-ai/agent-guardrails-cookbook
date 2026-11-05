# The three checkpoints

Untrusted text enters an agent in three places. Guard each one.

| # | Checkpoint | What arrives | Main threats | What to do |
|---|---|---|---|---|
| 1 | **Input** | The user's message | Direct prompt injection, jailbreaks, PII the model shouldn't see | `BLOCK` → refuse. `MASK` → pass the masked text on. |
| 2a | **Tool call** | What the agent *wants* to do | Excessive agency, destructive commands, data sent out | Check before it runs. `BLOCK`/`REVIEW` → don't run it. |
| 2b | **Tool result** | Web pages, files, emails, API responses | **Indirect prompt injection** (the most common real attack) | Sanitise: strip the instruction, keep the useful content. |
| 3 | **Output** | The final reply | PII leaks, system-prompt leaks, harmful content | `MASK` → send the masked text. `BLOCK` → safe reply. |

## Rules

1. **Fail closed.** If the guard can't be reached, treat it as `BLOCK`. Loosen this only on low-risk paths.
2. **Never trust tool results.** They're written by strangers. Checkpoint 2b catches more real attacks than checkpoint 1.
3. **Check the call, not just the text.** "Send email to x@evil.io" is harmless as text and dangerous as a tool call.
4. **Use the masked text downstream.** Masking only helps if the model receives the masked version.
5. **Log decisions, not secrets.** Keep the action and reasons; don't log the original PII.

## Mapped to OWASP LLM Top 10

| Checkpoint | OWASP |
|---|---|
| Input | LLM01 Prompt Injection |
| Tool call | LLM06 Excessive Agency |
| Tool result | LLM01 (indirect) |
| Output | LLM02 Sensitive Information Disclosure, LLM07 System Prompt Leakage |
