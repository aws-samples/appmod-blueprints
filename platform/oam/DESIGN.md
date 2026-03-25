# OAM Component Design Decisions

This document captures architectural and design decisions for the KubeVela OAM components in this platform: **agent** (A2A) and **mcp-server** (MCP).

---

## Shared Decisions (Both Components)

### Blue-Green Deployment via Argo Rollouts

Both components use Argo Rollouts with blue-green strategy as the primary workload resource (not Deployment).

**How it works**:
- The Rollout creates two Services: `<name>-stable` (active) and `<name>-preview`.
- On image update, the new version deploys to preview. After promotion, it becomes stable.
- Argo Rollouts manages which ReplicaSet backs which service via selector injection.
- Default: auto-promotion enabled, 10s promotion delay, 30s scale-down delay.

**Gateway API plugin**: kgateway/agentgateway supports the Argo Rollouts Gateway API traffic router plugin (`argoproj-labs/gatewayAPI`) for canary with traffic splitting. For blue-green, the standard service selector approach works without the plugin since backends always point to the stable service.

**Reference**: [kgateway Argo Rollouts integration](https://kgateway.dev/docs/envoy/main/integrations/argo)

### KubeVela OAM Pattern

Both components follow the same structure:
- `.cue` file defines the component template with parameters
- A `ComponentDefinition` YAML wraps the CUE template for registration with KubeVela
- An `Application` YAML instantiates the component with specific properties

### Gateway Registration

Both components optionally register with agentgateway via HTTPRoute (`registerWithGateway: true` by default). The route attaches to the `agentgateway-proxy` Gateway in `agentgateway-system`.

### Service Port Convention

Services expose port 80 externally, mapping to the container's application port. This matches agentgateway documentation conventions and simplifies backend configuration.

---

## Agent Component (`agent.cue`)

The `agent` component deploys A2A (Agent-to-Agent) protocol agents.

### Generated Resources

1. **Argo Rollout** — blue-green deployment
2. **Stable Service** — `appProtocol: kgateway.dev/a2a`, port 8083
3. **Preview Service** — blue-green preview
4. **Agent Card ConfigMap** — metadata for agent discovery
5. **HTTPRoute** — routes `/<name>` to stable service (optional)

### LLM Access via Gateway (Not Direct Bedrock)

**Decision**: Agents access LLMs through a centralized LiteLLM proxy gateway, not directly via AWS Bedrock credentials.

**Why**:
- No AWS credentials needed in agent pods
- Centralized access control, monitoring, and cost tracking
- Support for multiple LLM providers behind a single endpoint
- Simplified agent deployment

Default config points to `http://litellm-proxy.agentgateway-system.svc.cluster.local:4000`.

### Container Port: 8083

Agents listen on port 8083 (A2A protocol convention). The stable service maps port 8083 → 8083 with `appProtocol: kgateway.dev/a2a`.

### MCP Server References

Agents reference MCP servers by name. The `MCP_SERVERS` env var is constructed from the `mcpServers` parameter, building service URLs as `http://<name>.<namespace>.svc.cluster.local:<port>`.

---

## MCP Server Component (`mcp-server.cue`)

The `mcp-server` component deploys Model Context Protocol servers with agentgateway integration.

### Generated Resources

1. **Argo Rollout** — blue-green deployment
2. **Stable Service** — `appProtocol: agentgateway.dev/mcp`, port 80 → containerPort
3. **Preview Service** — blue-green preview
4. **AgentgatewayBackend** — static target to stable service FQDN
5. **HTTPRoute** — registers at `/mcp/<name>` (optional)
6. **AgentgatewayPolicy** — tool-level CEL authorization (optional)

### Per-Server Routing (Not Federation)

**Decision**: Each MCP server gets its own HTTPRoute at `/mcp/<name>`, its own AgentgatewayBackend, and its own namespace.

**Rejected alternative**: Agentgateway supports federation — a single AgentgatewayBackend with multiple targets at one `/mcp` endpoint. Tools from all servers are returned on `tools/list`, prefixed with the target name (e.g., `weather_get_forecast`).

**Why we rejected federation**:
- At scale (100+ MCP servers, dozens of tools each), `tools/list` returns 1000+ tools — bloating agent context windows, increasing cost, and causing confusion.
- Teams deploy MCP servers independently in separate namespaces. A centralized backend becomes a coordination bottleneck.
- Per-server routing gives agents scoped tool lists — they connect only to the servers they need.
- Tool names remain clean (no target prefix).

**Tradeoff**: Agents need multiple MCP connections instead of one. This is acceptable — it provides isolation and scoping.

**Reference**: [agentgateway MCP federation docs](https://agentgateway.dev/docs/kubernetes/latest/tutorials/mcp-federation), [Virtual MCP docs](https://agentgateway.dev/docs/kubernetes/main/mcp/virtual/)

### Static Backend (Not Dynamic)

**Decision**: Use `static` targets in AgentgatewayBackend pointing to the stable service FQDN.

**Rejected alternative**: Dynamic backends use label selectors to discover services at runtime.

**Why**:
- Dynamic backends still require a Service — they don't bypass the Service layer.
- With Argo Rollouts blue-green, we need to explicitly target the stable service. Dynamic label selectors could match both stable and preview services.
- Static gives deterministic routing through the blue-green lifecycle.

**Reference**: [agentgateway Static MCP](https://agentgateway.dev/docs/kubernetes/latest/mcp/static-mcp/), [Dynamic MCP](https://agentgateway.dev/docs/kubernetes/latest/mcp/dynamic-mcp/)

### Default Container Port: 8000

FastMCP (the standard Python MCP server library) defaults to port 8000 for StreamableHTTP. Overridable via `containerPort` parameter.

### StreamableHTTP Protocol (Not SSE)

**Decision**: Default MCP protocol is `StreamableHTTP`, configurable to `SSE`.

**Why**: StreamableHTTP is the modern MCP transport. SSE is legacy. Agentgateway's dynamic backend only supports StreamableHTTP. Defaulting to StreamableHTTP ensures forward compatibility.

### Component Scope: Local Only

**Decision**: `mcp-server` handles locally deployed MCP servers (Deployment + Service + Backend + Route).

**Remote MCP servers** (external endpoints via HTTPS) only need an AgentgatewayBackend with a static host pointing to the external FQDN, plus an HTTPRoute. No Deployment or Service. This should be a separate component type (e.g., `mcp-remote`) if needed.

**Reference**: [agentgateway Connect via HTTPS](https://agentgateway.dev/docs/kubernetes/latest/mcp/https/)

### Authentication & Authorization

Tool-level authorization is opt-in via `authPolicy` parameter, generating an `AgentgatewayPolicy` targeting the AgentgatewayBackend.

**Two levels of auth in agentgateway**:

| Level | Policy Target | Purpose |
|---|---|---|
| **JWT auth** | Gateway or HTTPRoute | Validates JWT tokens, optional claim-based RBAC for server access |
| **Tool access** | AgentgatewayBackend | CEL expressions filtering which tools are visible per JWT claims |

**JWT auth** is configured once at the Gateway level by the platform team (not per MCP server).

**Tool access** is per-backend, configured by the MCP server owner:

```yaml
authPolicy:
  action: Allow
  matchExpressions:
    - 'jwt.sub == "alice" && mcp.tool.name == "get_time"'
    - 'jwt.team == "ops"'
```

CEL expressions use OR logic — any matching expression grants access.

**MCP Auth vs JWT Auth**: Use JWT auth for service-to-service / static clients. Use MCP auth for interactive MCP clients (MCP Inspector, VS Code, Claude Code) that need dynamic OAuth discovery.

**Reference**: [agentgateway JWT auth](https://agentgateway.dev/docs/kubernetes/latest/mcp/mcp-access/), [Tool access](https://agentgateway.dev/docs/kubernetes/latest/mcp/tool-access/)

### Route Path Convention

Each MCP server is exposed at `/mcp/<name>`. Agents connect via `http://<gateway-address>/mcp/<name>`.
