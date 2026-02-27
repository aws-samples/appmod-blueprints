# Testing the Strands Agent in Kubernetes

This guide shows how to test the Strands agent in a Kubernetes cluster.

## Prerequisites

- Kubernetes cluster with kubectl access
- Image pushed to ECR: `498530348755.dkr.ecr.us-east-1.amazonaws.com/strands-agent:latest`
- For AgentGateway mode: AgentGateway deployed in cluster
- For direct Bedrock mode: Pod identity or IAM role configured

## Option 1: Test with AgentGateway (Recommended)

This option uses AgentGateway for centralized LLM access. AgentGateway handles authentication via pod identity.

**About Credentials**: The test pod includes placeholder credentials (`anonymous` / `anonymous`) that boto3 requires but AgentGateway ignores. This is a boto3 limitation - it requires credentials for the bedrock-runtime service even with custom endpoints. AgentGateway performs its own authentication using pod identity and does not validate these placeholder credentials.

### Deploy the test pod

```bash
kubectl apply -f applications/strands/deployment/simple-deployment.yaml
```

### Verify deployment


### Test the agent

```bash
# Port-forward to access the agent
kubectl port-forward pod/strands-agent 8083:8083
```

In another terminal:

```bash
# Test health endpoint
curl http://localhost:8083/health

# Get agent card (A2A protocol)
curl http://localhost:8083/.well-known/agent.json

# Test simple invocation
curl -X POST http://localhost:8083/invoke \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello! Can you tell me what you can do?"}'

# Test A2A message endpoint
curl -X POST http://localhost:8083/\
  -H "Content-Type: application/json" \
  -d '{
    "method": "message/send"
    "kind": "message",
    "role": "user",
    "parts": [{"kind": "text", "text": "What is Kubernetes?"}]
  }'
```

