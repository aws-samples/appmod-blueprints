# workshop/aiops-agent — the PEEKS AIOps agent (demo instance)

This is the **PEEKS-specific instance** of the OAP agent stack. The reusable
building blocks live upstream in **[open-agentic-platform](https://github.com/awslabs/open-agentic-platform)**
(`applications/{a2a-chat-ui,skills-mcp,eks-mcp,strands-agent-base}`); this
directory only carries what is specific to PEEKS.

## Contents

| Path | What |
|---|---|
| `chart/` | the Helm chart that renders the **single KubeVela Application** (agent + skills-mcp + eks-read-mcp + chat-ui + incident-bridge + ACK access entries). This is the **GitOps source of truth**, delivered as the `aiops-agent` addon via the fleet-config overlay. |
| `chart/files/aiops-agent-app.yaml` | the canonical OAM Application manifest (the only copy); the chart substitutes the `REPLACE_*` tokens at render time. |
| `chart/README.md` | chart values, image pinning, enable/disable, and placeholder reference. |
| `skills-overlay/Dockerfile` | bakes `.kiro/skills` into the generic OAP `skills-mcp` image. |
| `src/` | in-repo sources for the generic services (`a2a-chat-ui`, `eks-mcp`, `gitlab-mcp`, `skills-mcp`, `incident-bridge`) so images build without a cross-repo OAP clone. |
| `buildspec.yaml` / `buildspec-public-ecr.yaml` | CodeBuild: build + push the images (pinned) to a private ECR / the public demo registry. |

## How the PEEKS skills reach the agent

The agent image is the **generic** OAP `strands-agent`. It does **not** contain the
skills. It connects (via the AgentGateway) to the **skills-mcp** server and calls
`get_skill` / `list_skills`. So the PEEKS skills are baked into the **skills-mcp**
image — via `skills-overlay/Dockerfile` (`FROM oap/skills-mcp` + `COPY .kiro/skills
/payload/skills`) — **not** into the agent image. The agent is wired to it purely
by config (`mcpServers: [skills-mcp, eks-read-mcp]` in the Application).

## Images (built to the env's ECR, e.g. `…/<your-ecr-namespace>/*`)

| Image | Source |
|---|---|
| `chat-ui` | OAP `applications/a2a-chat-ui` (generic, env-branded to PEEKS) |
| `eks-mcp` | OAP `applications/eks-mcp` (supergateway + awslabs eks-mcp-server) |
| `skills-mcp` | OAP `applications/skills-mcp` **+** this `skills-overlay` (bakes `.kiro/skills`) |
| `incident-bridge` | this `src/incident-bridge` (SQS→A2A autonomous incident forwarder) |
| agent | OAP `applications/strands-agent-base` (unchanged) |

## Deploy

This addon is delivered via **GitOps**, not an imperative `kubectl apply`. It is
gated OFF by default and enabled by the `enable_aiops_agent` cluster-secret label,
emitted from the fleet-config overlay (`overlays/environments/control-plane/enabled-addons.yaml`).
See `chart/README.md` for enable/disable, image pinning, and the `REPLACE_*`
placeholder reference. To publish your own images first, run `buildspec.yaml`
(private ECR) or `buildspec-public-ecr.yaml` (public), then point the chart at them
via `images.imageRegistry`/`imageTag` in the overlay (or the `aiops_agent_img_*`
cluster-secret annotations).
