# Strands Agent with A2A Protocol

Minimal Strands agent with FastAPI, A2A protocol, and kgateway consistent hashing for multi-replica scaling.

## Quick Start

```bash
# Local development
uv sync
uv run python -m app.main

# Docker build (AMD64 for AWS)
./build.sh

# Docker run
docker run -p 8083:8083 \
  -e AWS_REGION=us-west-2 \
  -e AWS_ACCESS_KEY_ID=xxx \
  -e AWS_SECRET_ACCESS_KEY=xxx \
  strands-agent:latest

# Test
curl http://localhost:8083/health
```

## Project Structure

```
applications/strands/
├── app/                    # Application code
│   ├── main.py            # FastAPI + A2A endpoints
│   ├── agent.py           # Strands agent config
│   └── config.py          # Environment config
├── tests/                  # Tests and fixtures
│   ├── integration/       # Integration tests
│   └── fixtures/          # Test helpers, manifests
├── Dockerfile             # Multi-stage build (AMD64)
├── build.sh               # Docker build script
├── build-podman.sh        # Podman build script
└── requirements.txt       # Python dependencies
```

## Configuration

All configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NAME` | `strands-agent` | Agent identifier |
| `SYSTEM_PROMPT` | Default prompt | Agent behavior |
| `MODEL_ID` | `claude-sonnet` | Model name for LLM Gateway |
| `AWS_REGION` | `us-west-2` | AWS region |
| `LLM_GATEWAY_URL` | `http://litellm-proxy.agentgateway-system.svc.cluster.local:4000` | LiteLLM proxy URL |
| `LLM_GATEWAY_API_KEY` | `sk-1234` | Gateway API key (optional) |
| `MCP_SERVERS` | None | Comma-separated URLs |
| `PORT` | `8083` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level |

## API Endpoints

### A2A Protocol (via Strands A2AServer)
- `GET /.well-known/agent.json` - Agent card
- `POST /message` - Send message to agent
- `POST /message/stream` - Streaming message

### Custom Endpoints
- `GET /health` - Health check
- `GET /info` - Agent information

## A2A Protocol Usage

The agent uses Strands' built-in A2AServer which handles all A2A protocol complexity automatically, including conversation history management.

Send messages via the `/message` endpoint:

```bash
# First message - server creates context and task
curl -X POST http://localhost:8083/message \
  -H 'Content-Type: application/json' \
  -d '{
    "message": {
      "role": "ROLE_USER",
      "parts": [{"text": "Hello, how can you help me?"}],
      "messageId": "msg-1"
    }
  }'

# Response includes contextId and taskId
# {
#   "task": {
#     "id": "task-123",
#     "contextId": "ctx-456",
#     "history": [...]
#   }
# }

# Follow-up message - maintains conversation context
curl -X POST http://localhost:8083/message \
  -H 'Content-Type: application/json' \
  -d '{
    "message": {
      "role": "ROLE_USER",
      "parts": [{"text": "Tell me more"}],
      "messageId": "msg-2",
      "contextId": "ctx-456"
    }
  }'
```

The A2A protocol manages sessions through:
- **contextId**: Groups related tasks in a conversation
- **taskId**: Unique identifier for each task
- **Task.history**: Server-maintained conversation history
- For streaming responses, use `/message/stream`

## Deployment

### Kubernetes with kgateway Consistent Hashing (Recommended)

The agent uses kgateway's consistent hashing to enable multi-replica deployments with in-memory TaskStore. Requests with the same contextId are routed to the same pod.

```bash
# Deploy with consistent hashing (3 replicas)
kubectl apply -f deployment/kgateway-session-affinity.yaml
```

This deployment includes:
- **BackendConfigPolicy**: Configures Ringhash/Maglev for consistent hashing
- **HTTPRoute**: Routes traffic through kgateway
- **Service**: Exposes agent with `appProtocol: kgateway.dev/a2a`
- **Deployment**: 3 replicas with in-memory TaskStore

**Client Requirements**: Clients must add `X-Context-ID` header extracted from A2A contextId:

```python
import requests

# First request
response = requests.post(
    "http://agents.example.com/strands-agent/message",
    json={"message": {"role": "ROLE_USER", "parts": [{"text": "Hello"}]}}
)

# Extract contextId from response
context_id = response.json()["task"]["contextId"]

# Follow-up request with header for consistent hashing
response = requests.post(
    "http://agents.example.com/strands-agent/message",
    json={
        "message": {
            "role": "ROLE_USER",
            "parts": [{"text": "Continue"}],
            "contextId": context_id  # In body (A2A protocol)
        }
    },
    headers={"X-Context-ID": context_id}  # In header (for kgateway)
)
```

See `CONSISTENT_HASHING.md` for complete implementation guide.

### ECR Push

```bash
# Build and push
./build.sh push

# Or manually
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com

aws ecr create-repository --repository-name strands-agent --region us-west-2 || true

docker tag strands-agent:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/strands-agent:latest

docker push ${AWS_ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/strands-agent:latest
```

## Container Image

**Base:** `python:3.11-slim-bookworm`  
**Architecture:** `linux/amd64`  
**Size:** ~150 MB compressed  
**User:** Non-root (UID 1000)  
**Port:** 8083  
**Health:** `/health` endpoint

**What's inside:**
- FastAPI + Uvicorn
- Strands Agents SDK with A2A support
- LiteLLM for gateway integration

## Testing

```bash
# Start server locally
uv run python -m app.main

# Test health endpoint
curl http://localhost:8083/health

# Test agent info
curl http://localhost:8083/info

# Test A2A message endpoint
curl -X POST http://localhost:8083/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "role": "ROLE_USER",
      "parts": [{"text": "Hello"}],
      "messageId": "msg-1"
    }
  }'
```

See `TESTING.md` for detailed testing documentation including integration tests.

## Scaling with Consistent Hashing

The agent uses kgateway's consistent hashing to enable multi-replica deployments:

- ✅ **Multiple replicas supported** (3+ pods)
- ✅ **Same contextId routes to same pod** (via X-Context-ID header)
- ✅ **In-memory TaskStore** (no database needed)
- ⚠️ **Affinity lost on pod changes** (scaling, restarts)

**How it works**:
1. Client extracts contextId from A2A response
2. Client adds `X-Context-ID` header to subsequent requests
3. kgateway hashes header and routes to same pod
4. Pod serves request from in-memory TaskStore

**Deployment**:
```bash
kubectl apply -f deployment/kgateway-session-affinity.yaml
```

See `CONSISTENT_HASHING.md` for:
- Complete implementation guide
- Client examples (Python, curl)
- Algorithm comparison (Ringhash vs Maglev)
- Hash policy options
- Troubleshooting

**When to use**:
- Development/staging with multiple replicas
- Production with stable pod count
- Short-lived conversations (minutes to hours)

**When NOT to use**:
- Long-lived conversations (days to weeks)
- Frequent scaling up/down
- Critical conversations that cannot be lost

**Alternative**: For production robustness, implement persistent TaskStore or use Bedrock AgentCore Runtime (see CONSISTENT_HASHING.md).

## Podman Support

Use Podman instead of Docker:

```bash
# Build
./build-podman.sh

# Run
podman run -p 8083:8083 -e AWS_REGION=us-west-2 strands-agent:latest

# Push to ECR
./build-podman.sh push
```

## Progressive Delivery

Deploy with Argo Rollouts for canary or blue-green deployments:

```bash
# See platform/oam/ for examples
kubectl apply -f platform/oam/example-strands-agent.yaml
```

## Troubleshooting

**Container won't start:**
```bash
docker logs strands-agent
```

**AWS auth issues:**
```bash
# Verify credentials
aws sts get-caller-identity

# Check pod identity
aws eks list-pod-identity-associations --cluster-name your-cluster
```

**LLM Gateway connection:**
```bash
# Test LiteLLM proxy
kubectl port-forward -n agentgateway-system svc/litellm-proxy 4000:4000
curl http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-1234" \
  -d '{"model": "claude-sonnet", "messages": [{"role": "user", "content": "test"}]}'
```

## References

- [Strands Agents](https://strandsagents.com/)
- [A2A Protocol](https://a2a-protocol.org/)
- [kgateway Consistent Hashing](https://kgateway.dev/docs/envoy/main/traffic-management/session-affinity/consistent-hashing/)
- [AgentGateway](https://agentgateway.dev/)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)

## Documentation

- `ARCHITECTURE.md` - System architecture and request flow
- `CONSISTENT_HASHING.md` - Multi-replica scaling with kgateway
- `TESTING.md` - Testing guide and integration tests
