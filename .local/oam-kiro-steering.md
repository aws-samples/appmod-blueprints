# OAM Agent Platform — Kiro Steering Context

This document captures the current design of the agent platform so Kiro can pick up context quickly without re-exploration.

---

## 1. Strands Agent Image (`applications/strands/`)

A generic, config-driven container image that deploys any Strands agent. Developers create agents purely through environment variables — no custom image required.

### Key files

| File | Purpose |
|---|---|
| `app/config.py` | `Config` class — all behavior driven by env vars: `AGENT_NAME`, `SYSTEM_PROMPT`, `MODEL_ID`, `LLM_GATEWAY_URL`, `MCP_SERVER_NAMES`, `MEMORY_PROVIDER`, `MEMORY_CONFIG` |
| `app/agent.py` | Builds `Agent` with `LiteLLMModel`, connects to MCP servers via `streamablehttp_client`, exposes global `agent` singleton |
| `app/main.py` | FastAPI app wrapping `A2AServer` + `/health`, `/chat` endpoints. Runs on port 8083 |
| `Dockerfile` | Multi-stage build with `uv`, Python 3.11, non-root user, healthcheck on `/ping` |

### How it works

- LLM access goes through a centralized LiteLLM proxy (no direct Bedrock creds in agent pods).
- MCP tools are loaded at startup from `MCP_SERVER_NAMES` → resolved to `http://<gateway>/mcp/<name>` URLs.
- A2A protocol handled entirely by `strands.multiagent.a2a.A2AServer`.

### Memory — initial design

The image accepts `MEMORY_PROVIDER` and `MEMORY_CONFIG` (JSON) env vars. The OAM layer injects these. The agent code has initial scaffolding to receive memory config but the actual memory integration (constructing the session manager or mem0 client from these env vars) is a work-in-progress.

Two memory approaches are planned:

1. **AgentCore (native Strands)** — Uses Strands `SessionManager` / AgentCore memory service directly. Requires AWS credentials (Bedrock access) via pod identity. Config: `memoryId`, `region`, optionally `roleArn`.

2. **mem0 with vector store** — Uses the mem0 library backed by a vector database. Supported providers: `milvus`, `qdrant`, `opensearch`, `pgvector`, `redis`, `chroma`, `s3vectors`. Config varies per provider (e.g., `url`, `collectionName` for Milvus).

---

## 2. OAM Agent Component (`platform/oam/agent.cue`)

KubeVela CUE-based ComponentDefinition that declaratively deploys agents using the strands image.

### What it generates

| Resource | Details |
|---|---|
| Argo Rollout | Blue-green strategy with `<name>-stable` and `<name>-preview` services |
| Stable Service | Port 8083, `appProtocol: kgateway.dev/a2a` |
| Preview Service | Port 8083, for blue-green preview |
| Agent Card ConfigMap | Metadata: name, description, model, memory provider, MCP servers |
| HTTPRoute | Optional, routes `/<name>` → stable service via `agentgateway-proxy` |
| ServiceAccount | Only when `memory.provider == "agentcore"` — creates SA with `eks.amazonaws.com/role-arn` annotation |

### Key parameters

```
name, namespace, description, systemMessage  — required
image                                        — defaults to ECR strands-agent:latest
replicas                                     — default 3
serviceAccount                               — default "default"
modelConfig.modelId                          — default "claude-sonnet"
modelConfig.llmGatewayUrl                    — default litellm-proxy cluster URL
memory.provider                              — "agentcore" | "milvus" | "qdrant" | "opensearch" | "pgvector" | "redis" | "chroma" | "s3vectors"
memory.config                                — provider-specific key/value map
mcpServers                                   — list of {name: string}
env                                          — additional env vars
resources                                    — requests/limits
registerWithGateway                          — default true
```

### Memory env injection

The CUE template builds `_memoryEnv` from `parameter.memory`:
- `MEMORY_PROVIDER` → `parameter.memory.provider`
- `MEMORY_CONFIG` → JSON-serialized `parameter.memory.config`

These are appended to the container env list.

### AgentCore memory and ServiceAccount

When `memory.provider == "agentcore"`, the CUE template generates a dedicated ServiceAccount (`<name>-sa`) with `eks.amazonaws.com/role-arn` annotation from `memory.config.roleArn`. This gives the pod AWS credentials for Bedrock/AgentCore access.

**Current limitation**: This inline SA creation is basic. It requires the user to pre-provision the IAM role and pass the ARN. It does NOT auto-provision the IAM role, policy, or PodIdentityAssociation.

---

## 3. Service Account Component (`gitops/addons/charts/kubevela/templates/components/service-account.yaml`)

KubeVela ComponentDefinition `dp-service-account` that automates full AWS identity provisioning.

### What it generates

| Resource | Details |
|---|---|
| `PodIdentityAssociation` (Crossplane) | `eks.aws.upbound.io/v1beta1` — binds SA to IAM role in the EKS cluster |
| IAM `Role` (Crossplane) | `iam.aws.upbound.io/v1beta1` — trust policy for `pods.eks.amazonaws.com` with `sts:AssumeRole` + `sts:TagSession` |
| `RolePolicyAttachment` (Crossplane) | For each component in `componentNamesForAccess`, attaches `<appName>-<component>-iam-policy` to the role |
| `ServiceAccount` | Kubernetes SA with the component name |

### Parameters

```
componentNamesForAccess?: [...string]   — other OAM components whose IAM policies should be attached
clusterRegion: string                   — AWS region
clusterName: string                     — EKS cluster name
```

### How it discovers policies

Uses KubeVela's `context.components["<name>"]` to look up sibling components in the same Application. The convention is that AWS resource components (e.g., DynamoDB, S3) create IAM policies named `<appName>-<componentName>-iam-policy`. The service account component attaches these to its role via `RolePolicyAttachment`.

---

## 4. Integration Plan: Agent + Service Account for AWS Access

When an agent needs AWS access (AgentCore memory, direct Bedrock, S3, etc.), the intended pattern is:

### Approach A: AgentCore memory via `dp-service-account`

Instead of the agent.cue inline SA (which requires a pre-provisioned role ARN), compose the agent with `dp-service-account` in the same OAM Application:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: my-agent
spec:
  components:
    - name: my-agent-sa
      type: dp-service-account
      properties:
        clusterRegion: us-west-2
        clusterName: my-cluster
        componentNamesForAccess:
          - bedrock-policy  # reference to a policy component if needed

    - name: my-agent
      type: agent
      properties:
        name: my-agent
        namespace: agents
        serviceAccount: my-agent-sa  # references the SA created above
        memory:
          provider: agentcore
          config:
            memoryId: my-memory
            region: us-west-2
        # ... rest of agent config
```

This auto-provisions: IAM Role → PodIdentityAssociation → ServiceAccount → RolePolicyAttachment. No manual role ARN needed.

### Approach B: mem0 + Milvus (no AWS access needed)

Milvus runs in-cluster, so no AWS credentials required:

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: agent-with-milvus
spec:
  components:
    - name: assistant
      type: agent
      properties:
        name: assistant
        namespace: agents
        memory:
          provider: milvus
          config:
            url: milvus.vector-system.svc.cluster.local:19530
            collectionName: assistant-memory
```

For mem0 providers that need AWS (e.g., `s3vectors`), use the same `dp-service-account` pattern as Approach A.

---

## 5. Example Files

| File | What it demonstrates |
|---|---|
| `platform/oam/example-agent-simple.yaml` | Agent with AgentCore memory, MCP tools, resource limits |
| `platform/oam/example-agent-milvus-memory.yaml` | Agent with mem0 + Milvus vector store |
| `platform/oam/example-agent-with-mcp.yaml` | Agent with MCP server references |
| `platform/oam/example-agent-minimal.yaml` | Bare minimum agent |

---

## 6. Design Decisions (from `platform/oam/DESIGN.md`)

- Blue-green via Argo Rollouts (not Deployment) for both agents and MCP servers.
- LLM access through LiteLLM proxy gateway — no direct Bedrock creds in agent pods.
- Per-MCP-server routing (not federation) to avoid bloated tool lists.
- Static AgentgatewayBackend targets (not dynamic) for deterministic blue-green routing.
- StreamableHTTP for MCP transport (not SSE).
- Agent port 8083, MCP server port 8000.
- Gateway registration via HTTPRoute is on by default.

---

## 7. Open Items / TODOs

- **Agent image memory integration**: The Python code in `app/agent.py` does not yet construct a session manager or mem0 client from `MEMORY_PROVIDER`/`MEMORY_CONFIG`. This wiring needs to be implemented.
- **agent.cue + dp-service-account composition**: The agent.cue currently has an inline SA for agentcore. Consider removing it in favor of always using `dp-service-account` as a sibling component, or making the inline SA call out to Crossplane resources.
- **Bedrock policy component**: Need a reusable OAM component that creates the Bedrock IAM policy (`bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`) so `dp-service-account` can reference it via `componentNamesForAccess`.
