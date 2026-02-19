# Agent Platform on EKS - User Guide

## Overview

The Agent Platform on EKS extends the Platform Engineering on EKS solution with AI agent capabilities, including Kagent (Kubernetes-native AI agent framework), LiteLLM (LLM gateway), observability tools (Langfuse, Jaeger), and infrastructure automation (Tofu Controller).

This guide helps you deploy and use the agent platform components.

## Quick Start

### Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured
- kubectl installed
- Terraform installed (v1.5+)
- Git

### Deploy Agent Platform

#### Option 1: New Deployment

```bash
# Clone repository
git clone https://github.com/aws-samples/appmod-blueprints
cd appmod-blueprints

# Deploy with agent platform enabled
cd platform/infra/terraform
terraform init
terraform apply \
  -var="workshop_type=agent-platform" \
  -var="enable_agent_platform=true"

# Wait for deployment (~20 minutes)
```

#### Option 2: Enable on Existing Platform

```bash
# Update Terraform variables
cd appmod-blueprints/platform/infra/terraform

terraform apply -var="enable_agent_platform=true"

# Or update bootstrap configuration
vim gitops/addons/bootstrap/default/addons.yaml
# Change agent-platform.enabled to true

git add gitops/addons/bootstrap/default/addons.yaml
git commit -m "Enable agent platform"
git push
```

### Verify Deployment

```bash
# Check individual applications
kubectl get applications -n argocd | grep agent-platform

# Expected output:
# peeks-agent-platform-kagent
# peeks-agent-platform-litellm
# peeks-agent-platform-agent-gateway
# peeks-agent-platform-langfuse
# peeks-agent-platform-jaeger
# peeks-agent-platform-tofu-controller
# peeks-agent-platform-agent-core

# Check pods
kubectl get pods -n agent-platform

# All pods should be Running
```

## Architecture

The agent platform uses a GitOps bridge pattern:

1. **appmod-blueprints** repository contains a lightweight bridge chart
2. Bridge chart creates individual ArgoCD Applications for each component
3. Each Application references a Helm chart in **sample-agent-platform-on-eks** repository
4. Components deploy to spoke clusters (dev/prod)

```
Hub Cluster (ArgoCD)
    ↓
Bridge Chart (appmod-blueprints)
    ↓
Individual ArgoCD Applications
    ├─ kagent-application.yaml
    ├─ litellm-application.yaml
    ├─ agent-gateway-application.yaml
    ├─ langfuse-application.yaml
    ├─ jaeger-application.yaml
    ├─ tofu-controller-application.yaml
    └─ agent-core-application.yaml
    ↓
Component Helm Charts (sample-agent-platform-on-eks/gitops/)
    ├─ kagent/
    ├─ litellm/
    ├─ agent-gateway/
    ├─ langfuse/
    ├─ jaeger/
    ├─ tofu-controller/
    └─ agent-core/
    ↓
Spoke Clusters (Dev/Prod)
```

## Components

### Kagent

Kubernetes-native AI agent framework.

**Access**: Via Kubernetes API
```bash
# Create an agent
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: my-agent
  namespace: agent-platform
spec:
  systemPrompt: "You are a helpful assistant"
  modelConfig:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
EOF

# Check agent status
kubectl get agent my-agent -n agent-platform
```

### LiteLLM

Unified LLM gateway supporting multiple providers.

**Access**: Internal service at `http://litellm.agent-platform:4000`

```bash
# Test LiteLLM
kubectl run -it --rm curl --image=curlimages/curl --restart=Never -- \
  curl http://litellm.agent-platform:4000/health
```

### Langfuse

LLM observability and analytics platform.

**Access**: Via port-forward
```bash
kubectl port-forward -n agent-platform svc/langfuse 3000:3000
# Open http://localhost:3000
```

### Jaeger

Distributed tracing for agent workflows.

**Access**: Via port-forward
```bash
kubectl port-forward -n agent-platform svc/jaeger 16686:16686
# Open http://localhost:16686
```

### Tofu Controller

Terraform operator for managing AWS resources.

**Access**: Via Kubernetes API
```bash
# Check Terraform resources
kubectl get terraform -n agent-platform
```

### Agent Core Components

AWS Bedrock Agent Core capabilities (Memory, Browser, Code Interpreter).

**Access**: Provisioned via Tofu Controller
```bash
# Check Terraform CR status
kubectl get terraform agent-core -n agent-platform -o yaml
```

## Configuration

### Global Settings

Edit `appmod-blueprints/gitops/addons/charts/agent-platform/values.yaml`:

```yaml
global:
  namespace: "agent-platform"
  resourcePrefix: "peeks"
  awsRegion: "us-east-1"
  eksClusterName: "dev"
```

### Component-Specific Settings

Edit `appmod-blueprints/gitops/addons/default/addons/agent-platform/values.yaml`:

```yaml
components:
  kagent:
    config:
      replicas: 2
      modelConfig:
        model: "anthropic.claude-3-5-sonnet-20241022-v2:0"
      resources:
        requests:
          memory: "512Mi"
          cpu: "250m"
```

### Environment Overrides

Create environment-specific overrides:

```bash
# Dev environment
mkdir -p gitops/addons/environments/dev/addons/agent-platform
cat > gitops/addons/environments/dev/addons/agent-platform/values.yaml <<EOF
components:
  kagent:
    config:
      replicas: 1
EOF

# Prod environment
mkdir -p gitops/addons/environments/prod/addons/agent-platform
cat > gitops/addons/environments/prod/addons/agent-platform/values.yaml <<EOF
components:
  kagent:
    config:
      replicas: 3
      autoscaling:
        enabled: true
        minReplicas: 3
        maxReplicas: 10
EOF
```

## Common Tasks

### Create an AI Agent

```bash
kubectl apply -f - <<EOF
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: code-assistant
  namespace: agent-platform
spec:
  systemPrompt: "You are a code assistant that helps with Kubernetes manifests"
  modelConfig:
    provider: bedrock
    model: anthropic.claude-3-5-sonnet-20241022-v2:0
  tools:
    - name: kubernetes
      type: builtin
EOF
```

### Scale Components

```bash
# Scale Kagent
kubectl scale deployment kagent -n agent-platform --replicas=5

# Or update values and let ArgoCD sync
vim gitops/addons/default/addons/agent-platform/values.yaml
# Change replicas: 5
git commit -am "Scale Kagent to 5 replicas"
git push
```

### View Logs

```bash
# Kagent logs
kubectl logs -n agent-platform deployment/kagent -f

# LiteLLM logs
kubectl logs -n agent-platform deployment/litellm -f

# All agent platform logs
kubectl logs -n agent-platform --all-containers=true -f
```

### Monitor Resources

```bash
# Resource usage
kubectl top pods -n agent-platform

# Events
kubectl get events -n agent-platform --sort-by='.lastTimestamp'

# Application sync status
argocd app list | grep agent-platform
```

## Troubleshooting

### Agent Platform Not Deploying

**Symptom**: No agent platform applications created

**Solution**:
```bash
# Check feature flag
kubectl get configmap -n argocd -o yaml | grep agent-platform

# Check ApplicationSet
kubectl get applicationset -n argocd agent-platform -o yaml

# Check ApplicationSet controller logs
kubectl logs -n argocd deployment/argocd-applicationset-controller
```

### Kagent Pods Failing

**Symptom**: Kagent pods in CrashLoopBackOff

**Solution**:
```bash
# Check pod logs
kubectl logs -n agent-platform deployment/kagent

# Check service account
kubectl get sa kagent -n agent-platform -o yaml

# Verify IAM role annotation
kubectl get sa kagent -n agent-platform -o yaml | grep role-arn

# Test AWS credentials
kubectl run -it --rm aws-cli --image=amazon/aws-cli --restart=Never \
  --serviceaccount=kagent -n agent-platform -- \
  sts get-caller-identity
```

### LiteLLM Connection Issues

**Symptom**: LiteLLM cannot connect to Bedrock

**Solution**:
```bash
# Check configuration
kubectl get configmap litellm-config -n agent-platform -o yaml

# Check AWS region
kubectl exec -it deployment/litellm -n agent-platform -- env | grep AWS

# Test Bedrock connectivity
kubectl exec -it deployment/litellm -n agent-platform -- \
  curl https://bedrock-runtime.us-east-1.amazonaws.com
```

### Tofu Controller Not Provisioning

**Symptom**: Terraform resources stuck in pending

**Solution**:
```bash
# Check Tofu Controller
kubectl get pods -n flux-system | grep tofu

# Check Terraform CR status
kubectl get terraform -n agent-platform -o yaml

# Check Tofu Controller logs
kubectl logs -n flux-system deployment/tofu-controller -f

# Verify IAM permissions
kubectl get sa tofu-controller -n flux-system -o yaml | grep role-arn
```

## Disable Agent Platform

To disable agent platform and return to core platform only:

```bash
# Option 1: Via Terraform
terraform apply -var="enable_agent_platform=false"

# Option 2: Via Bootstrap Config
vim gitops/addons/bootstrap/default/addons.yaml
# Change agent-platform.enabled to false
git commit -am "Disable agent platform"
git push

# Verify removal
kubectl get applications -n argocd | grep agent-platform
# Should return no results
```

## Next Steps

- Read [DESIGN.md](./DESIGN.md) for architecture details
- Read [COMPONENTS.md](./COMPONENTS.md) for component specifications
- Read [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for detailed troubleshooting
- Explore [sample-agent-platform-on-eks](https://github.com/aws-samples/sample-agent-platform-on-eks) repository

## Support

- GitHub Issues: [appmod-blueprints/issues](https://github.com/aws-samples/appmod-blueprints/issues)
- AWS Support: Contact your AWS account team
- Community: Join the discussion in GitHub Discussions

## License

This project is licensed under the MIT-0 License. See LICENSE file for details.
