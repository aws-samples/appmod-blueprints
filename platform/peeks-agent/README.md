# platform/peeks-agent — the PEEKS read-only agent (demo instance)

This is the **PEEKS-specific instance** of the OAP agent stack. The reusable
building blocks live upstream in **[open-agentic-platform](https://github.com/awslabs/open-agentic-platform)**
(`applications/{a2a-chat-ui,skills-mcp,eks-mcp,strands-agent-base}`); this
directory only carries what is specific to PEEKS.

## Contents

| Path | What |
|---|---|
| `deploy/peeks-agent-app.yaml` | the **single KubeVela Application** (agent + skills-mcp + eks-read-mcp + chat-ui + ACK access entries). One `kubectl apply` deploys the whole stack, ConfigMap included. |
| `deploy/BUNDLE.md` | prerequisites, parameters, apply procedure, MCP transport rules. |
| `skills-overlay/Dockerfile` | bakes `.kiro/skills` into the generic OAP `skills-mcp` image. |
| `buildspec.yaml` | CodeBuild: build + push the 4 images (pinned) to ECR. |

## How the PEEKS skills reach the agent

The agent image is the **generic** OAP `strands-agent`. It does **not** contain the
skills. It connects (via the AgentGateway) to the **skills-mcp** server and calls
`get_skill` / `list_skills`. So the PEEKS skills are baked into the **skills-mcp**
image — via `skills-overlay/Dockerfile` (`FROM oap/skills-mcp` + `COPY .kiro/skills
/payload/skills`) — **not** into the agent image. The agent is wired to it purely
by config (`mcpServers: [skills-mcp, eks-read-mcp]` in the Application).

## Images (built to the env's ECR, e.g. `…/peeks-e2e/*`)

| Image | Source |
|---|---|
| `chat-ui` | OAP `applications/a2a-chat-ui` (generic, env-branded to PEEKS) |
| `eks-mcp` | OAP `applications/eks-mcp` (supergateway + awslabs eks-mcp-server) |
| `skills-mcp` | OAP `applications/skills-mcp` **+** this `skills-overlay` (bakes `.kiro/skills`) |
| agent | OAP `applications/strands-agent-base` (unchanged) |

## Deploy

See `deploy/BUNDLE.md`. In short: build/push the images (`buildspec.yaml`),
substitute the 3 placeholders, then
`kubectl -n peeks-agent apply -f deploy/peeks-agent-app.yaml`.
