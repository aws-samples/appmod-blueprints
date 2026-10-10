# a2a-chat-ui

A minimal, **Keycloak-gated** web chat front-end for an OAP Strands agent exposed
over **A2A** (JSON-RPC). It authenticates the browser user via Keycloak
(Resource Owner Password Credentials), then proxies chat turns to the agent's A2A
endpoint. Long-running turns use an **async job + poll** pattern so they survive
edge (CloudFront/ALB) idle timeouts.

Features: colored **Markdown rendering** (headings, code, GFM tables, lists,
links), **local history persistence** (survives refresh), and **contextual
follow-up suggestions**.

## Configuration (all via env)

| Env | Default | Purpose |
|---|---|---|
| `AGENT_A2A_URL` | `http://agent-stable.default.svc.cluster.local:8083/` | agent A2A JSON-RPC URL |
| `KEYCLOAK_TOKEN_URL` | — | Keycloak token endpoint (public URL the browser reaches) |
| `KEYCLOAK_CLIENT_ID` | `a2a-chat` | public client with Direct Access Grants |
| `KEYCLOAK_CLIENT_SECRET` | _(empty)_ | set for a confidential client |
| `SESSION_SECRET` | random/pod | HMAC key for the session cookie |
| `SESSION_TTL` | `3600` | session lifetime (s) |
| `COOKIE_SECURE` | `false` | set `true` behind HTTPS/CloudFront |
| `APP_TITLE` | `A2A Agent Chat` | UI title/heading |
| `AGENT_LABEL` | `agent` | avatar label |
| `APP_INTRO` | generic | intro line shown above the chat |
| `PORT` | `8080` | listen port |

The UI reads `/config` at load to apply `APP_TITLE` / `AGENT_LABEL` / `APP_INTRO`,
so a single image is rebranded purely via env.

## Build & run

```bash
docker build -t a2a-chat-ui .
docker run -p 8080:8080 -e AGENT_A2A_URL=... -e KEYCLOAK_TOKEN_URL=... a2a-chat-ui
```

Serves fine at `/` or behind a path prefix (all fetches are relative to
`location.pathname`).
