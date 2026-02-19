# Kagent with Argo Rollouts - KubeVela Component

This directory contains a KubeVela ComponentDefinition that enables deploying Kagent-compatible AI agents with Argo Rollouts progressive delivery capabilities.

## Files

- `kagent-rollout-component.yaml` - ComponentDefinition for Kagent agents with Argo Rollouts
- `example-pdf-agent.yaml` - Example Application using the component

## Features

- ✅ Kagent-compatible agent discovery (Service + labels)
- ✅ Argo Rollouts progressive delivery (canary, blue-green)
- ✅ MCP server integration
- ✅ Tool management
- ✅ Model configuration with secrets
- ✅ A2A protocol support
- ✅ Health checks (liveness/readiness probes)

## Prerequisites

1. KubeVela installed
2. Argo Rollouts installed
3. MCP servers deployed (e.g., pdf-tools, k8s-tools)

## Installation

### 1. Install the ComponentDefinition

```bash
kubectl apply -f kagent-rollout-component.yaml
```

### 2. Create required secrets

```bash
# AWS credentials for Bedrock
kubectl create secret generic bedrock-secret -n kagent \
  --from-literal=aws-access-key-id=AKIAIOSFODNN7EXAMPLE \
  --from-literal=aws-secret-access-key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# Or use IRSA (recommended)
kubectl create serviceaccount bedrock-agent-sa -n kagent
kubectl annotate serviceaccount bedrock-agent-sa -n kagent \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/bedrock-agent-role
```

### 3. Deploy an agent

```bash
kubectl apply -f example-pdf-agent.yaml
```

## Usage

### Access the agent

```bash
# Via Kubernetes DNS (internal)
curl http://pdf-processor.kagent.svc.cluster.local:8083/.well-known/agent.json

# Via Kagent controller (if installed)
curl http://kagent-controller.kagent.svc.cluster.local:8083/api/a2a/kagent/pdf-processor/.well-known/agent.json
```

### Monitor rollout

```bash
# Watch rollout progress
kubectl argo rollouts get rollout pdf-processor -n kagent --watch

# Promote canary
kubectl argo rollouts promote pdf-processor -n kagent

# Abort rollout
kubectl argo rollouts abort pdf-processor -n kagent
```

## Configuration

### Model Configuration

```yaml
modelConfig:
  model: anthropic.claude-sonnet-4-20250514-v1:0
  apiKeySecret:
    name: bedrock-secret
    key: aws-access-key-id
```

### MCP Servers

```yaml
mcpServers:
  - name: pdf-tools
    port: 3000
  - name: k8s-tools
    port: 3001
```

The component constructs URLs: `http://{name}.{namespace}.svc.cluster.local:{port}`

### Tools

```yaml
tools:
  - name: generate_pdf
    mcpServer: pdf-tools
  - name: extract_text
    mcpServer: pdf-tools
```

### Rollout Strategies

**Canary:**
```yaml
rolloutStrategy:
  canary:
    steps:
      - setWeight: 20
      - pause: {duration: 5m}
      - setWeight: 50
      - pause: {duration: 5m}
```

**Blue-Green:**
```yaml
rolloutStrategy:
  blueGreen:
    activeService: pdf-processor-active
    previewService: pdf-processor-preview
    autoPromotionEnabled: false
```

## Agent Discovery

Agents are discoverable via:

1. **Kubernetes DNS**: `http://{agent-name}.{namespace}.svc.cluster.local:8083`
2. **Labels**: `kagent.dev/agent={agent-name}`
3. **ConfigMap**: `{agent-name}-card` contains agent metadata

## Integration with Strands

Your Strands agent should read configuration from environment variables:

```python
import os
from strands import Agent
from strands.multiagent.a2a import A2AServer

# Read config from env
model = os.getenv("MODEL_NAME")
system_message = os.getenv("SYSTEM_MESSAGE")
mcp_servers = os.getenv("MCP_SERVERS", "").split(",")
enabled_tools = os.getenv("ENABLED_TOOLS", "").split(",")

# Create agent
agent = Agent(
    model=model,
    system_message=system_message,
    tools=load_tools_from_mcp(mcp_servers, enabled_tools)
)

# Expose via A2A
server = A2AServer(agent=agent, host="0.0.0.0", port=8083)
server.serve()
```

## Troubleshooting

### Check rollout status
```bash
kubectl argo rollouts status pdf-processor -n kagent
```

### View agent logs
```bash
kubectl logs -l kagent.dev/agent=pdf-processor -n kagent
```

### Test agent endpoint
```bash
kubectl port-forward svc/pdf-processor 8083:8083 -n kagent
curl http://localhost:8083/.well-known/agent.json
```
