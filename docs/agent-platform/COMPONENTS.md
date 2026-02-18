# Agent Platform Components

This document provides detailed specifications for each component in the agent platform.

## Table of Contents

1. [Kagent](#kagent)
2. [LiteLLM](#litellm)
3. [Agent Gateway](#agent-gateway)
4. [Langfuse](#langfuse)
5. [Jaeger](#jaeger)
6. [Tofu Controller](#tofu-controller)
7. [Agent Core Components](#agent-core-components)

---

## Kagent

### Overview

Kagent is a Kubernetes-native AI agent framework that enables building and deploying AI agents as Kubernetes custom resources.

### Architecture

```
┌─────────────────────────────────────────┐
│         Kagent Operator                 │
│  ┌───────────────────────────────────┐  │
│  │   Agent Controller                │  │
│  │   - Watches Agent CRs             │  │
│  │   - Manages agent lifecycle       │  │
│  │   - Handles model interactions    │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   ModelConfig Controller          │  │
│  │   - Manages model configurations  │  │
│  │   - Handles provider settings     │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   ToolServer Controller           │  │
│  │   - Manages tool integrations     │  │
│  │   - Handles tool execution        │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Custom Resource Definitions

#### Agent CRD

```yaml
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: example-agent
  namespace: agent-platform
spec:
  systemPrompt: "You are a helpful assistant"
  modelConfig:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
    temperature: 0.7
    maxTokens: 4096
  tools:
    - name: kubernetes
      type: builtin
    - name: custom-tool
      type: external
      endpoint: http://tool-server:8080
  memory:
    enabled: true
    type: redis
    endpoint: redis://redis:6379
```

#### ModelConfig CRD

```yaml
apiVersion: kagent.dev/v1alpha1
kind: ModelConfig
metadata:
  name: bedrock-claude
  namespace: agent-platform
spec:
  provider: bedrock
  model: anthropic.claude-3-5-sonnet-20241022-v2:0
  region: us-east-1
  credentials:
    type: irsa
    serviceAccount: kagent
  parameters:
    temperature: 0.7
    maxTokens: 4096
    topP: 0.9
```

#### ToolServer CRD

```yaml
apiVersion: kagent.dev/v1alpha1
kind: ToolServer
metadata:
  name: kubernetes-tools
  namespace: agent-platform
spec:
  endpoint: http://k8s-tool-server:8080
  authentication:
    type: serviceAccount
  tools:
    - name: get-pods
      description: "Get list of pods in a namespace"
    - name: describe-pod
      description: "Get detailed information about a pod"
```

### Installation

Kagent is installed via two ArgoCD Applications:

1. **kagent-crds** (sync wave -4): Installs CRDs
2. **kagent** (sync wave 0): Installs operator

```yaml
# Chart reference
repository: oci://public.ecr.aws/kagent-dev/kagent
version: 0.7.9
```

### Configuration

```yaml
kagent:
  version: "0.7.9"
  
  # Operator settings
  operator:
    replicas: 1
    resources:
      requests:
        memory: "512Mi"
        cpu: "250m"
      limits:
        memory: "1Gi"
        cpu: "500m"
  
  # Default model configuration
  defaultModelConfig:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
    region: us-east-1
  
  # Service account with IRSA
  serviceAccount:
    create: true
    annotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::ACCOUNT:role/KagentRole"
  
  # Observability
  tracing:
    enabled: true
    endpoint: http://jaeger-collector:14268/api/traces
  
  metrics:
    enabled: true
    port: 8080
```

### IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:*:*:foundation-model/*"
    }
  ]
}
```

### Metrics

- `kagent_agent_requests_total` - Total agent requests
- `kagent_agent_request_duration_seconds` - Request latency histogram
- `kagent_agent_errors_total` - Error count by type
- `kagent_model_tokens_used` - Token usage by model
- `kagent_tool_invocations_total` - Tool invocation count

---

## LiteLLM

### Overview

LiteLLM is a unified interface for multiple LLM providers, providing a consistent API across OpenAI, Anthropic, AWS Bedrock, and others.

### Architecture

```
┌─────────────────────────────────────────┐
│           LiteLLM Gateway               │
│  ┌───────────────────────────────────┐  │
│  │   API Server                      │  │
│  │   - OpenAI-compatible API         │  │
│  │   - Request routing               │  │
│  │   - Response streaming            │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   Provider Adapters               │  │
│  │   - Bedrock adapter               │  │
│  │   - OpenAI adapter                │  │
│  │   - Anthropic adapter             │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   Caching Layer                   │  │
│  │   - Response caching              │  │
│  │   - Cost optimization             │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm
  namespace: agent-platform
spec:
  replicas: 2
  selector:
    matchLabels:
      app: litellm
  template:
    metadata:
      labels:
        app: litellm
    spec:
      serviceAccountName: litellm
      containers:
        - name: litellm
          image: ghcr.io/berriai/litellm:latest
          ports:
            - containerPort: 4000
              name: http
          env:
            - name: AWS_REGION
              value: "us-east-1"
            - name: LITELLM_LOG_LEVEL
              value: "INFO"
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 4000
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 4000
            initialDelaySeconds: 10
            periodSeconds: 5
```

### Configuration

```yaml
litellm:
  replicas: 2
  
  image:
    repository: ghcr.io/berriai/litellm
    tag: latest
    pullPolicy: IfNotPresent
  
  # Provider configuration
  providers:
    - name: bedrock
      enabled: true
      region: us-east-1
      models:
        - anthropic.claude-3-5-sonnet-20241022-v2:0
        - anthropic.claude-3-sonnet-20240229-v1:0
        - anthropic.claude-3-haiku-20240307-v1:0
    
    - name: openai
      enabled: false
      apiKeySecret: litellm-openai-key
  
  # Caching
  cache:
    enabled: true
    type: redis
    endpoint: redis://redis:6379
    ttl: 3600
  
  # Rate limiting
  rateLimit:
    enabled: true
    requestsPerMinute: 100
  
  # Autoscaling
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
  
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "1Gi"
      cpu: "500m"
```

### API Usage

```bash
# Health check
curl http://litellm.agent-platform:4000/health

# List models
curl http://litellm.agent-platform:4000/models

# Chat completion (OpenAI-compatible)
curl -X POST http://litellm.agent-platform:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Metrics

- `litellm_requests_total` - Total requests by provider
- `litellm_request_duration_seconds` - Request latency
- `litellm_errors_total` - Errors by provider and type
- `litellm_tokens_used` - Token usage by model
- `litellm_cache_hits_total` - Cache hit rate

---

## Agent Gateway

### Overview

Agent Gateway provides API gateway functionality for agent requests, including authentication, rate limiting, and request routing.

### Features

- Request authentication and authorization
- Rate limiting per user/API key
- Request/response logging
- Metrics collection
- Integration with LiteLLM

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-gateway
  namespace: agent-platform
spec:
  replicas: 2
  selector:
    matchLabels:
      app: agent-gateway
  template:
    metadata:
      labels:
        app: agent-gateway
    spec:
      containers:
        - name: agent-gateway
          image: agent-gateway:latest
          ports:
            - containerPort: 8080
              name: http
          env:
            - name: LITELLM_ENDPOINT
              value: "http://litellm:4000"
            - name: AUTH_ENABLED
              value: "true"
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "250m"
```

### Configuration

```yaml
agentGateway:
  replicas: 2
  
  # Backend configuration
  backend:
    litellmEndpoint: "http://litellm:4000"
    timeout: 30s
  
  # Authentication
  auth:
    enabled: true
    type: jwt
    jwksUrl: "https://keycloak/realms/platform/protocol/openid-connect/certs"
  
  # Rate limiting
  rateLimit:
    enabled: true
    requestsPerMinute: 60
    burstSize: 10
  
  # Logging
  logging:
    level: info
    format: json
    destination: stdout
  
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "512Mi"
      cpu: "250m"
```

---

## Langfuse

### Overview

Langfuse is an open-source LLM observability and analytics platform for tracking, debugging, and improving LLM applications.

### Architecture

```
┌─────────────────────────────────────────┐
│           Langfuse Platform             │
│  ┌───────────────────────────────────┐  │
│  │   Web UI                          │  │
│  │   - Trace visualization           │  │
│  │   - Analytics dashboard           │  │
│  │   - User management               │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   API Server                      │  │
│  │   - Ingestion API                 │  │
│  │   - Query API                     │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   PostgreSQL Database             │  │
│  │   - Traces storage                │  │
│  │   - Spans storage                 │  │
│  │   - Observations storage          │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   Redis Cache                     │  │
│  │   - Session cache                 │  │
│  │   - Query cache                   │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Deployment

```yaml
# Langfuse application
apiVersion: apps/v1
kind: Deployment
metadata:
  name: langfuse
  namespace: agent-platform
spec:
  replicas: 1
  selector:
    matchLabels:
      app: langfuse
  template:
    metadata:
      labels:
        app: langfuse
    spec:
      containers:
        - name: langfuse
          image: langfuse/langfuse:latest
          ports:
            - containerPort: 3000
              name: http
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: langfuse-postgres
                  key: connection-string
            - name: REDIS_URL
              value: "redis://redis:6379"
            - name: NEXTAUTH_URL
              value: "http://langfuse.agent-platform:3000"
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "2Gi"
              cpu: "1000m"

---
# PostgreSQL StatefulSet
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: langfuse-postgres
  namespace: agent-platform
spec:
  serviceName: langfuse-postgres
  replicas: 1
  selector:
    matchLabels:
      app: langfuse-postgres
  template:
    metadata:
      labels:
        app: langfuse-postgres
    spec:
      containers:
        - name: postgres
          image: postgres:15
          ports:
            - containerPort: 5432
              name: postgres
          env:
            - name: POSTGRES_DB
              value: langfuse
            - name: POSTGRES_USER
              value: langfuse
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: langfuse-postgres
                  key: password
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
          resources:
            requests:
              memory: "1Gi"
              cpu: "500m"
            limits:
              memory: "2Gi"
              cpu: "1000m"
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

### Configuration

```yaml
langfuse:
  replicas: 1
  
  image:
    repository: langfuse/langfuse
    tag: latest
  
  # PostgreSQL configuration
  postgres:
    enabled: true
    storage: 10Gi
    resources:
      requests:
        memory: "1Gi"
        cpu: "500m"
      limits:
        memory: "2Gi"
        cpu: "1000m"
  
  # Redis configuration
  redis:
    enabled: true
    resources:
      requests:
        memory: "256Mi"
        cpu: "100m"
  
  # Ingress
  ingress:
    enabled: true
    host: langfuse.example.com
    tls:
      enabled: true
  
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "2Gi"
      cpu: "1000m"
```

### Usage

```python
# Python SDK
from langfuse import Langfuse

langfuse = Langfuse(
    public_key="pk-...",
    secret_key="sk-...",
    host="http://langfuse.agent-platform:3000"
)

# Create trace
trace = langfuse.trace(name="agent-request")

# Add span
span = trace.span(name="llm-call")

# Add observation
span.generation(
    name="claude-response",
    model="anthropic.claude-3-5-sonnet-20241022-v2:0",
    input="Hello",
    output="Hi there!",
    usage={"input_tokens": 10, "output_tokens": 5}
)
```

---

## Jaeger

### Overview

Jaeger is an open-source distributed tracing system for monitoring and troubleshooting microservices-based architectures.

### Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  namespace: agent-platform
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jaeger
  template:
    metadata:
      labels:
        app: jaeger
    spec:
      containers:
        - name: jaeger
          image: jaegertracing/all-in-one:1.52
          ports:
            - containerPort: 16686
              name: ui
            - containerPort: 14268
              name: collector
            - containerPort: 9411
              name: zipkin
          env:
            - name: COLLECTOR_ZIPKIN_HOST_PORT
              value: ":9411"
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "500m"
```

### Configuration

```yaml
jaeger:
  allInOne:
    enabled: true
    image: jaegertracing/all-in-one:1.52
  
  storage:
    type: memory
    memory:
      maxTraces: 100000
  
  # For production, use persistent storage
  # storage:
  #   type: elasticsearch
  #   elasticsearch:
  #     host: elasticsearch:9200
  
  ingress:
    enabled: true
    host: jaeger.example.com
  
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "1Gi"
      cpu: "500m"
```

---

## Tofu Controller

### Overview

Tofu Controller is a Kubernetes operator for managing Terraform/OpenTofu resources via Kubernetes custom resources.

### Architecture

```
┌─────────────────────────────────────────┐
│       Tofu Controller Operator          │
│  ┌───────────────────────────────────┐  │
│  │   Terraform Controller            │  │
│  │   - Watches Terraform CRs         │  │
│  │   - Executes terraform commands   │  │
│  │   - Manages state                 │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │   Source Controller               │  │
│  │   - Fetches Terraform modules     │  │
│  │   - Manages Git sources           │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Terraform CRD

```yaml
apiVersion: infra.contrib.fluxcd.io/v1alpha2
kind: Terraform
metadata:
  name: agent-core
  namespace: agent-platform
spec:
  interval: 10m
  path: ./terraform
  sourceRef:
    kind: GitRepository
    name: agent-core-terraform
    namespace: flux-system
  approvePlan: auto
  destroyResourcesOnDeletion: true
  writeOutputsToSecret:
    name: agent-core-outputs
  vars:
    - name: project_name
      value: "ekspoc-v4"
    - name: region
      value: "us-east-1"
  varsFrom:
    - kind: Secret
      name: aws-credentials
  serviceAccountName: tofu-controller
```

### Configuration

```yaml
tofuController:
  replicas: 1
  
  image:
    repository: ghcr.io/flux-iac/tofu-controller
    tag: latest
  
  serviceAccount:
    create: true
    annotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::ACCOUNT:role/TofuControllerRole"
  
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
    limits:
      memory: "2Gi"
      cpu: "1000m"
```

---

## Agent Core Components

### Overview

Agent Core Components provision AWS Bedrock Agent Core capabilities (Memory, Browser, Code Interpreter) using Tofu Controller.

### Terraform Configuration

```hcl
# terraform/main.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

module "agent_core" {
  source = "git::https://github.com/elamaran11/eks-agent-core-pocs.git//terraform/modules/agent-core"
  
  project_name = var.project_name
  version      = var.version
  
  capabilities = {
    memory           = var.enable_memory
    browser          = var.enable_browser
    code_interpreter = var.enable_code_interpreter
  }
  
  network_mode = var.network_mode
}

output "memory_capability_id" {
  value = module.agent_core.memory_capability_id
}

output "browser_capability_id" {
  value = module.agent_core.browser_capability_id
}

output "code_interpreter_capability_id" {
  value = module.agent_core.code_interpreter_capability_id
}
```

### Kubernetes Integration

```yaml
# Terraform CR
apiVersion: infra.contrib.fluxcd.io/v1alpha2
kind: Terraform
metadata:
  name: agent-core
  namespace: agent-platform
spec:
  interval: 10m
  path: ./terraform
  sourceRef:
    kind: GitRepository
    name: agent-core-terraform
  approvePlan: auto
  writeOutputsToSecret:
    name: agent-core-outputs
  vars:
    - name: project_name
      value: "ekspoc-v4"
    - name: enable_memory
      value: "true"
    - name: enable_browser
      value: "true"
    - name: enable_code_interpreter
      value: "true"

---
# Agent deployment using outputs
apiVersion: apps/v1
kind: Deployment
metadata:
  name: strands-agent
  namespace: agent-platform
spec:
  replicas: 1
  selector:
    matchLabels:
      app: strands-agent
  template:
    metadata:
      labels:
        app: strands-agent
    spec:
      serviceAccountName: strands-agent
      containers:
        - name: agent
          image: strands-agent:latest
          env:
            - name: MEMORY_CAPABILITY_ID
              valueFrom:
                secretKeyRef:
                  name: agent-core-outputs
                  key: memory_capability_id
            - name: BROWSER_CAPABILITY_ID
              valueFrom:
                secretKeyRef:
                  name: agent-core-outputs
                  key: browser_capability_id
            - name: CODE_INTERPRETER_CAPABILITY_ID
              valueFrom:
                secretKeyRef:
                  name: agent-core-outputs
                  key: code_interpreter_capability_id
```

### Configuration

```yaml
agentCore:
  enabled: false  # Disabled by default
  
  terraform:
    version: "v4"
    projectName: "ekspoc-v4"
    region: "us-east-1"
  
  capabilities:
    memory: true
    browser: true
    codeInterpreter: true
  
  networkMode: "PUBLIC"
  
  agent:
    image: strands-agent:latest
    replicas: 1
    resources:
      requests:
        memory: "512Mi"
        cpu: "250m"
```

---

## Component Dependencies

```
Tofu Controller (Wave -1)
    ↓
Kagent CRDs (Wave -4)
    ↓
Kagent, Jaeger (Wave 0)
    ↓
LiteLLM, Langfuse (Wave 1)
    ↓
Agent Gateway (Wave 2)
    ↓
Agent Core (Wave 3)
```

## Resource Requirements

| Component | CPU Request | Memory Request | CPU Limit | Memory Limit | Storage |
|-----------|-------------|----------------|-----------|--------------|---------|
| Kagent | 250m | 512Mi | 500m | 1Gi | - |
| LiteLLM | 250m | 512Mi | 500m | 1Gi | - |
| Agent Gateway | 100m | 256Mi | 250m | 512Mi | - |
| Langfuse | 250m | 512Mi | 1000m | 2Gi | - |
| Langfuse PostgreSQL | 500m | 1Gi | 1000m | 2Gi | 10Gi |
| Jaeger | 250m | 512Mi | 500m | 1Gi | - |
| Tofu Controller | 250m | 512Mi | 1000m | 2Gi | - |
| Agent Core | 250m | 512Mi | 500m | 1Gi | - |

**Total per cluster**: ~2.5 vCPUs, ~6 GB RAM, ~10 GB storage

---

## Version Compatibility

| Component | Version | Kubernetes | Notes |
|-----------|---------|------------|-------|
| Kagent | 0.7.9 | 1.27+ | Requires CRD support |
| LiteLLM | latest | 1.24+ | Stateless |
| Agent Gateway | latest | 1.24+ | Stateless |
| Langfuse | latest | 1.24+ | Requires PVC |
| Jaeger | 1.52 | 1.24+ | All-in-one mode |
| Tofu Controller | latest | 1.26+ | Requires Flux |

---

## Next Steps

- Read [DESIGN.md](./DESIGN.md) for architecture details
- Read [README.md](./README.md) for deployment guide
- Read [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for common issues
