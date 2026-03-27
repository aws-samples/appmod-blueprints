# Agentic Platform

GitOps-managed deployment of the agentic AI infrastructure on EKS, including [AgentGateway](https://agentgateway.dev) (Gateway API for AI agents/MCP servers), a Bedrock AI backend, and a LiteLLM proxy for centralized LLM access.

## Architecture

```
gitops/agentic/
└── addons/
    ├── default/
    │   └── addons.yaml                    # Addon definitions for application-sets chart
    └── charts/
        └── agentgateway/
            ├── Chart.yaml                 # Wrapper chart (depends on oci://cr.agentgateway.dev/charts/agentgateway)
            ├── values.yaml                # Default values
            └── templates/
                ├── gateway.yaml           # Gateway API Gateway resource
                ├── bedrock-backend.yaml   # AgentgatewayBackend + HTTPRoute for Bedrock
                └── litellm.yaml           # LiteLLM proxy (Deployment, ConfigMap, Service)

gitops/fleet/bootstrap/
└── agentic-addons.yaml                    # ArgoCD ApplicationSet (entry point)
```

## What Gets Deployed

| Component | Description |
|---|---|
| AgentGateway controller | Helm chart `oci://cr.agentgateway.dev/charts/agentgateway:v2.2.1` — manages GatewayClass, proxy deployments |
| Gateway proxy | Auto-provisioned by the controller when the Gateway resource is created; exposes a LoadBalancer |
| Bedrock backend | `AgentgatewayBackend` CR pointing to Claude Sonnet on Bedrock, with an HTTPRoute |
| LiteLLM proxy | OpenAI-compatible proxy that routes to Bedrock via pod identity; used by agents as their LLM endpoint |

## Deployment

### Automatic (Recommended)

Add `enable_agentgateway: true` to the hub cluster's addons in `platform/infra/terraform/hub-config.yaml`:

```yaml
clusters:
  hub:
    addons:
      # ... existing addons ...
      enable_agentgateway: true
```

Then run the standard Terraform apply. The gitops-bridge module propagates this label to the ArgoCD cluster secret, which triggers the `agentic-addons` ApplicationSet in `gitops/fleet/bootstrap/agentic-addons.yaml`. ArgoCD then deploys the agentgateway chart into the `agentgateway-system` namespace.

### Manual

If the cluster is already running and you just want to enable it without a Terraform run, add the label to the ArgoCD cluster secret directly:

```bash
kubectl label secret -n argocd -l argocd.argoproj.io/secret-type=cluster \
  enable_agentgateway=true --overwrite
```

ArgoCD will pick up the label change and deploy automatically.

## How the GitOps Flow Works

```
hub-config.yaml                          # 1. enable_agentgateway: true
  → Terraform (gitops-bridge)            # 2. Sets label on ArgoCD cluster secret
    → fleet/bootstrap/agentic-addons.yaml  # 3. ApplicationSet matches the label
      → agentic/addons/default/addons.yaml # 4. Addon config fed to application-sets chart
        → agentic/addons/charts/agentgateway/ # 5. Helm chart deployed to cluster
```

The `agentic-addons.yaml` ApplicationSet lives in `gitops/fleet/bootstrap/`, which is auto-synced by the top-level fleet bootstrap. It only activates when the cluster secret has `enable_agentgateway: "true"`.

## Configuration

Override values per-environment by creating additional value files:

```
gitops/agentic/addons/
├── default/addons.yaml           # Base config (always applied)
├── environments/
│   └── control-plane/addons.yaml # Environment overrides (optional)
└── clusters/
    └── hub/addons.yaml           # Cluster-specific overrides (optional)
```

### Key Values

| Value | Default | Description |
|---|---|---|
| `bedrockBackend.model` | `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | Bedrock model ID |
| `bedrockBackend.region` | `us-west-2` (from cluster annotation) | AWS region for Bedrock |
| `litellm.masterKey` | `sk-1234` | LiteLLM API key (override in production) |
| `litellm.models` | Claude Sonnet via Bedrock | LLM model routing config |
| `gateway.listeners` | HTTP on port 80, all namespaces | Gateway listener config |

## Accessing the Gateway

```bash
# Get the gateway endpoint
GATEWAY_URL=$(kubectl get svc -n agentgateway-system agentgateway-proxy \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Test Bedrock backend
curl http://${GATEWAY_URL}/bedrock/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "claude-sonnet", "messages": [{"role": "user", "content": "Hello"}]}'

# LiteLLM is available cluster-internally at:
# http://litellm-proxy.agentgateway-system.svc.cluster.local:4000
```

## Adding More Agentic Addons

To add new addons (e.g., kagent, MCP servers), add entries to `agentic/addons/default/addons.yaml` following the same pattern, and place charts under `agentic/addons/charts/`.
