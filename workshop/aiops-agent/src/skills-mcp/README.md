# skills-mcp

A tiny **FastMCP** server that turns a directory of *skills* (each a folder with a
`SKILL.md` step-by-step method) into MCP tools:

- `list_skills()` — list available skills + one-line descriptions
- `get_skill(name)` — return the full `SKILL.md` (+ an index of referenced files)

Skills live under `$PAYLOAD_DIR/skills` (`PAYLOAD_DIR` default `/payload`).

## Run **stateless** behind an L7 gateway

FastMCP must run **stateless** when fronted by an AgentGateway (each POST is
self-contained; no persistent SSE stream to cut). This image sets
`FASTMCP_STATELESS_HTTP=true` and `FASTMCP_JSON_RESPONSE=true` by default.

## Provide your own skills

```dockerfile
FROM <registry>/skills-mcp:latest
COPY my-skills/ /payload/skills/
```

…or mount a volume / ConfigMap at `/payload/skills`. The bundled
`example-skills/` are only a placeholder so the image runs standalone.
