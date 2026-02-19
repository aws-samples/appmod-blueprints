# Agent Platform Integration Design

## Executive Summary

This document describes the design for integrating agent platform components (Kagent, LiteLLM, Agent Gateway, Langfuse, Jaeger, Tofu Controller, and Agent Core) into the Platform Engineering on EKS solution using a GitOps bridge pattern.

### Key Principles

1. **Separation of Concerns**: Platform infrastructure in `appmod-blueprints`, agent components in `sample-agent-platform-on-eks`
2. **Opt-In Model**: Agent platform is disabled by default, enabled via feature flag
3. **GitOps Bridge**: Lightweight bridge chart references external repository
4. **Backward Compatibility**: Platform Engineering workshop works unchanged
5. **Single Source of Truth**: All agent component charts live in dedicated repository

### Repository Roles

| Repository | Role | Contents |
|------------|------|----------|
| `appmod-blueprints` | Platform Infrastructure | GitOps bridge chart, feature flags, deployment orchestration |
| `sample-agent-platform-on-eks` | Agent Components | All agent platform Helm charts and configurations |
| `eks-agent-core-pocs` | Reference Implementation | POC implementations (referenced, not duplicated) |

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Repository Changes](#repository-changes)
3. [Component Details](#component-details)
4. [Feature Flag Mechanism](#feature-flag-mechanism)
5. [Deployment Flow](#deployment-flow)
6. [Configuration Management](#configuration-management)
7. [Implementation Plan](#implementation-plan)
8. [Testing Strategy](#testing-strategy)
9. [Migration Guide](#migration-guide)

---

## Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Platform Engineering on EKS (Hub Cluster)             │
│                          appmod-blueprints Repository                    │
│                                                                          │
│  ┌──────────────┐         ┌────────────────────────────────────┐        │
│  │   ArgoCD     │────────▶│  Agent Platform Bridge Chart       │        │
│  │  (Control    │         │  (Lightweight GitOps Orchestrator) │        │
│  │   Plane)     │         └────────────────────────────────────┘        │
│  └──────────────┘                        │                              │
│         │                                │                              │
│         │                                ▼                              │
│         │         ┌──────────────────────────────────────────┐          │
│         │         │  Feature Flag: agent-platform            │          │
│         │         │  - enabled: false (default)              │          │
│         │         │  - enabled: true (agent workshop)        │          │
│         │         └──────────────────────────────────────────┘          │
│         │                                │                              │
│         │                                │ (if enabled)                 │
│         │                                ▼                              │
│         │         ┌──────────────────────────────────────────┐          │
│         │         │  ArgoCD Applications (Individual)        │          │
│         │         │  - kagent-application.yaml               │          │
│         │         │  - litellm-application.yaml              │          │
│         │         │  - agent-gateway-application.yaml        │          │
│         │         │  - langfuse-application.yaml             │          │
│         │         │  - jaeger-application.yaml               │          │
│         │         │  - tofu-controller-application.yaml      │          │
│         │         │  - agent-core-application.yaml           │          │
│         │         └──────────────────────────────────────────┘          │
│         │                                │                              │
└─────────┼────────────────────────────────┼──────────────────────────────┘
          │                                │
          │                                │ Each Application Points to
          │                                │ External Repo Helm Chart
          │                                ▼
┌─────────┼────────────────────────────────────────────────────────────────┐
│         │         sample-agent-platform-on-eks Repository                │
│         │                                                                │
│         │         ┌──────────────────────────────────────────┐          │
│         └────────▶│  gitops/                                 │          │
│                   │  ├── kagent/          (Helm Chart)       │◀─────────│
│                   │  ├── litellm/         (Helm Chart)       │◀─────────│
│                   │  ├── agent-gateway/   (Helm Chart)       │◀─────────│
│                   │  ├── langfuse/        (Helm Chart)       │◀─────────│
│                   │  ├── jaeger/          (Helm Chart)       │◀─────────│
│                   │  ├── tofu-controller/ (Helm Chart)       │◀─────────│
│                   │  └── agent-core/      (Helm Chart)       │◀─────────│
│                   └──────────────────────────────────────────┘          │
│                   Each ArgoCD Application references its chart          │
└─────────────────────────────────────────────────────────────────────────┘
          │
          │ Deploys to
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Spoke Clusters (Dev/Prod)                        │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────┐         │
│  │  Agent Platform Stack (Only if enabled)                    │         │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │         │
│  │  │   Kagent     │  │   LiteLLM    │  │Agent Gateway │     │         │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │         │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │         │
│  │  │  Langfuse    │  │   Jaeger     │  │Tofu Controller│    │         │
│  │  └──────────────┘  └──────────────┘  └──────────────┘     │         │
│  │  ┌────────────────────────────────────────────────────┐   │         │
│  │  │  Agent Core Components (via Tofu Controller)       │   │         │
│  │  │  - Memory, Browser, Code Interpreter               │   │         │
│  │  └────────────────────────────────────────────────────┘   │         │
│  └────────────────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
User Deploys Workshop
         │
         ▼
    Feature Flag Check
    (agent-platform: enabled?)
         │
         ├─── NO ──▶ Platform Engineering Workshop
         │           (Core platform only)
         │
         └─── YES ──▶ Agent Platform Workshop
                      │
                      ▼
              Bridge Chart Activated
                      │
                      ▼
         Creates Individual ArgoCD Applications
         (One per component)
                      │
                      ├─── kagent-application.yaml
                      ├─── litellm-application.yaml
                      ├─── agent-gateway-application.yaml
                      ├─── langfuse-application.yaml
                      ├─── jaeger-application.yaml
                      ├─── tofu-controller-application.yaml
                      └─── agent-core-application.yaml
                      │
                      ▼
         Each Application Points to
         External Repository Helm Chart
         (sample-agent-platform-on-eks/gitops/<component>)
                      │
                      ▼
         Deploys Component Charts
         to Spoke Clusters
```

---

## Repository Changes

### Changes in `appmod-blueprints` Repository

#### 1. New Files to Create

```
appmod-blueprints/
├── docs/
│   └── agent-platform/                          # NEW
│       ├── DESIGN.md                            # This document
│       ├── README.md                            # User guide
│       ├── COMPONENTS.md                        # Component details
│       └── TROUBLESHOOTING.md                   # Common issues
│
├── gitops/
│   ├── addons/
│   │   ├── charts/
│   │   │   └── agent-platform/                  # NEW: Bridge chart
│   │   │       ├── Chart.yaml
│   │   │       ├── values.yaml
│   │   │       ├── README.md
│   │   │       └── templates/
│   │   │           ├── _helpers.tpl
│   │   │           ├── namespace.yaml
│   │   │           ├── kagent-application.yaml
│   │   │           ├── litellm-application.yaml
│   │   │           ├── agent-gateway-application.yaml
│   │   │           ├── langfuse-application.yaml
│   │   │           ├── jaeger-application.yaml
│   │   │           ├── tofu-controller-application.yaml
│   │   │           └── agent-core-application.yaml
│   │   │
│   │   ├── default/
│   │   │   └── addons/
│   │   │       └── agent-platform/              # NEW
│   │   │           └── values.yaml
│   │   │
│   │   └── environments/
│   │       ├── control-plane/
│   │       │   └── addons/
│   │       │       └── agent-platform/          # NEW
│   │       │           └── values.yaml
│   │       │
│   │       └── agent-platform/                  # NEW: Agent workshop env
│   │           └── addons/
│   │               └── agent-platform/
│   │                   └── values.yaml
│   │
│   └── fleet/
│       └── kro-values/
│           └── tenants/
│               └── control-plane/
│                   └── agent-platform/          # NEW
│                       └── values.yaml
│
└── platform/
    └── infra/
        └── terraform/
            ├── variables.tf                     # UPDATE: Add workshop_type
            ├── outputs.tf                       # UPDATE: Add agent platform outputs
            └── scripts/
                └── bootstrap.sh                 # UPDATE: Add feature flag logic
```

#### 2. Files to Modify

**`gitops/addons/bootstrap/default/addons.yaml`**:
```yaml
# ADD at the end:
agent-platform:
  enabled: false  # Disabled by default
```

**`platform/infra/terraform/variables.tf`**:
```hcl
# ADD:
variable "workshop_type" {
  description = "Type of workshop to deploy"
  type        = string
  default     = "platform-engineering"
  validation {
    condition     = contains(["platform-engineering", "agent-platform"], var.workshop_type)
    error_message = "workshop_type must be 'platform-engineering' or 'agent-platform'"
  }
}

variable "enable_agent_platform" {
  description = "Enable agent platform components"
  type        = bool
  default     = false
}
```

**`platform/infra/terraform/outputs.tf`**:
```hcl
# ADD:
output "workshop_type" {
  description = "Workshop type deployed"
  value       = var.workshop_type
}

output "agent_platform_enabled" {
  description = "Whether agent platform is enabled"
  value       = var.enable_agent_platform
}
```

**`README.md`**:
```markdown
# ADD section:
## Workshop Types

### Platform Engineering on EKS (Default)
Standard workshop with core platform components.

### Agent Platform on EKS (Extended)
Includes agent platform components (Kagent, LiteLLM, etc.).

Set `ENABLE_AGENT_PLATFORM=true` to enable.
```

### Changes in `sample-agent-platform-on-eks` Repository

#### 1. New Directory Structure to Create

```
sample-agent-platform-on-eks/
├── gitops/                                      # NEW: All Helm charts
│   ├── kagent/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── README.md
│   │   └── templates/
│   │       ├── _helpers.tpl
│   │       ├── namespace.yaml
│   │       ├── application-crds.yaml
│   │       ├── application-kagent.yaml
│   │       ├── serviceaccount.yaml
│   │       └── NOTES.txt
│   │
│   ├── litellm/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── README.md
│   │   └── templates/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       ├── configmap.yaml
│   │       ├── secret.yaml
│   │       ├── serviceaccount.yaml
│   │       ├── ingress.yaml
│   │       └── hpa.yaml
│   │
│   ├── agent-gateway/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── README.md
│   │   └── templates/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       ├── configmap.yaml
│   │       └── ingress.yaml
│   │
│   ├── langfuse/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── README.md
│   │   └── templates/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       ├── postgres.yaml
│   │       ├── redis.yaml
│   │       └── ingress.yaml
│   │
│   ├── jaeger/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── README.md
│   │   └── templates/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       └── ingress.yaml
│   │
│   ├── tofu-controller/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── README.md
│   │   └── templates/
│   │       ├── namespace.yaml
│   │       ├── application.yaml
│   │       ├── serviceaccount.yaml
│   │       └── rbac.yaml
│   │
│   └── agent-core-components/
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── README.md
│       └── templates/
│           ├── terraform-resource.yaml
│           ├── deployment.yaml
│           ├── serviceaccount.yaml
│           └── configmap.yaml
│
├── 00-initial-setup/                           # EXISTING: Keep as reference
│   └── values.yaml
│
└── README.md                                    # UPDATE: Add GitOps section
```

#### 2. Chart Standardization

All charts should follow this standard structure:

**Chart.yaml Template**:
```yaml
apiVersion: v2
name: <component-name>
description: <Component> for Agent Platform on EKS
type: application
version: 0.1.0
appVersion: "<component-version>"
keywords:
  - agent-platform
  - ai
  - kubernetes
maintainers:
  - name: AWS Samples
    url: https://github.com/aws-samples
```

**values.yaml Template**:
```yaml
# Global settings (inherited from bridge chart)
global:
  namespace: agent-platform
  resourcePrefix: peeks

# Component-specific settings
replicaCount: 1

image:
  repository: <image-repo>
  tag: <version>
  pullPolicy: IfNotPresent

resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"

# ... component-specific configuration
```

---

## Component Details

### 1. Kagent (Kubernetes Native AI Agent Framework)

**Purpose**: Cloud-native agentic AI framework for Kubernetes

**Chart Location**: `sample-agent-platform-on-eks/gitops/kagent/`

**Key Resources**:
- CRDs Application (sync wave -4)
- Kagent Operator Application (sync wave 0)
- ServiceAccount with IRSA
- Agent CRDs: Agent, ModelConfig, ToolServer

**OCI Registry**: `oci://public.ecr.aws/kagent-dev/kagent`

**Version**: 0.7.9

**Dependencies**: None

**Configuration**:
```yaml
kagent:
  version: "0.7.9"
  llmProvider: "bedrock"
  region: "us-east-1"
  modelConfig:
    provider: "bedrock"
    model: "anthropic.claude-3-5-sonnet-20241022-v2:0"
```

### 2. LiteLLM (LLM Gateway)

**Purpose**: Unified interface for multiple LLM providers

**Chart Location**: `sample-agent-platform-on-eks/gitops/litellm/`

**Key Resources**:
- Deployment
- Service (ClusterIP)
- ConfigMap (provider configuration)
- Secret (API keys)
- HPA (optional)
- Ingress (optional)

**Image**: `ghcr.io/berriai/litellm:latest`

**Dependencies**: None

**Configuration**:
```yaml
litellm:
  replicas: 2
  providers:
    - bedrock
    - openai
    - anthropic
  resources:
    requests:
      memory: "512Mi"
      cpu: "250m"
```

### 3. Agent Gateway

**Purpose**: API gateway for agent requests

**Chart Location**: `sample-agent-platform-on-eks/gitops/agent-gateway/`

**Key Resources**:
- Deployment
- Service
- ConfigMap
- Ingress

**Dependencies**: LiteLLM (optional)

**Configuration**:
```yaml
agentGateway:
  replicas: 2
  litellmEndpoint: "http://litellm:4000"
```

### 4. Langfuse (LLM Observability)

**Purpose**: Observability and analytics for LLM applications

**Chart Location**: `sample-agent-platform-on-eks/gitops/langfuse/`

**Key Resources**:
- Deployment (Langfuse)
- Service
- PostgreSQL StatefulSet
- Redis Deployment
- PVC for PostgreSQL
- Ingress

**Image**: `langfuse/langfuse:latest`

**Dependencies**: PostgreSQL, Redis

**Configuration**:
```yaml
langfuse:
  replicas: 1
  postgres:
    enabled: true
    storage: 10Gi
  redis:
    enabled: true
```

### 5. Jaeger (Distributed Tracing)

**Purpose**: Distributed tracing for agent workflows

**Chart Location**: `sample-agent-platform-on-eks/gitops/jaeger/`

**Key Resources**:
- Deployment (All-in-one)
- Service
- Ingress

**Image**: `jaegertracing/all-in-one:latest`

**Dependencies**: None

**Configuration**:
```yaml
jaeger:
  allInOne:
    enabled: true
  storage:
    type: memory
```

### 6. Tofu Controller (Terraform Operator)

**Purpose**: Manage Terraform resources via Kubernetes CRs

**Chart Location**: `sample-agent-platform-on-eks/gitops/tofu-controller/`

**Key Resources**:
- Namespace (flux-system)
- Deployment
- ServiceAccount with IAM role
- RBAC (ClusterRole, ClusterRoleBinding)
- CRDs (Terraform)

**Image**: `ghcr.io/flux-iac/tofu-controller:latest`

**Dependencies**: Flux source-controller, notification-controller

**Configuration**:
```yaml
tofuController:
  serviceAccount:
    annotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::ACCOUNT:role/TofuControllerRole"
```

### 7. Agent Core Components

**Purpose**: AWS Bedrock Agent Core capabilities (Memory, Browser, Code Interpreter)

**Chart Location**: `sample-agent-platform-on-eks/gitops/agent-core-components/`

**Key Resources**:
- Terraform CR (provisions AWS resources)
- Deployment (Strands agent)
- ServiceAccount with Pod Identity
- ConfigMap (capability IDs from Terraform outputs)

**Dependencies**: Tofu Controller, AWS Bedrock Agent Core

**Configuration**:
```yaml
agentCore:
  version: "v4"
  projectName: "ekspoc-v4"
  capabilities:
    memory: true
    browser: true
    codeInterpreter: true
  networkMode: "PUBLIC"
```

---

## Feature Flag Mechanism

### Implementation Levels

The feature flag is implemented at multiple levels for flexibility:

#### Level 1: Bootstrap Configuration (Default)

**File**: `gitops/addons/bootstrap/default/addons.yaml`

```yaml
# Core platform addons (always enabled)
argocd:
  enabled: true
backstage:
  enabled: true
keycloak:
  enabled: true

# Agent platform (disabled by default)
agent-platform:
  enabled: false  # ← Default: Platform Engineering workshop
```

#### Level 2: Environment Override

**Platform Engineering Workshop** (`gitops/addons/environments/control-plane/addons.yaml`):
```yaml
# No override needed - inherits disabled state
```

**Agent Platform Workshop** (`gitops/addons/environments/agent-platform/addons.yaml`):
```yaml
agent-platform:
  enabled: true  # ← Enable for agent workshop
```

#### Level 3: Infrastructure Parameter

**Terraform** (`platform/infra/terraform/variables.tf`):
```hcl
variable "workshop_type" {
  description = "Workshop type: platform-engineering or agent-platform"
  type        = string
  default     = "platform-engineering"
}

variable "enable_agent_platform" {
  description = "Enable agent platform components"
  type        = bool
  default     = false
}
```

**CloudFormation** (workshop template):
```yaml
Parameters:
  WorkshopType:
    Type: String
    Default: platform-engineering
    AllowedValues:
      - platform-engineering
      - agent-platform
    
  EnableAgentPlatform:
    Type: String
    Default: "false"
    AllowedValues:
      - "true"
      - "false"
```

#### Level 4: Runtime Environment Variable

**Bootstrap Script** (`platform/infra/terraform/scripts/bootstrap.sh`):
```bash
#!/bin/bash

# Feature flag from environment
WORKSHOP_TYPE=${WORKSHOP_TYPE:-"platform-engineering"}
ENABLE_AGENT_PLATFORM=${ENABLE_AGENT_PLATFORM:-"false"}

echo "Workshop Type: $WORKSHOP_TYPE"
echo "Agent Platform: $ENABLE_AGENT_PLATFORM"

# Deploy with appropriate configuration
terraform apply \
  -var="workshop_type=$WORKSHOP_TYPE" \
  -var="enable_agent_platform=$ENABLE_AGENT_PLATFORM"
```

### Decision Matrix

| Workshop Type | Feature Flag | Components Deployed |
|---------------|--------------|---------------------|
| platform-engineering | false | Core platform only |
| platform-engineering | true | Core + Agent platform |
| agent-platform | false | Core platform only (unusual) |
| agent-platform | true | Core + Agent platform |

### Conditional Logic in Bridge Chart

**File**: `gitops/addons/charts/agent-platform/templates/kagent-application.yaml`

```yaml
{{- if .Values.enabled }}
{{- if .Values.components.kagent.enabled }}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .Values.global.resourcePrefix }}-agent-platform-kagent
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: {{ .Values.externalRepo.url }}
    targetRevision: {{ .Values.externalRepo.revision }}
    path: {{ .Values.externalRepo.basePath }}{{ .Values.components.kagent.path }}
    helm:
      valueFiles:
        - values.yaml
      values: |
        global:
          namespace: {{ .Values.global.namespace }}
          resourcePrefix: {{ .Values.global.resourcePrefix }}
          awsRegion: {{ .Values.global.awsRegion }}
          eksClusterName: {{ .Values.global.eksClusterName }}
        {{- with .Values.components.kagent.config }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
  destination:
    server: https://kubernetes.default.svc
    namespace: {{ .Values.global.namespace }}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  info:
    - name: Component
      value: Kagent
    - name: Wave
      value: "{{ .Values.components.kagent.syncWave }}"
{{- end }}
{{- end }}
```

**Similar templates for each component**:
- `litellm-application.yaml`
- `agent-gateway-application.yaml`
- `langfuse-application.yaml`
- `jaeger-application.yaml`
- `tofu-controller-application.yaml`
- `agent-core-application.yaml`

### Verification Commands

```bash
# Check if agent platform is enabled
kubectl get configmap -n argocd -o yaml | grep agent-platform

# Check for agent platform applications
kubectl get applications -n argocd | grep agent-platform

# Should show individual applications:
# peeks-agent-platform-kagent
# peeks-agent-platform-litellm
# peeks-agent-platform-agent-gateway
# peeks-agent-platform-langfuse
# peeks-agent-platform-jaeger
# peeks-agent-platform-tofu-controller
# peeks-agent-platform-agent-core

# If disabled, all above should return empty/not found
```

---

## Deployment Flow

### Scenario 1: Platform Engineering Workshop (Default)

```
User Deploys
     │
     ▼
CloudFormation/Terraform
(workshop_type=platform-engineering)
(enable_agent_platform=false)
     │
     ▼
EKS Cluster Created
     │
     ▼
ArgoCD Installed
     │
     ▼
Bootstrap Configuration Applied
(agent-platform: enabled: false)
     │
     ▼
Core Platform Addons Deployed
- ArgoCD
- Backstage
- Keycloak
- Kro
- etc.
     │
     ▼
✅ Platform Engineering Workshop Ready
❌ No Agent Platform Components
```

### Scenario 2: Agent Platform Workshop

```
User Deploys
     │
     ▼
CloudFormation/Terraform
(workshop_type=agent-platform)
(enable_agent_platform=true)
     │
     ▼
EKS Cluster Created
     │
     ▼
ArgoCD Installed
     │
     ▼
Bootstrap Configuration Applied
(agent-platform: enabled: true)
     │
     ▼
Core Platform Addons Deployed
     │
     ▼
Agent Platform Bridge Chart Activated
     │
     ▼
Individual ArgoCD Applications Created
     │
     ├─▶ Tofu Controller Application (Wave -1)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/tofu-controller
     │       └─▶ Deployed
     │
     ├─▶ Kagent CRDs Application (Wave -4)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/kagent (CRDs)
     │       └─▶ Deployed
     │
     ├─▶ Kagent Application (Wave 0)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/kagent
     │       └─▶ Deployed
     │
     ├─▶ Jaeger Application (Wave 0)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/jaeger
     │       └─▶ Deployed
     │
     ├─▶ LiteLLM Application (Wave 1)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/litellm
     │       └─▶ Deployed
     │
     ├─▶ Langfuse Application (Wave 1)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/langfuse
     │       └─▶ Deployed
     │
     ├─▶ Agent Gateway Application (Wave 2)
     │   └─▶ Points to: sample-agent-platform-on-eks/gitops/agent-gateway
     │       └─▶ Deployed
     │
     └─▶ Agent Core Application (Wave 3)
         └─▶ Points to: sample-agent-platform-on-eks/gitops/agent-core
             └─▶ Terraform CR Created
                 └─▶ Tofu Controller Provisions AWS Resources
                     └─▶ Agent Deployment Created
                         └─▶ Deployed
     │
     ▼
✅ Agent Platform Workshop Ready
✅ All Agent Components Deployed
```

### Sync Wave Strategy

| Wave | Components | Purpose |
|------|------------|---------|
| -4 | Kagent CRDs | Install CRDs before operators |
| -1 | Tofu Controller | Install Terraform operator |
| 0 | Kagent, Jaeger | Core agent infrastructure |
| 1 | LiteLLM, Langfuse | LLM gateway and observability |
| 2 | Agent Gateway | API gateway (depends on LiteLLM) |
| 3 | Agent Core | AWS resources (depends on Tofu Controller) |

### Deployment Timeline

**Platform Engineering Workshop**:
- Total Time: ~15 minutes
- EKS Cluster: 10 minutes
- Core Addons: 5 minutes

**Agent Platform Workshop**:
- Total Time: ~20 minutes
- EKS Cluster: 10 minutes
- Core Addons: 5 minutes
- Agent Components: 5 minutes
  - Tofu Controller: 1 minute
  - Kagent: 1 minute
  - Other components: 2 minutes
  - Agent Core (Terraform): 3 minutes

---

## Configuration Management

### Configuration Hierarchy

Values are merged in this order (later overrides earlier):

```
1. Component Chart Defaults
   (sample-agent-platform-on-eks/gitops/<component>/values.yaml)
         ↓
2. Bridge Chart Defaults
   (appmod-blueprints/gitops/addons/charts/agent-platform/values.yaml)
         ↓
3. Bootstrap Defaults
   (appmod-blueprints/gitops/addons/default/addons/agent-platform/values.yaml)
         ↓
4. Environment Overrides
   (appmod-blueprints/gitops/addons/environments/<env>/addons/agent-platform/values.yaml)
         ↓
5. Tenant Overrides
   (appmod-blueprints/gitops/addons/tenants/<tenant>/addons/agent-platform/values.yaml)
         ↓
6. Cluster-Specific Overrides
   (appmod-blueprints/gitops/addons/tenants/<tenant>/clusters/<cluster>/agent-platform/values.yaml)
```

### Example Configuration Files

#### Bridge Chart Default (`appmod-blueprints/gitops/addons/charts/agent-platform/values.yaml`)

```yaml
enabled: false  # Disabled by default

externalRepo:
  url: "https://github.com/aws-samples/sample-agent-platform-on-eks"
  revision: "main"
  basePath: "gitops/"

global:
  namespace: "agent-platform"
  resourcePrefix: "peeks"
  awsRegion: "us-east-1"
  eksClusterName: "dev"

components:
  kagent:
    enabled: true
    path: "kagent"
    syncWave: "0"
    
  litellm:
    enabled: true
    path: "litellm"
    syncWave: "1"
    
  agentGateway:
    enabled: true
    path: "agent-gateway"
    syncWave: "2"
    
  langfuse:
    enabled: true
    path: "langfuse"
    syncWave: "1"
    
  jaeger:
    enabled: true
    path: "jaeger"
    syncWave: "0"
    
  tofuController:
    enabled: true
    path: "tofu-controller"
    syncWave: "-1"
    
  agentCore:
    enabled: false  # Disabled by default (requires AWS setup)
    path: "agent-core-components"
    syncWave: "3"
```

#### Bootstrap Default (`appmod-blueprints/gitops/addons/default/addons/agent-platform/values.yaml`)

```yaml
components:
  kagent:
    config:
      llmProvider: "bedrock"
      region: "us-east-1"
      resources:
        requests:
          memory: "512Mi"
          cpu: "250m"
        limits:
          memory: "1Gi"
          cpu: "500m"
          
  litellm:
    config:
      replicas: 2
      providers:
        - bedrock
      resources:
        requests:
          memory: "512Mi"
          cpu: "250m"
```

#### Dev Environment (`appmod-blueprints/gitops/addons/environments/dev/addons/agent-platform/values.yaml`)

```yaml
components:
  kagent:
    config:
      replicas: 1
      modelConfig:
        model: "anthropic.claude-3-sonnet-20240229-v1:0"
        
  litellm:
    config:
      replicas: 1
      
  agentCore:
    enabled: true  # Enable in dev for testing
    config:
      version: "v4"
      projectName: "ekspoc-dev-v4"
      capabilities:
        memory: true
        browser: true
        codeInterpreter: true
```

#### Prod Environment (`appmod-blueprints/gitops/addons/environments/prod/addons/agent-platform/values.yaml`)

```yaml
components:
  kagent:
    config:
      replicas: 3
      modelConfig:
        model: "anthropic.claude-3-5-sonnet-20241022-v2:0"
      resources:
        requests:
          memory: "2Gi"
          cpu: "1000m"
        limits:
          memory: "4Gi"
          cpu: "2000m"
      autoscaling:
        enabled: true
        minReplicas: 3
        maxReplicas: 10
        
  litellm:
    config:
      replicas: 3
      autoscaling:
        enabled: true
        
  agentCore:
    enabled: false  # Disabled in prod initially
```

### Configuration Best Practices

1. **Minimal Defaults**: Keep bridge chart defaults minimal
2. **Environment-Specific**: Use environment overrides for dev/prod differences
3. **Security**: Store secrets in AWS Secrets Manager, reference via External Secrets
4. **Resource Limits**: Always set resource requests and limits
5. **Versioning**: Pin component versions in production
6. **Documentation**: Document all configuration options in component READMEs

---

## Implementation Plan

### Phase 1: Foundation (Week 1)

#### In `appmod-blueprints` Repository

**Day 1-2: Bridge Chart Structure**
- [ ] Create `docs/agent-platform/` directory
- [ ] Create `DESIGN.md` (this document)
- [ ] Create `README.md` (user guide)
- [ ] Create `COMPONENTS.md` (component details)
- [ ] Create `gitops/addons/charts/agent-platform/` structure
- [ ] Implement bridge chart with ApplicationSet template
- [ ] Add feature flag to bootstrap configuration

**Day 3-4: Configuration Files**
- [ ] Create default values in `gitops/addons/default/addons/agent-platform/`
- [ ] Create environment overrides for control-plane
- [ ] Create environment overrides for agent-platform
- [ ] Update Terraform variables for feature flag
- [ ] Update bootstrap script with conditional logic

**Day 5: Testing & Documentation**
- [ ] Test bridge chart rendering with `helm template`
- [ ] Validate ApplicationSet generation
- [ ] Update main README.md with workshop types
- [ ] Create troubleshooting guide

#### In `sample-agent-platform-on-eks` Repository

**Day 1-2: Directory Structure**
- [ ] Create `gitops/` directory
- [ ] Create subdirectories for each component
- [ ] Set up standard Chart.yaml templates
- [ ] Set up standard values.yaml templates

**Day 3-5: Initial Charts**
- [ ] Create Kagent chart (OCI registry reference)
- [ ] Create Tofu Controller chart
- [ ] Test charts locally
- [ ] Document chart structure

### Phase 2: Core Components (Week 2)

#### In `sample-agent-platform-on-eks` Repository

**Day 1-2: LiteLLM Chart**
- [ ] Create Helm chart structure
- [ ] Implement deployment, service, configmap
- [ ] Add HPA and ingress (optional)
- [ ] Test deployment
- [ ] Document configuration options

**Day 2-3: Agent Gateway Chart**
- [ ] Create Helm chart structure
- [ ] Implement deployment, service
- [ ] Add LiteLLM integration
- [ ] Test deployment
- [ ] Document configuration

**Day 3-4: Langfuse Chart**
- [ ] Create Helm chart structure
- [ ] Implement Langfuse deployment
- [ ] Add PostgreSQL StatefulSet
- [ ] Add Redis deployment
- [ ] Test deployment
- [ ] Document configuration

**Day 4-5: Jaeger Chart**
- [ ] Create Helm chart structure
- [ ] Implement all-in-one deployment
- [ ] Add service and ingress
- [ ] Test deployment
- [ ] Document configuration

### Phase 3: Agent Core Integration (Week 3)

#### In `sample-agent-platform-on-eks` Repository

**Day 1-2: Agent Core Chart**
- [ ] Create Helm chart structure
- [ ] Implement Terraform CR template
- [ ] Add agent deployment template
- [ ] Configure Pod Identity
- [ ] Test with Tofu Controller

**Day 3-4: Integration Testing**
- [ ] Deploy full stack to dev cluster
- [ ] Test component interactions
- [ ] Verify Terraform provisioning
- [ ] Test agent workflows end-to-end
- [ ] Fix integration issues

**Day 5: Documentation**
- [ ] Document Agent Core setup
- [ ] Create architecture diagrams
- [ ] Write troubleshooting guide
- [ ] Update README with examples

### Phase 4: Production Readiness (Week 4)

#### In Both Repositories

**Day 1-2: Production Configuration**
- [ ] Create production value overrides
- [ ] Configure autoscaling
- [ ] Set resource limits
- [ ] Configure monitoring
- [ ] Set up alerts

**Day 2-3: Security Hardening**
- [ ] Implement RBAC policies
- [ ] Configure network policies
- [ ] Set up External Secrets
- [ ] Enable Pod Security Standards
- [ ] Security scanning

**Day 3-4: Testing**
- [ ] Deploy to prod spoke cluster
- [ ] Performance testing
- [ ] Load testing
- [ ] Failover testing
- [ ] Backup/restore testing

**Day 5: Documentation & Handoff**
- [ ] Complete all documentation
- [ ] Create runbooks
- [ ] Record demo videos
- [ ] Conduct knowledge transfer
- [ ] Release v1.0.0

### Milestones

| Milestone | Date | Deliverables |
|-----------|------|--------------|
| M1: Foundation | End of Week 1 | Bridge chart, feature flag, basic structure |
| M2: Core Components | End of Week 2 | All component charts created and tested |
| M3: Integration | End of Week 3 | Full stack deployed and working |
| M4: Production | End of Week 4 | Production-ready, documented, released |

---

## Testing Strategy

### Unit Testing

#### Bridge Chart Testing

```bash
# Test Helm template rendering
cd appmod-blueprints/gitops/addons/charts/agent-platform

# Test with agent platform disabled (default)
helm template agent-platform . \
  --set enabled=false

# Should output: No resources (commented out)

# Test with agent platform enabled
helm template agent-platform . \
  --set enabled=true \
  -f ../../../default/addons/agent-platform/values.yaml

# Should output: ApplicationSet with all components
```

#### Component Chart Testing

```bash
# Test individual component charts
cd sample-agent-platform-on-eks/gitops/kagent

helm template kagent . \
  --set global.namespace=agent-platform \
  --set global.resourcePrefix=test

# Validate output
helm template kagent . | kubectl apply --dry-run=client -f -
```

### Integration Testing

#### Test Scenario 1: Platform Engineering Workshop (Default)

```bash
# Deploy with agent platform disabled
export WORKSHOP_TYPE="platform-engineering"
export ENABLE_AGENT_PLATFORM="false"

# Deploy infrastructure
cd appmod-blueprints/platform/infra/terraform
terraform apply \
  -var="workshop_type=$WORKSHOP_TYPE" \
  -var="enable_agent_platform=$ENABLE_AGENT_PLATFORM"

# Verify no agent platform applications
kubectl get applications -n argocd | grep agent-platform
# Expected: No results

# Verify core platform works
kubectl get pods -n argocd
kubectl get pods -n backstage
kubectl get pods -n keycloak
# Expected: All running
```

#### Test Scenario 2: Agent Platform Workshop

```bash
# Deploy with agent platform enabled
export WORKSHOP_TYPE="agent-platform"
export ENABLE_AGENT_PLATFORM="true"

# Deploy infrastructure
terraform apply \
  -var="workshop_type=$WORKSHOP_TYPE" \
  -var="enable_agent_platform=$ENABLE_AGENT_PLATFORM"

# Verify individual applications created
kubectl get applications -n argocd | grep agent-platform
# Expected: Individual applications listed:
# peeks-agent-platform-kagent
# peeks-agent-platform-litellm
# peeks-agent-platform-agent-gateway
# peeks-agent-platform-langfuse
# peeks-agent-platform-jaeger
# peeks-agent-platform-tofu-controller
# peeks-agent-platform-agent-core

# Verify components deployed
kubectl get pods -n agent-platform
# Expected: All agent platform pods running

# Test component health
kubectl get pods -n agent-platform -o wide
kubectl logs -n agent-platform deployment/kagent
kubectl logs -n agent-platform deployment/litellm
```

#### Test Scenario 3: Toggle Feature Flag

```bash
# Start with disabled
terraform apply -var="enable_agent_platform=false"

# Verify no agent components
kubectl get applications -n argocd | grep agent-platform
# Expected: No results

# Enable agent platform
terraform apply -var="enable_agent_platform=true"

# Verify agent components deployed
kubectl get applications -n argocd | grep agent-platform
# Expected: Applications created

# Disable again
terraform apply -var="enable_agent_platform=false"

# Verify clean removal
kubectl get applications -n argocd | grep agent-platform
# Expected: No results (pruned)

kubectl get pods -n agent-platform
# Expected: No resources found (namespace may remain)
```

### End-to-End Testing

#### Test Agent Workflow

```bash
# Deploy agent platform
export ENABLE_AGENT_PLATFORM="true"
terraform apply -var="enable_agent_platform=true"

# Wait for all components ready
kubectl wait --for=condition=available --timeout=300s \
  deployment/kagent -n agent-platform

kubectl wait --for=condition=available --timeout=300s \
  deployment/litellm -n agent-platform

# Test Kagent agent creation
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: test-agent
  namespace: agent-platform
spec:
  systemPrompt: "You are a helpful assistant"
  modelConfig:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
  tools:
    - name: kubernetes
EOF

# Verify agent created
kubectl get agent test-agent -n agent-platform

# Test agent interaction (if UI available)
# Or test via API

# Check observability
kubectl port-forward -n agent-platform svc/jaeger 16686:16686
# Open http://localhost:16686 and verify traces

kubectl port-forward -n agent-platform svc/langfuse 3000:3000
# Open http://localhost:3000 and verify metrics
```

### Performance Testing

```bash
# Load test LiteLLM
kubectl run -it --rm load-test --image=williamyeh/wrk --restart=Never -- \
  wrk -t4 -c100 -d30s http://litellm.agent-platform:4000/health

# Monitor resource usage
kubectl top pods -n agent-platform

# Check HPA scaling
kubectl get hpa -n agent-platform
```

### Regression Testing

```bash
# Ensure Platform Engineering workshop still works
export ENABLE_AGENT_PLATFORM="false"
terraform apply -var="enable_agent_platform=false"

# Run existing workshop tests
cd appmod-blueprints
task test-applicationsets
task backstage-validate

# Verify no agent platform components
kubectl get all -n agent-platform
# Expected: No resources found or namespace doesn't exist
```

### Automated Testing

Create test suite in `appmod-blueprints/tests/agent-platform/`:

```bash
tests/
├── test-bridge-chart.sh          # Test bridge chart rendering
├── test-feature-flag.sh          # Test feature flag toggle
├── test-component-deployment.sh  # Test component deployment
└── test-integration.sh           # Test full integration
```

Run all tests:
```bash
cd appmod-blueprints/tests/agent-platform
./test-all.sh
```

---

## Migration Guide

### For Existing Platform Engineering Deployments

If you have an existing Platform Engineering on EKS deployment and want to add agent platform capabilities:

#### Step 1: Update Repository

```bash
# Pull latest changes
cd appmod-blueprints
git pull origin main

# Verify bridge chart exists
ls -la gitops/addons/charts/agent-platform/
```

#### Step 2: Enable Feature Flag

**Option A: Via Terraform Variables**

```bash
cd platform/infra/terraform

# Update terraform.tfvars
cat >> terraform.tfvars <<EOF
workshop_type = "agent-platform"
enable_agent_platform = true
EOF

# Apply changes
terraform apply
```

**Option B: Via Environment Variables**

```bash
export WORKSHOP_TYPE="agent-platform"
export ENABLE_AGENT_PLATFORM="true"

terraform apply \
  -var="workshop_type=$WORKSHOP_TYPE" \
  -var="enable_agent_platform=$ENABLE_AGENT_PLATFORM"
```

**Option C: Via Bootstrap Configuration**

```bash
# Edit bootstrap configuration
vim gitops/addons/bootstrap/default/addons.yaml

# Change:
agent-platform:
  enabled: true  # Changed from false

# Commit and push
git add gitops/addons/bootstrap/default/addons.yaml
git commit -m "Enable agent platform"
git push

# ArgoCD will sync automatically
```

#### Step 3: Verify Deployment

```bash
# Check individual applications created
kubectl get applications -n argocd | grep agent-platform

# Expected output:
# peeks-agent-platform-kagent
# peeks-agent-platform-litellm
# peeks-agent-platform-agent-gateway
# peeks-agent-platform-langfuse
# peeks-agent-platform-jaeger
# peeks-agent-platform-tofu-controller
# peeks-agent-platform-agent-core

# Monitor deployment
kubectl get pods -n agent-platform -w

# Check sync status
argocd app list | grep agent-platform
```

#### Step 4: Configure Components

```bash
# Create environment-specific overrides
mkdir -p gitops/addons/environments/prod/addons/agent-platform

cat > gitops/addons/environments/prod/addons/agent-platform/values.yaml <<EOF
components:
  kagent:
    config:
      replicas: 3
      resources:
        requests:
          memory: "2Gi"
          cpu: "1000m"
  
  litellm:
    config:
      replicas: 3
      autoscaling:
        enabled: true
        minReplicas: 3
        maxReplicas: 10
EOF

# Commit and push
git add gitops/addons/environments/prod/
git commit -m "Add prod agent platform configuration"
git push
```

#### Step 5: Validate

```bash
# Test agent creation
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: test-agent
  namespace: agent-platform
spec:
  systemPrompt: "You are a helpful assistant"
  modelConfig:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
EOF

# Check agent status
kubectl get agent test-agent -n agent-platform -o yaml

# Access observability tools
kubectl port-forward -n agent-platform svc/jaeger 16686:16686
kubectl port-forward -n agent-platform svc/langfuse 3000:3000
```

### Rollback Procedure

If you need to disable agent platform:

```bash
# Option 1: Via Terraform
terraform apply -var="enable_agent_platform=false"

# Option 2: Via Bootstrap Config
vim gitops/addons/bootstrap/default/addons.yaml
# Change enabled: true to enabled: false

git add gitops/addons/bootstrap/default/addons.yaml
git commit -m "Disable agent platform"
git push

# Verify removal
kubectl get applications -n argocd | grep agent-platform
# Expected: No results

kubectl get pods -n agent-platform
# Expected: No resources found
```

### For New Deployments

#### Quick Start: Platform Engineering Only

```bash
# Clone repository
git clone https://github.com/aws-samples/appmod-blueprints
cd appmod-blueprints

# Deploy with defaults (agent platform disabled)
cd platform/infra/terraform
terraform init
terraform apply

# Workshop ready in ~15 minutes
```

#### Quick Start: Agent Platform Enabled

```bash
# Clone repository
git clone https://github.com/aws-samples/appmod-blueprints
cd appmod-blueprints

# Deploy with agent platform
cd platform/infra/terraform
terraform init
terraform apply \
  -var="workshop_type=agent-platform" \
  -var="enable_agent_platform=true"

# Full platform ready in ~20 minutes
```

---

## Security Considerations

### IAM Roles and Permissions

#### Kagent Service Account

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kagent
  namespace: agent-platform
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/KagentRole
```

**Required IAM Policy**:
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

#### Tofu Controller Service Account

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tofu-controller
  namespace: flux-system
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/TofuControllerRole
```

**Required IAM Policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateAgent",
        "bedrock:UpdateAgent",
        "bedrock:DeleteAgent",
        "bedrock:GetAgent",
        "bedrock:CreateAgentActionGroup",
        "bedrock:UpdateAgentActionGroup",
        "bedrock:DeleteAgentActionGroup"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::*:role/BedrockAgent*"
    }
  ]
}
```

### Network Policies

#### Isolate Agent Platform Namespace

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: agent-platform-isolation
  namespace: agent-platform
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow from ArgoCD
    - from:
        - namespaceSelector:
            matchLabels:
              name: argocd
    # Allow from Backstage
    - from:
        - namespaceSelector:
            matchLabels:
              name: backstage
    # Allow internal communication
    - from:
        - podSelector: {}
  egress:
    # Allow to AWS services
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 443
    # Allow DNS
    - to:
        - namespaceSelector:
            matchLabels:
              name: kube-system
      ports:
        - protocol: UDP
          port: 53
    # Allow internal communication
    - to:
        - podSelector: {}
```

### Secrets Management

#### Use External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: litellm-api-keys
  namespace: agent-platform
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: SecretStore
  target:
    name: litellm-api-keys
    creationPolicy: Owner
  data:
    - secretKey: openai-api-key
      remoteRef:
        key: agent-platform/litellm/openai-api-key
    - secretKey: anthropic-api-key
      remoteRef:
        key: agent-platform/litellm/anthropic-api-key
```

### Pod Security Standards

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: agent-platform
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

### Image Security

- Use only trusted registries (ECR, public.ecr.aws)
- Scan images with Trivy or similar tools
- Pin image versions (no `latest` tags in production)
- Use minimal base images (distroless when possible)

### RBAC Policies

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: agent-platform-developer
  namespace: agent-platform
rules:
  - apiGroups: ["kagent.dev"]
    resources: ["agents", "modelconfigs", "toolservers"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
```

---

## Monitoring and Observability

### Metrics Collection

#### Prometheus ServiceMonitors

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kagent
  namespace: agent-platform
spec:
  selector:
    matchLabels:
      app: kagent
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

#### Key Metrics to Monitor

**Kagent Metrics**:
- `kagent_agent_requests_total` - Total agent requests
- `kagent_agent_request_duration_seconds` - Request latency
- `kagent_agent_errors_total` - Error count
- `kagent_model_tokens_used` - Token usage

**LiteLLM Metrics**:
- `litellm_requests_total` - Total LLM requests
- `litellm_request_duration_seconds` - Request latency
- `litellm_errors_total` - Error count by provider
- `litellm_tokens_used` - Token usage by model

**Langfuse Metrics**:
- `langfuse_traces_total` - Total traces
- `langfuse_spans_total` - Total spans
- `langfuse_observations_total` - Total observations

### Logging

#### Centralized Logging with Fluent Bit

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: agent-platform
data:
  fluent-bit.conf: |
    [INPUT]
        Name              tail
        Path              /var/log/containers/*agent-platform*.log
        Parser            docker
        Tag               agent-platform.*
        Refresh_Interval  5
    
    [FILTER]
        Name                kubernetes
        Match               agent-platform.*
        Kube_URL            https://kubernetes.default.svc:443
        Merge_Log           On
    
    [OUTPUT]
        Name                cloudwatch_logs
        Match               agent-platform.*
        region              us-east-1
        log_group_name      /aws/eks/agent-platform
        auto_create_group   true
```

#### Log Aggregation Queries

**CloudWatch Insights - Error Analysis**:
```sql
fields @timestamp, @message, kubernetes.pod_name, kubernetes.container_name
| filter kubernetes.namespace_name = "agent-platform"
| filter @message like /ERROR|error|Error/
| stats count() by kubernetes.pod_name
| sort count desc
```

**CloudWatch Insights - Agent Request Latency**:
```sql
fields @timestamp, request_duration, agent_name, model
| filter kubernetes.namespace_name = "agent-platform"
| filter kubernetes.container_name = "kagent"
| stats avg(request_duration), max(request_duration), p99(request_duration) by agent_name
```

### Distributed Tracing

#### Jaeger Configuration

```yaml
jaeger:
  allInOne:
    enabled: true
    image: jaegertracing/all-in-one:1.52
    options:
      collector:
        zipkin:
          host-port: 9411
      query:
        base-path: /jaeger
  storage:
    type: memory
    memory:
      max-traces: 100000
```

#### Trace Sampling

```yaml
# Configure in Kagent
kagent:
  tracing:
    enabled: true
    endpoint: http://jaeger-collector:14268/api/traces
    sampler:
      type: probabilistic
      param: 0.1  # Sample 10% of traces
```

### Alerting

#### Prometheus Alert Rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: agent-platform-alerts
  namespace: agent-platform
spec:
  groups:
    - name: agent-platform
      interval: 30s
      rules:
        - alert: HighErrorRate
          expr: |
            rate(kagent_agent_errors_total[5m]) > 0.05
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate in agent platform"
            description: "Error rate is {{ $value }} errors/sec"
        
        - alert: HighLatency
          expr: |
            histogram_quantile(0.99, 
              rate(kagent_agent_request_duration_seconds_bucket[5m])
            ) > 30
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High latency in agent requests"
            description: "P99 latency is {{ $value }} seconds"
        
        - alert: PodCrashLooping
          expr: |
            rate(kube_pod_container_status_restarts_total{
              namespace="agent-platform"
            }[15m]) > 0
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Pod is crash looping"
            description: "Pod {{ $labels.pod }} is restarting"
```

### Dashboards

#### Grafana Dashboard - Agent Platform Overview

```json
{
  "dashboard": {
    "title": "Agent Platform Overview",
    "panels": [
      {
        "title": "Agent Requests per Second",
        "targets": [
          {
            "expr": "rate(kagent_agent_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Request Latency (P50, P95, P99)",
        "targets": [
          {
            "expr": "histogram_quantile(0.50, rate(kagent_agent_request_duration_seconds_bucket[5m]))",
            "legendFormat": "P50"
          },
          {
            "expr": "histogram_quantile(0.95, rate(kagent_agent_request_duration_seconds_bucket[5m]))",
            "legendFormat": "P95"
          },
          {
            "expr": "histogram_quantile(0.99, rate(kagent_agent_request_duration_seconds_bucket[5m]))",
            "legendFormat": "P99"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(kagent_agent_errors_total[5m])"
          }
        ]
      },
      {
        "title": "Token Usage",
        "targets": [
          {
            "expr": "rate(kagent_model_tokens_used[5m])"
          }
        ]
      }
    ]
  }
}
```

---

## Backup and Disaster Recovery

### Backup Strategy

#### What to Backup

1. **Kubernetes Resources**
   - Agent CRDs (Agent, ModelConfig, ToolServer)
   - ConfigMaps and Secrets
   - PersistentVolumeClaims

2. **Application Data**
   - Langfuse PostgreSQL database
   - Agent conversation history
   - Model configurations

3. **Configuration**
   - Helm values files
   - ArgoCD application definitions
   - Terraform state

#### Backup Tools

**Velero for Kubernetes Resources**:

```bash
# Install Velero
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.9.0 \
  --bucket agent-platform-backups \
  --backup-location-config region=us-east-1 \
  --snapshot-location-config region=us-east-1 \
  --secret-file ./credentials-velero

# Create backup schedule
velero schedule create agent-platform-daily \
  --schedule="0 2 * * *" \
  --include-namespaces agent-platform \
  --ttl 720h
```

**PostgreSQL Backup (Langfuse)**:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: langfuse-db-backup
  namespace: agent-platform
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: postgres:15
              command:
                - /bin/sh
                - -c
                - |
                  pg_dump -h langfuse-postgres -U langfuse langfuse | \
                  gzip > /backup/langfuse-$(date +%Y%m%d).sql.gz
                  aws s3 cp /backup/langfuse-$(date +%Y%m%d).sql.gz \
                    s3://agent-platform-backups/postgres/
              env:
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: langfuse-postgres
                      key: password
              volumeMounts:
                - name: backup
                  mountPath: /backup
          volumes:
            - name: backup
              emptyDir: {}
          restartPolicy: OnFailure
```

### Disaster Recovery Procedures

#### Scenario 1: Complete Cluster Loss

```bash
# 1. Provision new EKS cluster
cd appmod-blueprints/platform/infra/terraform
terraform apply -var="enable_agent_platform=true"

# 2. Restore Kubernetes resources
velero restore create --from-backup agent-platform-daily-20240101

# 3. Restore PostgreSQL data
kubectl exec -it langfuse-postgres-0 -n agent-platform -- \
  psql -U langfuse -d langfuse < /backup/langfuse-20240101.sql

# 4. Verify restoration
kubectl get pods -n agent-platform
kubectl get agents -n agent-platform
```

#### Scenario 2: Component Failure

```bash
# Identify failed component
kubectl get applications -n argocd | grep agent-platform

# Force sync
argocd app sync agent-platform-kagent --force

# Or delete and recreate
kubectl delete application agent-platform-kagent -n argocd
# ArgoCD ApplicationSet will recreate it

# Verify recovery
kubectl get pods -n agent-platform -l app=kagent
```

#### Scenario 3: Data Corruption

```bash
# 1. Stop affected components
kubectl scale deployment kagent -n agent-platform --replicas=0

# 2. Restore from backup
velero restore create --from-backup agent-platform-daily-20240101 \
  --include-resources persistentvolumeclaims,persistentvolumes

# 3. Restart components
kubectl scale deployment kagent -n agent-platform --replicas=3

# 4. Verify data integrity
kubectl exec -it langfuse-postgres-0 -n agent-platform -- \
  psql -U langfuse -d langfuse -c "SELECT COUNT(*) FROM traces;"
```

### Recovery Time Objectives (RTO) and Recovery Point Objectives (RPO)

| Component | RTO | RPO | Backup Frequency |
|-----------|-----|-----|------------------|
| Kubernetes Resources | 15 minutes | 24 hours | Daily |
| Langfuse Database | 30 minutes | 24 hours | Daily |
| Agent Configurations | 5 minutes | 1 hour | Continuous (GitOps) |
| Observability Data | N/A | 7 days | Not backed up (ephemeral) |

---

## FAQ

### General Questions

**Q: Can I run Platform Engineering workshop without agent platform?**

A: Yes, agent platform is disabled by default. The Platform Engineering workshop works independently.

**Q: How do I enable agent platform for an existing deployment?**

A: Set `enable_agent_platform=true` in Terraform variables or update the bootstrap configuration. See [Migration Guide](#migration-guide).

**Q: Where are the agent component charts stored?**

A: All agent component charts are in the `sample-agent-platform-on-eks` repository under `gitops/`. The `appmod-blueprints` repository only contains a lightweight bridge chart.

**Q: Can I deploy only specific agent components?**

A: Yes, you can disable individual components in the bridge chart values:
```yaml
components:
  kagent:
    enabled: true
  litellm:
    enabled: false  # Disable LiteLLM
```

### Configuration Questions

**Q: How do I change the AWS region for Bedrock?**

A: Update the global configuration in bridge chart values:
```yaml
global:
  awsRegion: "us-west-2"
```

**Q: How do I use a different LLM model?**

A: Update the Kagent configuration:
```yaml
components:
  kagent:
    config:
      modelConfig:
        model: "anthropic.claude-3-opus-20240229-v1:0"
```

**Q: Can I use external PostgreSQL for Langfuse?**

A: Yes, disable the built-in PostgreSQL and provide external connection:
```yaml
components:
  langfuse:
    config:
      postgres:
        enabled: false
        externalHost: "my-postgres.rds.amazonaws.com"
        externalPort: 5432
```

### Deployment Questions

**Q: How long does agent platform deployment take?**

A: Approximately 5 minutes after core platform is ready. Total time from scratch is ~20 minutes.

**Q: What are the resource requirements?**

A: Minimum requirements per spoke cluster:
- 4 vCPUs
- 16 GB RAM
- 50 GB storage

Recommended for production:
- 8 vCPUs
- 32 GB RAM
- 100 GB storage

**Q: Can I deploy to existing EKS clusters?**

A: Yes, you can deploy the bridge chart to any cluster with ArgoCD installed. Point it to the `sample-agent-platform-on-eks` repository.

**Q: How do I update component versions?**

A: Update the version in the component chart's `Chart.yaml` in the `sample-agent-platform-on-eks` repository. ArgoCD will sync automatically.

### Troubleshooting Questions

**Q: Agent platform applications are not being created**

A: The agent platform uses individual ArgoCD Applications created by the bridge chart. Check:
1. Feature flag is enabled: `kubectl get configmap -n argocd -o yaml | grep agent-platform`
2. Bridge chart is deployed: `helm list -n argocd | grep agent-platform`
3. Individual applications exist: `kubectl get applications -n argocd | grep agent-platform`
4. Application controller logs: `kubectl logs -n argocd deployment/argocd-application-controller`

**Q: Kagent pods are failing with "AccessDenied" errors**

A: Verify IAM role for service account (IRSA):
```bash
# Check service account annotation
kubectl get sa kagent -n agent-platform -o yaml | grep role-arn

# Test AWS credentials
kubectl run -it --rm aws-cli --image=amazon/aws-cli --restart=Never -- \
  sts get-caller-identity
```

**Q: LiteLLM is not connecting to Bedrock**

A: Check:
1. AWS region is correct in configuration
2. IAM permissions include `bedrock:InvokeModel`
3. Bedrock model access is enabled in AWS console
4. Network connectivity to Bedrock endpoint

**Q: How do I access Jaeger UI?**

A: Port forward to Jaeger service:
```bash
kubectl port-forward -n agent-platform svc/jaeger 16686:16686
# Open http://localhost:16686
```

**Q: Agent Core Terraform resources are not provisioning**

A: Check:
1. Tofu Controller is running: `kubectl get pods -n flux-system | grep tofu`
2. Terraform CR status: `kubectl get terraform -n agent-platform -o yaml`
3. Tofu Controller logs: `kubectl logs -n flux-system deployment/tofu-controller`
4. IAM permissions for Tofu Controller service account

### Performance Questions

**Q: How do I scale agent platform components?**

A: Update replica counts in values:
```yaml
components:
  kagent:
    config:
      replicas: 5
  litellm:
    config:
      replicas: 5
```

Or enable autoscaling:
```yaml
components:
  kagent:
    config:
      autoscaling:
        enabled: true
        minReplicas: 3
        maxReplicas: 10
        targetCPUUtilizationPercentage: 70
```

**Q: What are the cost implications?**

A: Main costs:
- EKS cluster: ~$73/month (control plane)
- EC2 nodes: Varies by instance type and count
- Bedrock API calls: Pay per token
- Data transfer: Minimal for internal communication
- Storage: ~$10/month for 100GB

**Q: How do I optimize Bedrock costs?**

A: Strategies:
1. Use appropriate model sizes (Haiku for simple tasks, Sonnet for complex)
2. Implement caching in LiteLLM
3. Set token limits in agent configurations
4. Monitor usage with Langfuse
5. Use batch processing where possible

---

## References and Links

### Official Documentation

- [AWS EKS Documentation](https://docs.aws.amazon.com/eks/)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Helm Documentation](https://helm.sh/docs/)

### Component Documentation

- [Kagent GitHub](https://github.com/kagent-dev/kagent)
- [LiteLLM Documentation](https://docs.litellm.ai/)
- [Langfuse Documentation](https://langfuse.com/docs)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Tofu Controller GitHub](https://github.com/flux-iac/tofu-controller)

### Related Repositories

- [appmod-blueprints](https://github.com/aws-samples/appmod-blueprints) - Platform Engineering on EKS
- [sample-agent-platform-on-eks](https://github.com/aws-samples/sample-agent-platform-on-eks) - Agent Platform Components
- [eks-agent-core-pocs](https://github.com/elamaran11/eks-agent-core-pocs) - Agent Core POCs

### AWS Samples and Workshops

- [EKS Workshop](https://www.eksworkshop.com/)
- [Platform Engineering on AWS](https://catalog.workshops.aws/platform-engineering/)
- [Generative AI on AWS](https://catalog.workshops.aws/generative-ai/)

### Community Resources

- [CNCF Landscape](https://landscape.cncf.io/)
- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [GitOps Working Group](https://opengitops.dev/)

### Best Practices

- [AWS Well-Architected Framework](https://aws.amazon.com/architecture/well-architected/)
- [EKS Best Practices Guide](https://aws.github.io/aws-eks-best-practices/)
- [GitOps Principles](https://opengitops.dev/)
- [Helm Best Practices](https://helm.sh/docs/chart_best_practices/)

---

## Appendix

### Glossary

- **Bridge Chart**: Lightweight Helm chart that references external repositories
- **ApplicationSet**: ArgoCD resource that generates multiple Applications
- **Sync Wave**: Ordering mechanism for ArgoCD resource deployment
- **IRSA**: IAM Roles for Service Accounts
- **Pod Identity**: AWS authentication mechanism for pods
- **GitOps**: Declarative infrastructure management using Git
- **CRD**: Custom Resource Definition
- **Tofu**: OpenTofu, open-source Terraform alternative

### Version Compatibility Matrix

| Component | Version | Kubernetes | EKS | Notes |
|-----------|---------|------------|-----|-------|
| Kagent | 0.7.9 | 1.27+ | 1.27+ | Requires CRD support |
| LiteLLM | latest | 1.24+ | 1.24+ | Stateless |
| Langfuse | latest | 1.24+ | 1.24+ | Requires PVC |
| Jaeger | 1.52 | 1.24+ | 1.24+ | All-in-one mode |
| Tofu Controller | latest | 1.26+ | 1.26+ | Requires Flux |
| ArgoCD | 2.9+ | 1.24+ | 1.24+ | ApplicationSet required |

### Change Log

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2024-02-18 | Initial design document |

---

**Document Status**: Draft  
**Last Updated**: 2024-02-18  
**Authors**: Platform Engineering Team  
**Reviewers**: TBD
