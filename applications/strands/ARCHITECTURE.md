# Strands Agent Architecture

This document explains how the Strands agent implementation works and how it integrates with the LLM Gateway and AgentGateway.

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      AgentGateway                           │
│              (Kubernetes Gateway API)                       │
│         Routes A2A requests to agents                       │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP (A2A Protocol)
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                   Strands Agent Pod                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  FastAPI App (main.py)                               │   │
│  │  - Health endpoints (/health, /info)                 │   │
│  │  - A2AServer integration                             │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │  Strands A2AServer                                   │   │
│  │  - /.well-known/agent.json                           │   │
│  │  - POST /message                                     │   │
│  │  - POST /message/stream                              │   │
│  │  - Task management                                   │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │  Strands Agent (agent.py)                            │   │
│  │  - System prompt                                     │   │
│  │  - LiteLLM model                                     │   │
│  │  - Tools (optional)                                  │   │
│  └──────────────────┬───────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP (OpenAI-compatible API)
                     ↓
┌─────────────────────────────────────────────────────────────┐
│              LLM Gateway (LiteLLM Proxy)                    │
│         http://litellm-proxy.agentgateway-system:4000      │
│  - OpenAI-compatible API                                    │
│  - Pod identity for Bedrock auth                            │
└────────────────────┬────────────────────────────────────────┘
                     │ AWS Bedrock API
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                   Amazon Bedrock                            │
│              Claude 3.5 Sonnet Model                        │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. FastAPI Application (main.py)

The entry point that:
- Creates an A2AServer instance with the Strands agent
- Converts A2AServer to a FastAPI app
- Adds custom endpoints (/health, /info)
- Runs with Uvicorn

**Key point:** We don't implement A2A protocol manually. Strands A2AServer handles all the complexity.

### 2. Strands A2AServer

Built into Strands SDK, provides:
- `/.well-known/agent.json` - Agent card endpoint
- `POST /message` - Stateless message endpoint
- `POST /message/stream` - Streaming responses
- Task management and lifecycle
- Protocol compliance

**Key point:** A2A protocol is stateless. Each request is independent. No session management needed.

### 3. Strands Agent (agent.py)

Configured with:
- LiteLLM model pointing to LLM Gateway
- System prompt from environment
- Optional tools (MCP servers)
- Agent metadata (name, description)

**Key point:** Uses LiteLLM model, not direct Bedrock model. This allows gateway-based authentication.

### 4. LLM Gateway (LiteLLM Proxy)

Centralized LLM access:
- OpenAI-compatible API
- Handles Bedrock authentication via pod identity
- No credentials needed in agent pods
- Supports multiple models and providers

**Key point:** Gateway pod has AWS credentials via pod identity. Agent pods don't need credentials.

### 5. AgentGateway (Optional)

Kubernetes Gateway API for routing:
- Routes A2A requests to agents
- Service discovery
- Load balancing
- Path-based routing

**Key point:** Agents register via HTTPRoute with `appProtocol: kgateway.dev/a2a` annotation.

## Configuration Flow

### Environment Variables

```
Agent Pod Environment:
├── AGENT_NAME=strands-agent
├── MODEL_ID=claude-sonnet              # Model name for gateway
├── SYSTEM_PROMPT=...                   # Agent behavior
├── LLM_GATEWAY_URL=http://...          # Gateway endpoint
├── LLM_GATEWAY_API_KEY=sk-1234         # Gateway auth (optional)
├── PORT=8083
└── LOG_LEVEL=INFO
```

### Configuration Loading

```python
# config.py loads from environment
config = Config()

# agent.py creates LiteLLM model
model = LiteLLMModel(
    client_args={
        "api_key": config.LLM_GATEWAY_API_KEY,
        "api_base": config.LLM_GATEWAY_URL,
        "use_litellm_proxy": True
    },
    model_id=config.MODEL_ID,  # "claude-sonnet"
)

# agent.py creates agent
agent = Agent(
    model=model,
    system_prompt=config.SYSTEM_PROMPT,
)

# main.py creates A2A server
a2a_server = A2AServer(agent=agent)
app = a2a_server.to_fastapi_app()
```

## Request Flow

### A2A Message Request

```
1. Client → AgentGateway
   POST /message
   {
     "message": {
       "role": "ROLE_USER",
       "parts": [{"text": "Hello"}],
       "contextId": "ctx-123",  // Optional: groups related tasks
       "taskId": "task-456"      // Optional: continues existing task
     }
   }

2. AgentGateway → Agent Pod (via HTTPRoute)
   POST http://strands-agent-stable:8083/message
   Same payload

3. Agent Pod → A2AServer
   Handles protocol, manages task lifecycle
   Maintains conversation history in Task object

4. A2AServer → Strands Agent
   agent.invoke_async("Hello")

5. Strands Agent → LLM Gateway
   POST http://litellm-proxy:4000/v1/chat/completions
   {
     "model": "claude-sonnet",
     "messages": [{"role": "user", "content": "Hello"}]
   }

6. LLM Gateway → Bedrock
   Uses pod identity credentials
   POST https://bedrock-runtime.us-west-2.amazonaws.com/...

7. Response flows back through the chain
   Task object includes history of all messages
```

## Authentication

### No Credentials in Agent Pod

The agent pod doesn't need AWS credentials because:
1. Agent uses LiteLLM model pointing to gateway
2. Gateway has pod identity with Bedrock permissions
3. Agent only needs gateway URL and API key

### LLM Gateway Pod Identity

```yaml
# Gateway pod has service account with IAM role
apiVersion: v1
kind: ServiceAccount
metadata:
  name: litellm-proxy
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/litellm-bedrock-role
```

IAM role has Bedrock permissions:
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": "*"
}
```

## A2A Protocol Details

### Session Management via Context and Task IDs

The A2A protocol manages conversation history through:
- **contextId**: Groups related tasks and messages in a logical session
- **taskId**: Unique identifier for each task with its own history
- **Task.history**: Array of messages exchanged during task execution
- Server-side storage of conversation context

### How contextId is Propagated

According to the A2A specification (Section 3.4), contextId propagation works as follows:

**Server Responsibilities:**
1. When receiving a message WITHOUT contextId:
   - Server MUST generate a new contextId
   - Server MUST include it in the response (Task or Message)
   
2. When receiving a message WITH contextId:
   - Server MUST accept and preserve the client-provided contextId
   - Server validates it doesn't conflict with provided taskId

**Client Responsibilities:**
1. First message in conversation:
   - Client sends message without contextId
   - Client receives contextId from server response
   - Client stores contextId for subsequent messages

2. Follow-up messages:
   - Client MAY include contextId to continue conversation
   - Client MAY include taskId (with or without contextId)
   - Client MAY include contextId without taskId to start new task in same context

**Propagation Rules:**
- If only taskId provided: Server infers contextId from the task
- If both provided: Server validates they match (same contextId as the task)
- If mismatch: Server rejects with error

**Example Flow:**
```
1. Client → Server: Message (no contextId, no taskId)
   Response: Task { id: "task-1", contextId: "ctx-A" }

2. Client → Server: Message (contextId: "ctx-A")
   Response: Task { id: "task-2", contextId: "ctx-A" }  // Same context, new task

3. Client → Server: Message (taskId: "task-1")
   Response: Task { id: "task-1", contextId: "ctx-A" }  // Server infers context

4. Client → Server: Message (taskId: "task-1", contextId: "ctx-A")
   Response: Task { id: "task-1", contextId: "ctx-A" }  // Valid match

5. Client → Server: Message (taskId: "task-1", contextId: "ctx-B")
   Response: ERROR - contextId mismatch
```

**In Strands Implementation:**
The Strands A2AServer handles all of this automatically:
- Generates contextId for new conversations
- Validates contextId/taskId combinations
- Maintains Task.history for each context
- Provides conversation history to the agent

### Agent Card

```json
GET /.well-known/agent.json

{
  "name": "strands-agent",
  "description": "A Strands agent with A2A protocol support",
  "version": "1.0.0",
  "capabilities": ["chat", "streaming"]
}
```

### Message Endpoint

**First Message (No Context):**
```json
POST /message

Request:
{
  "message": {
    "role": "ROLE_USER",
    "parts": [{"text": "What is the weather?"}],
    "messageId": "msg-1"
    // No contextId or taskId
  }
}

Response:
{
  "task": {
    "id": "task-123",
    "contextId": "ctx-456",  // Server generated
    "status": {"state": "TASK_STATE_COMPLETED"},
    "history": [
      {
        "role": "ROLE_USER",
        "parts": [{"text": "What is the weather?"}],
        "messageId": "msg-1",
        "contextId": "ctx-456"
      },
      {
        "role": "ROLE_AGENT",
        "parts": [{"text": "I don't have access to weather data..."}],
        "messageId": "msg-2",
        "contextId": "ctx-456"
      }
    ]
  }
}
```

**Follow-up Message (With Context):**
```json
POST /message

Request:
{
  "message": {
    "role": "ROLE_USER",
    "parts": [{"text": "What about tomorrow?"}],
    "messageId": "msg-3",
    "contextId": "ctx-456"  // Client provides context from previous response
  }
}

Response:
{
  "task": {
    "id": "task-789",  // New task
    "contextId": "ctx-456",  // Same context
    "status": {"state": "TASK_STATE_COMPLETED"},
    "history": [
      // Full conversation history including previous messages
      {
        "role": "ROLE_USER",
        "parts": [{"text": "What is the weather?"}],
        "messageId": "msg-1",
        "contextId": "ctx-456"
      },
      {
        "role": "ROLE_AGENT",
        "parts": [{"text": "I don't have access to weather data..."}],
        "messageId": "msg-2",
        "contextId": "ctx-456"
      },
      {
        "role": "ROLE_USER",
        "parts": [{"text": "What about tomorrow?"}],
        "messageId": "msg-3",
        "contextId": "ctx-456"
      },
      {
        "role": "ROLE_AGENT",
        "parts": [{"text": "I still don't have weather capabilities..."}],
        "messageId": "msg-4",
        "contextId": "ctx-456"
      }
    ]
  }
}
```

**Continue Existing Task:**
```json
POST /message

Request:
{
  "message": {
    "role": "ROLE_USER",
    "parts": [{"text": "Can you clarify?"}],
    "messageId": "msg-5",
    "taskId": "task-789"  // Continue specific task (contextId inferred)
  }
}
```

## Deployment Patterns

### Simple Deployment

Single replica, no progressive delivery:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: strands-agent
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: agent
        image: strands-agent:latest
        env:
        - name: MODEL_ID
          value: claude-sonnet
        - name: LLM_GATEWAY_URL
          value: http://litellm-proxy.agentgateway-system.svc.cluster.local:4000
```

### Blue-Green with Argo Rollouts

Progressive delivery with traffic switching:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
spec:
  strategy:
    blueGreen:
      activeService: strands-agent-stable
      previewService: strands-agent-preview
      autoPromotionEnabled: true
      autoPromotionSeconds: 10
```

### OAM Application

Declarative with KubeVela:
```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
spec:
  components:
  - name: assistant
    type: agent  # Uses agent.cue ComponentDefinition
    properties:
      modelConfig:
        modelId: claude-sonnet
        llmGatewayUrl: http://litellm-proxy...
```

## Troubleshooting

### Agent can't reach LLM Gateway

```bash
# Check gateway is running
kubectl get pods -n agentgateway-system -l app=litellm-proxy

# Test from agent pod
kubectl exec -it strands-agent-xxx -- curl http://litellm-proxy.agentgateway-system.svc.cluster.local:4000/health
```

### Gateway can't authenticate to Bedrock

```bash
# Check pod identity
kubectl describe sa litellm-proxy -n agentgateway-system

# Check IAM role
aws iam get-role --role-name litellm-bedrock-role
```

### A2A requests failing

```bash
# Check agent logs
kubectl logs strands-agent-xxx

# Test agent directly
kubectl port-forward strands-agent-xxx 8083:8083
curl http://localhost:8083/health
curl http://localhost:8083/.well-known/agent.json
```

## References

- [Strands A2A Documentation](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/agent-to-agent/)
- [A2A Protocol Spec](https://a2a-protocol.org/)
- [LiteLLM Proxy](https://docs.litellm.ai/docs/proxy/quick_start)
- [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)
