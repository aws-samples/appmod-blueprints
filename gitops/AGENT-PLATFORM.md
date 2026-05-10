# Agent Platform on appmod-blueprints

Enable an AI agent platform on the appmod-blueprints hub cluster with a single toggle. All agent platform charts and configurations live in the [sample-agent-platform-on-eks](https://github.com/aws-samples/sample-agent-platform-on-eks) repo (`main` branch).

## How It Works

```
appmod-blueprints                          sample-agent-platform-on-eks
┌─────────────────────┐                    ┌──────────────────────────────┐
│ registry/agents.yaml│                    │ gitops/addons/               │
│   agent-platform:   │                    │   bootstrap/default/         │
│     enabled: true   │                    │     addons.yaml              │
│                     │                    │   charts/                    │
│ charts/             │                    │     application-sets/        │
│   agent-platform/   │──creates──────────▶│     kagent-setup/            │
│     bootstrap.yaml  │  ArgoCD            │     litellm/                 │
│                     │  Application       │     langfuse/                │
│                     │  pointing to ──────│     kagent-monitoring/       │
│                     │  sample repo       │     agent-gateway/           │
└─────────────────────┘                    │   environments/              │
                                           │     control-plane/           │
                                           │       addons.yaml            │
                                           └──────────────────────────────┘
```

1. Setting `agent_platform: true` in appmod-blueprints `enabled-addons.yaml` triggers the `agent-platform` addon
2. The addon deploys a thin bootstrap chart that creates an ArgoCD **Application** pointing to the sample repo's `application-sets` chart
3. The Application renders the sample repo's `application-sets` chart with `useSelectors: false` and `globalSelectors: {enable_agent_platform: "true"}`, so all generated ApplicationSets match the existing hub cluster secret — no duplicate cluster secret is created
4. Each addon deploys via the ArgoCD EKS Capability to the cluster
5. The cluster uses EKS Auto Mode with Pod Identity for AWS credentials

## What Gets Deployed

All addons are defined in the sample repo and deploy in sync-wave order:

| Wave | Addon | Source | Namespace |
|------|-------|--------|-----------|
| 2 | kagent-crds | OCI: `ghcr.io/kagent-dev/kagent/helm/kagent-crds:0.7.9` | kagent |
| 3 | kagent (operator + UI) | OCI: `ghcr.io/kagent-dev/kagent/helm/kagent:0.7.9` | kagent |
| 3 | kagent-setup (ModelConfig) | Git path chart | kagent |
| 3 | litellm (LLM gateway) | Git path chart | kagent |
| 4 | crossplane-agentcore | Git path chart | crossplane-system |
| 5 | langfuse (LLM tracing + PostgreSQL) | Git path chart | langfuse |
| 5 | jaeger (distributed tracing) | Helm: `jaegertracing/jaeger:3.4.1` | jaeger |
| 5 | prometheus-operator-crds | Helm: `prometheus-community/prometheus-operator-crds:28.0.1` | kagent |
| 6 | kagent-monitoring (ServiceMonitor) | Git path chart | kagent |
| 7 | gateway-api-crds | Git path chart (Job) | agentgateway-system |
| 7 | agentgateway-crds | OCI: `cr.agentgateway.dev/charts/agentgateway-crds:v1.1.0` | agentgateway-system |
| 8 | agentgateway (control plane) | OCI: `cr.agentgateway.dev/charts/agentgateway:v1.1.0` | agentgateway-system |
| 9 | agent-gateway (Gateway + Policies) | Git path chart | agent-core-infra |

The `crossplane-agentcore` addon (wave 4) installs the Bedrock AgentCore Crossplane provider, creates XRDs/Compositions, and provisions Memory, Browser, and Code Interpreter resources in AWS via claims. AgentGateway provides MCP authentication via KeyCloak JWT validation — KeyCloak is already provided by appmod-blueprints.

## Prerequisites

### Pod Identity (automated via Crossplane)

LiteLLM Pod Identity is **automated via Crossplane** using the `crossplane-pod-identity` chart deployed as `additionalResources` alongside the agent-platform addon:

| Identity | IAM Role | Namespace | ServiceAccount | Purpose |
|---|---|---|---|---|
| litellm | `{clusterName}-LiteLLMBedrockRole` | kagent | litellm | Bedrock model invocation |

**Requirement**: Crossplane with AWS IAM and EKS providers must be running on the hub cluster (`enable_crossplane: true` in enabled-addons.yaml).

## Enable the Agent Platform

Edit `gitops/overlays/environments/control-plane/enabled-addons.yaml`:

```yaml
  agent_platform: true
```

That's it. The bootstrap chart auto-derives configuration from the hub cluster secret's existing annotations (`aws_region`, `aws_account_id`, `aws_cluster_name`, `ingress_domain_name`).

To override defaults, add annotations to the hub cluster secret:

| Annotation | Default | Purpose |
|---|---|---|
| `agent_platform_repo_url` | `https://github.com/aws-samples/sample-agent-platform-on-eks.git` | Agent platform repo |
| `agent_platform_repo_revision` | `main` | Agent platform branch |
| `keycloak_issuer_url` | auto-derived from `ingress_domain_name` | KeyCloak issuer URL for JWT validation |

Commit and push. ArgoCD deploys everything automatically.

## Using the Agent Platform

### Chat with Agents (A2A Protocol)

Agents are accessible directly via the A2A (Agent-to-Agent) JSON-RPC protocol. No authentication required for internal cluster access:

```bash
# List available agents
kubectl get agents -n kagent

# Chat with the bedrock-assistant
kubectl run chat --rm -i --restart=Never --image=curlimages/curl -n kagent -- \
  -s -X POST http://bedrock-assistant.kagent.svc.cluster.local:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"msg-1","parts":[{"type":"text","text":"What is 2+2?"}]}}}'

# Chat with the k8s-ops-agent (has kubectl tools)
kubectl run chat --rm -i --restart=Never --image=curlimages/curl -n kagent -- \
  -s -X POST http://k8s-ops-agent.kagent.svc.cluster.local:8080/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"msg-1","parts":[{"type":"text","text":"List all namespaces"}]}}}'
```

### Access MCP Tools via AgentGateway (KeyCloak Auth)

For authenticated access to MCP tool servers through the AgentGateway:

```bash
DOMAIN="<your-ingress-domain>"  # e.g., idp.example.people.aws.dev

# 1. Get a JWT token from KeyCloak (platform realm, mcp-client)
TOKEN=$(curl -s -X POST "https://${DOMAIN}/keycloak/realms/platform/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=mcp-client&username=user1&password=<USER_PASSWORD>" \
  | jq -r .access_token)

# 2. Verify token has groups claim (must include "admin")
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub:.preferred_username, groups:.groups}'

# 3. Connect to MCP servers through the gateway (SSE transport)
curl -N http://agentgateway-proxy.agentgateway-system.svc.cluster.local:8080/sse \
  -H "Authorization: Bearer $TOKEN"

# 4. Without token — should get 401
curl -s -w "%{http_code}" -X POST http://agentgateway-proxy.agentgateway-system.svc.cluster.local:8080/sse
# Output: 401
```

### Architecture Overview

**Path 1: Agent A2A (direct chat, no auth for internal access)**

```
┌──────────┐     ┌───────────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌─────────┐
│  Client  │────▶│  Agent Pod        │────▶│ kagent-controller│     │   LiteLLM   │────▶│ Bedrock │
│  (curl/  │ A2A │  (bedrock-asst    │     │  (session mgmt)  │     │  (proxy)    │     │  (LLM)  │
│   UI)    │     │   or k8s-ops)     │     │                  │     │             │     │         │
└──────────┘     └───────┬───────────┘     └──────────────────┘     └─────────────┘     └─────────┘
                         │  OpenAI-compatible API                           ▲
                         └─────────────────────────────────────────────────┘
```

**Path 2: Authenticated MCP via AgentGateway + KeyCloak**

```
┌──────────┐  1.Get Token  ┌──────────────┐
│  Client  │──────────────▶│  KeyCloak    │
│          │◀──────────────│  (platform   │
│          │   JWT Token   │   realm)     │
└────┬─────┘               └──────────────┘
     │
     │ 2. MCP request + JWT
     ▼
┌──────────────────┐  3. Validate JWT   ┌──────────────┐
│  AgentGateway    │───────────────────▶│  KeyCloak    │
│  Proxy (:8080)   │   (JWKS fetch)     │  (JWKS)      │
│  - JWT validation│◀───────────────────│              │
│  - Group authz   │                    └──────────────┘
└────────┬─────────┘
         │ 4. Forward (if in "admin" group)
         ▼
┌─────────────────────────────────────┐
│  MCP Servers (code/browser/memory)  │
└─────────────────────────────────────┘
```

## Verify Deployment

```bash
# ArgoCD Applications
kubectl get applications -n argocd | grep -E "agent-platform|kagent|litellm|langfuse|jaeger|agentgateway"

# Pods
kubectl get pods -n kagent
kubectl get pods -n langfuse
kubectl get pods -n jaeger
kubectl get pods -n agentgateway-system

# KAgent resources
kubectl get agents,remotemcpservers,modelconfigs -A

# AgentGateway
kubectl get gateway,httproute,agentgatewaybackend,agentgatewaypolicy -A
```

## EKS ArgoCD Capability Notes

- **No duplicate cluster secrets**: The bootstrap chart uses an Application (not ApplicationSet) with `useSelectors: false` and `globalSelectors` to match the existing hub cluster secret.
- **Custom Lua health checks not supported**: Some resources may show as "Progressing" or "Unknown" in the ArgoCD UI but function correctly.
- **Sync timeout fixed at 120 seconds**: Long-running operations may appear to time out.
- **Git cache refresh**: The managed capability polls git repos every 3-10 minutes.
- **Pod Identity (not IRSA)**: EKS Auto Mode uses Pod Identity. No `eks.amazonaws.com/role-arn` annotations on ServiceAccounts.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| LiteLLM "Unable to locate credentials" | Missing Pod Identity | Verify Crossplane created the association, or use manual fallback |
| LiteLLM "model version has reached end of life" | Outdated model IDs | Update model IDs in litellm chart to use `us.anthropic.*` inference profiles |
| kagent-monitoring fails | Missing ServiceMonitor CRD | Verify `prometheus-operator-crds` addon deployed (wave 5, before monitoring at wave 6) |
| ArgoCD reverts manual changes | selfHeal enabled | Push changes to the sample repo git branch instead of patching directly |
| Gateway API CRDs Job fails | No outbound internet | Ensure NAT gateway is configured for EKS nodes |
| AgentGateway proxy not starting | Missing Gateway API CRDs or JWKS fetch failure | Verify CRDs installed, check KeyCloak reachability |
| JWT validation fails | Wrong issuer URL | Ensure issuer matches `iss` claim (`https://<domain>/keycloak/realms/platform`) |
| AgentGateway 403 | User not in admin group | Add user to `admin` group in KeyCloak platform realm |
