# Consistent Hashing for Multi-Replica Scaling

This guide explains how to use consistent hashing with kgateway to enable multi-replica deployments with in-memory TaskStore.

## Overview

**Problem**: With in-memory TaskStore, each pod has separate Task storage. Kubernetes Service uses round-robin load balancing, so requests with the same contextId may go to different pods.

**Solution**: Use kgateway's consistent hashing to route requests based on contextId. Same contextId always goes to the same pod (as long as the pod is healthy).

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Client Request                        │
│         POST /message with contextId in body            │
│         X-Context-ID: ctx-123 (header)                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│              kgateway (Kubernetes Gateway)              │
│         Consistent Hashing (RING_HASH or MAGLEV)        │
│         Hash(X-Context-ID) → Backend Pod                │
└────────┬────────────────┬────────────────┬──────────────┘
         │                │                │
         ↓                ↓                ↓
    ┌────────┐       ┌────────┐      ┌────────┐
    │ Pod A  │       │ Pod B  │      │ Pod C  │
    │ ctx-123│       │ ctx-456│      │ ctx-789│
    │ ctx-124│       │ ctx-457│      │ ctx-790│
    └────────┘       └────────┘      └────────┘
```

## How It Works

1. **Client sends request** with contextId in A2A message body
2. **Client or gateway adds X-Context-ID header** from contextId
3. **kgateway hashes the header** using Ringhash or Maglev algorithm
4. **Request routes to specific pod** based on hash
5. **Same contextId always routes to same pod** (until pod changes)

## Prerequisites

- Kubernetes cluster with Gateway API support
- kgateway installed (part of AgentGateway or standalone)
- Strands agent deployed with multiple replicas

## Implementation

### Step 1: Deploy BackendConfigPolicy

Choose between Ringhash (tunable) or Maglev (faster):

```yaml
# deployment/kgateway-session-affinity.yaml
apiVersion: gateway.kgateway.dev/v1
kind: BackendConfigPolicy
metadata:
  name: strands-agent-session-affinity
  namespace: default
spec:
  targetRefs:
  - group: ""
    kind: Service
    name: strands-agent
  
  config:
    loadBalancer:
      type: RING_HASH  # or MAGLEV
      
      ringHashConfig:
        minimumRingSize: 1024
        maximumRingSize: 8192
      
      hashPolicies:
      # Primary: Hash by X-Context-ID header
      - header:
          name: X-Context-ID
        terminal: true
      
      # Fallback: Hash by source IP
      - sourceIP: true
        terminal: true
```

Apply the policy:

```bash
kubectl apply -f deployment/kgateway-session-affinity.yaml
```

### Step 2: Configure Client to Send X-Context-ID Header

The client must extract contextId from the A2A message and add it as a header.

#### Option A: Client-Side Implementation

```python
import requests
import json

def send_a2a_message(url, message, context_id=None):
    """Send A2A message with X-Context-ID header."""
    headers = {"Content-Type": "application/json"}
    
    # Add contextId as header for consistent hashing
    if context_id:
        headers["X-Context-ID"] = context_id
    
    payload = {"message": message}
    
    # Also include contextId in message body (A2A protocol)
    if context_id:
        payload["message"]["contextId"] = context_id
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

# First request (no contextId)
response1 = send_a2a_message(
    "http://agents.example.com/strands-agent/message",
    {
        "role": "ROLE_USER",
        "parts": [{"text": "Hello"}],
        "messageId": "msg-1"
    }
)

# Extract contextId from response
context_id = response1["task"]["contextId"]

# Follow-up request (with contextId)
response2 = send_a2a_message(
    "http://agents.example.com/strands-agent/message",
    {
        "role": "ROLE_USER",
        "parts": [{"text": "Continue"}],
        "messageId": "msg-2"
    },
    context_id=context_id  # Routes to same pod
)
```

#### Option B: Gateway-Side Extraction (Future)

AgentGateway could be enhanced to automatically extract contextId from A2A message body and add as header. This would require:

1. Gateway parses A2A message body
2. Extracts `message.contextId` field
3. Adds `X-Context-ID` header
4. Forwards to backend with header

**Note**: This is not currently implemented in AgentGateway.

#### Option C: Middleware in Agent (Limited)

You can add middleware to log contextId, but you cannot modify request headers after the body is read:

```python
# app/main.py
from .middleware import add_context_id_middleware

# Add middleware
add_context_id_middleware(app)
```

See `app/middleware.py` for implementation.

### Step 3: Deploy with Multiple Replicas

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: strands-agent
spec:
  replicas: 3  # Now supported with consistent hashing!
  template:
    spec:
      containers:
      - name: agent
        image: strands-agent:latest
        # ... rest of config
```

### Step 4: Verify Consistent Hashing

```bash
# Scale to 3 replicas
kubectl scale deployment strands-agent --replicas=3

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=strands-agent --timeout=60s

# Send first message (no contextId)
curl -X POST http://agents.example.com/strands-agent/message \
  -H 'Content-Type: application/json' \
  -d '{
    "message": {
      "role": "ROLE_USER",
      "parts": [{"text": "Hello"}],
      "messageId": "msg-1"
    }
  }'

# Response includes contextId
# {
#   "task": {
#     "id": "task-123",
#     "contextId": "ctx-456",
#     ...
#   }
# }

# Send 10 follow-up messages with same contextId
for i in {1..10}; do
  curl -X POST http://agents.example.com/strands-agent/message \
    -H 'Content-Type: application/json' \
    -H 'X-Context-ID: ctx-456' \
    -d "{
      \"message\": {
        \"role\": \"ROLE_USER\",
        \"parts\": [{\"text\": \"Message $i\"}],
        \"messageId\": \"msg-$i\",
        \"contextId\": \"ctx-456\"
      }
    }"
done

# Check logs - all 10 requests should go to same pod
kubectl logs -l app=strands-agent --tail=20
```

## Hash Algorithms

### Ringhash

**Best for**: Custom tuning, fine-grained control

```yaml
loadBalancer:
  type: RING_HASH
  ringHashConfig:
    minimumRingSize: 1024  # Smaller = less memory, less precision
    maximumRingSize: 8192  # Larger = more memory, more precision
```

**Pros**:
- Tunable ring size
- Fine-grained control over distribution
- Good for specific workload requirements

**Cons**:
- May have performance cost
- Requires tuning

**When to use**:
- Need custom load distribution
- Have specific memory constraints
- Want to optimize for your workload

### Maglev

**Best for**: General-purpose, fast routing

```yaml
loadBalancer:
  type: MAGLEV
```

**Pros**:
- Fixed lookup table (65,357 entries)
- Optimized for speed
- Deterministic performance
- No tuning needed

**Cons**:
- Fixed table size (no tuning)
- May use more memory than small Ringhash

**When to use**:
- General-purpose workloads
- Want fast, predictable performance
- Don't need custom tuning

## Hash Policies

### Header-Based (Recommended for A2A)

```yaml
hashPolicies:
- header:
    name: X-Context-ID
  terminal: true
```

**Use case**: Route by A2A contextId

### Cookie-Based

```yaml
hashPolicies:
- cookie:
    name: session-id
    ttl: 3600s
    path: /
  terminal: true
```

**Use case**: Browser-based clients with cookies

### Source IP-Based

```yaml
hashPolicies:
- sourceIP: true
  terminal: true
```

**Use case**: Fallback when no header/cookie available

### Multiple Policies with Fallback

```yaml
hashPolicies:
# Try header first
- header:
    name: X-Context-ID
  terminal: true

# Fallback to cookie
- cookie:
    name: session-id
    ttl: 3600s
  terminal: true

# Final fallback to source IP
- sourceIP: true
  terminal: true
```

**Use case**: Support multiple client types

## Limitations

### 1. Affinity Lost on Pod Changes

When pods are added, removed, or restarted, the hash ring changes and affinity may be lost.

**Mitigation**:
- Use stable pod count
- Implement graceful shutdown
- Use persistent TaskStore for critical workloads

### 2. Requires Header Propagation

contextId must be in request header, not just message body.

**Mitigation**:
- Client adds X-Context-ID header
- Or gateway extracts and adds header
- Or use persistent TaskStore

### 3. Not True Sticky Sessions

Consistent hashing is "soft" affinity, not "strong" sticky sessions.

**Mitigation**:
- For strong stickiness, use persistent TaskStore
- Or use session persistence (cookie-based)

## Comparison: Session Affinity Options

| Feature | ClientIP | Consistent Hashing | Persistent TaskStore |
|---------|----------|-------------------|---------------------|
| **Routes by contextId** | ❌ | ✅ | ✅ |
| **Survives IP change** | ❌ | ✅ | ✅ |
| **Survives pod restart** | ❌ | ❌ | ✅ |
| **Survives scaling** | ❌ | ⚠️ | ✅ |
| **Multiple replicas** | ⚠️ | ✅ | ✅ |
| **Complexity** | Low | Medium | High |
| **Requires kgateway** | ❌ | ✅ | ❌ |
| **Requires header** | ❌ | ✅ | ❌ |
| **Production ready** | Limited | Yes | Yes |

## When to Use Consistent Hashing

### ✅ Good Use Cases

- **Development/staging** with multiple replicas
- **Production** with stable pod count
- **Short-lived conversations** (minutes to hours)
- **Clients that can add headers**
- **Using kgateway** or Kubernetes Gateway API

### ❌ Not Recommended

- **Long-lived conversations** (days to weeks)
- **Frequent scaling** up/down
- **Critical conversations** that cannot be lost
- **Clients that cannot add headers**
- **Not using kgateway**

### 🎯 Best Practice

Use consistent hashing as a **performance optimization** for multi-replica deployments, but implement **persistent TaskStore** for production robustness.

## Troubleshooting

### Requests still going to different pods

```bash
# Check BackendConfigPolicy is applied
kubectl get backendconfigpolicy strands-agent-session-affinity -o yaml

# Check if X-Context-ID header is present
kubectl logs -l app=strands-agent --tail=50 | grep "X-Context-ID"

# Test with explicit header
curl -X POST http://agents.example.com/strands-agent/message \
  -H 'X-Context-ID: test-123' \
  -H 'Content-Type: application/json' \
  -d '{"message": {"role": "ROLE_USER", "parts": [{"text": "test"}]}}'
```

### Hash ring not updating

```bash
# Check kgateway logs
kubectl logs -n agentgateway-system -l app=kgateway

# Restart kgateway
kubectl rollout restart deployment -n agentgateway-system kgateway
```

### Affinity lost after scaling

This is expected behavior. Consistent hashing affinity is lost when the hash ring changes (pods added/removed).

**Solution**: Use persistent TaskStore for production.

## References

- [kgateway Consistent Hashing](https://kgateway.dev/docs/envoy/main/traffic-management/session-affinity/consistent-hashing/)
- [Envoy Ringhash](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers#ring-hash)
- [Envoy Maglev](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers#maglev)
- [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)
- [A2A Protocol Specification](https://a2a-protocol.org/)

## Next Steps

1. **Try it**: Deploy with consistent hashing in development
2. **Test it**: Verify same contextId routes to same pod
3. **Monitor it**: Watch for affinity loss during scaling
4. **Upgrade it**: Implement persistent TaskStore for production
