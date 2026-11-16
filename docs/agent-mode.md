# Agent mode: use your own AI CLI as the tutor's brain

Wysp can run without any language model of its own. An AI agent you already use and pay for (Claude Code, kiro-cli, or any MCP client) connects to the Core's MCP endpoint, does the thinking, and calls the Wysp tools. The agent keeps doing its normal work; Wysp adds the application's live state, the board, voice and captions, and the permission gate.

```
Claude Code / kiro-cli / any MCP client ──MCP (HTTP, localhost, token)──┐
                                                                       ▼
Panel (board, captions, voice, approvals) ◄── Wysp Core ◄── adapter (Blender, IntelliJ, ...)
```

## Start

1. `uv run wysp serve --llm external` (add `--mcp` to serve `/mcp` next to a Core-owned LLM, for experiments).
2. `uv run wysp mcp-config` prints the setup for your client. The token is never printed; it is read from `~/.wysp/token`:
   - PowerShell: `$env:WYSP_TOKEN = (Get-Content "$env:USERPROFILE\.wysp\token" -Raw).Trim()`
   - Claude Code: `claude mcp add --transport http wysp http://127.0.0.1:8765/mcp --header "Authorization: Bearer $env:WYSP_TOKEN"`
   - kiro-cli (`.kiro/settings/mcp.json`):
     ```json
     {"mcpServers": {"wysp": {"url": "http://127.0.0.1:8765/mcp",
       "headers": {"Authorization": "Bearer ${WYSP_TOKEN}"}}}}
     ```
3. Open the Panel (http://127.0.0.1:8765) and the application (IDE, Blender...) with its adapter connected.
4. Tell your agent: "Use the Wysp tools to teach me what is in my project." Or type in the Panel, and tell the agent to "run the Wysp loop": it calls `wait_for_user`, answers each message with `narrate`, and calls `wait_for_user` again.

## Tools

The same closed set the Core's own LLM gets (`observe`, `show_entities`, `add_concept`, `annotate`, `narrate`, `highlight`, `propose_action`, `lookup_concept`, `ask_clarification`), plus two for agents:

| Tool | Purpose |
|---|---|
| `get_tutor_context` | The tutoring rules and the connected application's description, action catalog and current situation. Call it first. |
| `wait_for_user` | Messages (typed or spoken) and interruptions from the Panel. Returns after at most 55 s with an empty list; call again. |

## Trust model (unchanged)

- Every tool runs through the same `ToolBox` as in normal mode: provenance validation (an agent can never create an `observed` node), permission gate, post-condition verification, undo, audit log.
- `propose_action` blocks until the user approves in the Panel. There is no tool that approves, executes code, or talks to an adapter directly.
- `/mcp` accepts only requests with the pairing token (`Authorization: Bearer ...` or `X-Wysp-Token`), checks the Origin against the same allowlist as the other endpoints, and is bound to `127.0.0.1` like the rest of the Core.
- Tool results and application data are data, not instructions. Your agent may have shell access that Wysp's own LLM never had: keep its normal permission prompts on.
- Nothing about the conversation with your agent goes through Wysp. The Core only sees tool calls and the user's Panel messages, as in normal mode.

## Limits

- The agent, not the Core, drives the turn. Wysp's single-request turn loop, retries and history do not apply; quality depends on the agent following `get_tutor_context`.
- Latency depends on the agent. Voice feels slower than with a fast hosted model.
- The agent must be waiting in `wait_for_user` to answer Panel messages. Without a connected agent, the Panel says so.
- Check your provider's terms before using a subscription through an automated loop.
