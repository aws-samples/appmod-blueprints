# Agent Platform on appmod-blueprints

Enable an AI agent platform on the appmod-blueprints hub cluster with a single toggle. All agent platform charts and configurations live in the [sample-agent-platform-on-eks](https://github.com/aws-samples/sample-agent-platform-on-eks) repo (`feature/gitops-agent-platform` branch).

## How It Works

```
appmod-blueprints                          sample-agent-platform-on-eks
┌─────────────────────┐                    ┌──────────────────────────────┐
│ registry/agents.yaml│                    │ gitops/addons/               │
│   agent-platform:   │                    │   bootstrap/default/         │
│     enabled: true   │                    │     addons.yaml (11 addons)  │
│                     │                    │   charts/                    │
│ charts/             │                    │     application-sets/        │
│   agent-platform/   │──creates──────────▶│     kagent-setup/            │
│     bootstrap.yaml  │  cluster secret    │     litellm/                 │
│                     │  + ApplicationSet  │     langfuse/                │
│                     │  pointing to ──────│     kagent-monitoring/       │
│                     │  sample repo       │     agent-core/              │
└─────────────────────┘                    │   environments/dev/          │
                                           │     addons.yaml              │
                                           └──────────────────────────────┘
```

1. Setting `agent_platform: true` in appmod-blueprints `enabled-addons.yaml` triggers the `agent-platform` addon
2. The addon deploys a thin bootstrap chart that creates a cluster secret and ApplicationSet pointing to the sample repo
3. The sample repo's `application-sets` chart generates one ApplicationSet per enabled addon
4. Each addon deploys via the ArgoCD EKS Capability to the cluster
5. The cluster uses EKS Auto Mode with Pod Identity for AWS credentials

## What Gets Deployed

All addons are defined in the sample repo and deploy in sync-wave order:

| Wave | Addon | Source | Selector | Namespace |
|------|-------|--------|----------|-----------|
| 0 | flux (source-controller) | Helm: `fluxcd-community/flux2:2.12.4` | `enable_flux` | flux-system |
| 1 | tofu-controller | Helm: `flux-iac/tf-controller:0.16.0-rc.4` | `enable_tofu_controller` | flux-system |
| 2 | kagent-crds | OCI: `ghcr.io/kagent-dev/kagent/helm/kagent-crds:0.7.9` | `enable_kagent` | kagent |
| 3 | kagent (operator + UI) | OCI: `ghcr.io/kagent-dev/kagent/helm/kagent:0.7.9` | `enable_kagent` | kagent |
| 3 | kagent-setup (ModelConfig) | Git path chart | `enable_kagent` | kagent |
| 3 | litellm (LLM gateway) | Git path chart | `enable_litellm` | kagent |
| 4 | agent-core (Terraform + MCP + Agent) | Git path chart | `enable_agent_core` | agent-core-infra |
| 5 | langfuse (LLM tracing + PostgreSQL) | Git path chart | `enable_langfuse` | langfuse |
| 5 | jaeger (distributed tracing) | Helm: `jaegertracing/jaeger:3.4.1` | `enable_jaeger` | jaeger |
| 5 | prometheus-operator-crds | Helm: `prometheus-community/prometheus-operator-crds:28.0.1` | `enable_kagent_monitoring` | kagent |
| 6 | kagent-monitoring (ServiceMonitor) | Git path chart | `enable_kagent_monitoring` | kagent |

Flux and tofu-controller are prerequisites for agent-core only. The prometheus-operator-crds chart deploys automatically before kagent-monitoring — no manual CRD installation needed.

## Prerequisites

### Pod Identity (automated via Crossplane)

All Pod Identity (IAM roles + associations) for LiteLLM and Tofu Controller are **automated via Crossplane** using the `crossplane-pod-identity` chart deployed as `additionalResources` alongside the agent-platform addon. This creates:

| Identity | IAM Role | Namespace | ServiceAccount | Purpose |
|---|---|---|---|---|
| litellm | `{clusterName}-LiteLLMBedrockRole` | kagent | litellm | Bedrock model invocation |
| tofu-runner | `{clusterName}-AgentCoreTofuRunner` | agent-core-infra | tf-runner | Terraform provisioning for AgentCore |

**Requirement**: Crossplane with AWS IAM and EKS providers must be running on the hub cluster (`enable_crossplane: true` in enabled-addons.yaml).

The Terraform module for agent-core also auto-creates Pod Identity associations for:
- `agent-core-infra/agent-core-mcp-sa` — AgentCore API access for MCP server
- `agent-core-infra/agent-core-agent-sa` — Bedrock access for KAgent agent

### MCP Server Container Image (agent-core only)

The MCP server source lives in the [sample-agent-platform-on-eks](https://github.com/aws-samples/sample-agent-platform-on-eks) repo under `mcp-server/`.

```bash
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

cd <sample-agent-platform-on-eks-repo>/mcp-server

# Create ECR repository
aws ecr create-repository --repository-name agent-core-mcp --region $REGION

# Build and push
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com
docker build --platform linux/amd64 -t agent-core-mcp:latest .
docker tag agent-core-mcp:latest ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/agent-core-mcp:latest
docker push ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/agent-core-mcp:latest
```

## Enable the Agent Platform

### Basic (no agent-core)

Edit `gitops/overlays/environments/control-plane/enabled-addons.yaml`:

```yaml
  agent_platform: true
```

### Full (with agent-core)

Same as above, plus add annotations to `gitops/fleet/members/hub/values.yaml`:

```yaml
externalSecret:
  enabled: true
  secretStoreRefKind: ClusterSecretStore
  secretStoreRefName: aws-secrets-manager
  clusterName: hub
  labels:
    environment: control-plane
    tenant: control-plane
  annotations:
    agent_core_project_name: "agent-core"
    agent_core_network_mode: "PUBLIC"
    agent_core_mcp_image: "<ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/agent-core-mcp"
    agent_core_mcp_image_tag: "latest"
    agent_core_terraform_repo_url: "https://github.com/aws-samples/sample-agent-platform-on-eks.git"
    agent_core_terraform_repo_revision: "feature/gitops-agent-platform"
```

Commit and push. ArgoCD deploys everything automatically.

## Verify Deployment

```bash
# ArgoCD Applications
kubectl get applications -n argocd | grep -E "agent-platform|kagent|litellm|langfuse|jaeger|flux-agent|tofu"

# Pods
kubectl get pods -n kagent
kubectl get pods -n langfuse
kubectl get pods -n jaeger
kubectl get pods -n agent-core-infra   # if agent-core enabled
kubectl get pods -n flux-system        # if agent-core enabled

# KAgent resources
kubectl get agents,remotemcpservers,modelconfigs -A

# Terraform (if agent-core enabled)
kubectl get terraform -n agent-core-infra

# Test LiteLLM → Bedrock
kubectl run test --rm -i --restart=Never --image=curlimages/curl -n kagent -- \
  curl -s -X POST http://litellm-service.kagent.svc.cluster.local:4000/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"bedrock-claude-3-5-sonnet","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}'
```

## EKS ArgoCD Capability Notes

- **Custom Lua health checks not supported**: The agent-core chart includes a Terraform health check ConfigMap that is ignored by the managed capability. Terraform resources may show as "Progressing" or "Unknown" in the ArgoCD UI but function correctly.
- **Sync timeout fixed at 120 seconds**: Long-running Terraform applies may appear to time out but continue in the background via the tofu-controller.
- **Git cache refresh**: The managed capability polls git repos every 3-10 minutes. Changes to the sample repo may take time to propagate.
- **Cluster secrets use EKS ARNs**: The bootstrap chart constructs the ARN from `aws_region`, `aws_account_id`, and `aws_cluster_name` annotations.
- **Pod Identity (not IRSA)**: EKS Auto Mode uses Pod Identity. No `eks.amazonaws.com/role-arn` annotations on ServiceAccounts.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| LiteLLM "Unable to locate credentials" | Missing Pod Identity | Verify Crossplane created the association, or use manual fallback |
| LiteLLM "model version has reached end of life" | Outdated model IDs | Update model IDs in `litellm/templates/litellm.yaml` to use `us.anthropic.*` inference profiles |
| Terraform "AccessDenied" | Missing or insufficient IAM permissions | Verify AgentCoreTofuRunner policy and Pod Identity association |
| Terraform stuck in "Planning" | Source-controller unhealthy or slow Bedrock API | Check `kubectl get pods -n flux-system`, increase source-controller memory if OOMKilled |
| MCP server "CreateContainerConfigError" | Terraform outputs secret doesn't exist yet | Wait for Terraform to complete |
| MCP server OOMKilled (exit code 137) | Insufficient memory | Increase limits in `agent-core/values.yaml` (default 512Mi/1Gi) |
| RemoteMCPServer "Accepted: False" | DNS resolution failure or MCP server down | Verify URL uses FQDN (`<svc>.<ns>.svc.cluster.local`), check MCP server logs |
| kagent-monitoring fails | Missing ServiceMonitor CRD | Verify `prometheus-operator-crds` addon deployed (wave 5, before monitoring at wave 6) |
| ArgoCD reverts manual changes | selfHeal enabled | Push changes to the sample repo git branch instead of patching directly |
