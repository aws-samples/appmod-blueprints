# Deployment Guide - Application Modernization Blueprints

## Overview

This guide provides comprehensive deployment instructions for the Application Modernization Blueprints platform. Choose the deployment approach that best fits your organizational needs, from quick evaluation to production-ready platform adoption.

## Deployment Scenarios Comparison

| Scenario                       | Time      | Complexity | Use Case                      | Prerequisites                    |
|--------------------------------|-----------|------------|-------------------------------|----------------------------------|
| **🚀 CloudFormation Workshop** | 45 min    | Low        | Complete platform evaluation  | AWS account, basic AWS knowledge |
| **💻 CloudFormation IDE-Only** | 15 min    | Low        | Development environment only  | AWS account, basic AWS knowledge |
| **🏗️ Platform Adoption**      | 2-4 hours | Medium     | Organizational implementation | Kubernetes knowledge             |
| **⚙️ Custom Implementation**   | 1-2 weeks | High       | Production deployment         | Advanced platform engineering    |

## Prerequisites

### Basic Requirements

All deployment scenarios require:

- AWS account with appropriate permissions
- AWS CLI v2 configured
- Basic understanding of Kubernetes and GitOps concepts

### Tool Verification

Verify all required tools are installed correctly:

```bash
# Core tools
aws --version                    # Should show AWS CLI 2.x
kubectl version --client        # Should show kubectl version
jq --version                     # Should show jq version
yq --version                     # Should show yq version
direnv --version                 # Should show direnv version (if installed)

# Platform tools (if installed)
helm version                     # Should show Helm version
argocd version --client          # Should show ArgoCD CLI version
# Note: eksctl is optional - you can use existing EKS clusters

# Development tools (if installed)
node --version                   # Should show Node.js version
npm --version                    # Should show npm version
yarn --version                   # Should show yarn version
docker --version                 # Should show Docker version
terraform --version             # Should show Terraform version

# Test AWS authentication
aws sts get-caller-identity
```

### Tool Installation

#### Core Tools (Required for all scenarios)

```bash
# AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# kubectl (Kubernetes command-line tool)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# jq (JSON processor)
# macOS
brew install jq
# Ubuntu/Debian
sudo apt-get install jq
# Amazon Linux/RHEL/CentOS
sudo yum install jq

# yq (YAML processor)
# macOS
brew install yq
# Linux
sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
sudo chmod +x /usr/local/bin/yq

# direnv (environment variable management - recommended)
# macOS
brew install direnv
# Ubuntu/Debian
sudo apt-get install direnv
# Add to your shell profile: eval "$(direnv hook bash)" or eval "$(direnv hook zsh)"

# Git
# Usually pre-installed on most systems
```

**Platform-Specific Notes:**
- **macOS**: Most tools can be installed via Homebrew (`brew install <tool>`)
- **Ubuntu/Debian**: Use `apt-get install <tool>` for system packages
- **Amazon Linux/RHEL/CentOS**: Use `yum install <tool>` for system packages
- **Windows**: Consider using WSL2 with Ubuntu for the best experience

#### Platform Tools (Required for platform adoption scenarios)

```bash
# Helm (Kubernetes package manager)
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# ArgoCD CLI (for GitOps management)
# macOS
brew install argocd
# Linux
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64

# Note: eksctl is optional - you can use existing EKS clusters or other cluster creation methods
```

#### Development Tools (Optional)

```bash
# Docker (for local development and testing)
# macOS
brew install --cask docker
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh

# Node.js and npm (for Backstage development)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 20 && nvm use 20

# Yarn (alternative package manager)
npm install -g yarn

# Terraform (for infrastructure as code)
# macOS
brew install terraform
# Linux
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform
```

## Scenario 1: CloudFormation Workshop (Recommended)

**Best for**: First-time evaluation, workshops, comprehensive platform assessment

### What You Get

- Complete platform stack with all services
- VSCode IDE accessible via browser
- ArgoCD, GitLab, Backstage, and monitoring
- Sample applications and GitOps workflows
- Pre-configured development environment

### Step-by-Step Deployment

#### 1. Download CloudFormation Template (2 minutes)

```bash
# Download the complete workshop template
curl -o peeks-workshop-team-stack-self.json \
  https://github.com/aws-samples/appmod-blueprints/releases/latest/download/peeks-workshop-team-stack-self.json

# Or download from AWS Workshop Studio if attending an event
```

#### 2. Deploy via AWS Console (40 minutes)

1. **Open CloudFormation Console**
   - Navigate to AWS CloudFormation in your target region
   - Click "Create Stack" → "With new resources"

2. **Upload Template**
   - Choose "Upload a template file"
   - Select the downloaded JSON file
   - Click "Next"

3. **Configure Parameters**
   - **Stack Name**: `platform-engineering-workshop`
   - **ParticipantAssumedRoleArn**: `arn:aws:iam::YOUR-ACCOUNT-ID:role/YourRoleName`
   - Click "Next"

4. **Configure Stack Options**
   - Add tags if desired
   - Leave other options as default
   - Click "Next"

5. **Review and Deploy**
   - Check "I acknowledge that AWS CloudFormation might create IAM resources"
   - Click "Create Stack"

#### 3. Alternative: Deploy via AWS CLI

```bash
# Set your parameters
export AWS_REGION=us-west-2
export PARTICIPANT_ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/YourRoleName"

# Deploy the stack
aws cloudformation create-stack \
  --stack-name platform-engineering-workshop \
  --template-body file://peeks-workshop-team-stack-self.json \
  --parameters ParameterKey=ParticipantAssumedRoleArn,ParameterValue=$PARTICIPANT_ROLE_ARN \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --region $AWS_REGION
```

#### 4. Access Your Environment (3 minutes)

After deployment completes (~45 minutes):

```bash
# Get IDE access information
IDE_URL=$(aws cloudformation describe-stacks \
  --stack-name platform-engineering-workshop \
  --query "Stacks[0].Outputs[?OutputKey=='IdeUrl'].OutputValue" \
  --output text)

IDE_PASSWORD=$(aws cloudformation describe-stacks \
  --stack-name platform-engineering-workshop \
  --query "Stacks[0].Outputs[?OutputKey=='IdePassword'].OutputValue" \
  --output text)

echo "IDE URL: $IDE_URL"
echo "IDE Password: $IDE_PASSWORD"
```

### Validation Steps

From within the IDE environment:

```bash
# Get platform service URLs and credentials
./scripts/6-tools-urls.sh

# Verify platform services
kubectl get applications -n argocd

# Check platform health
kubectl get pods --all-namespaces | grep -E "(argocd|gitlab|backstage|grafana)"

# Test sample application deployment
kubectl get applications -n argocd -o wide
```

### Expected Outcomes

✅ **Success Criteria**:
- IDE accessible via browser with provided credentials
- ArgoCD dashboard showing deployed applications
- GitLab accessible with pre-configured repositories
- Backstage developer portal with application templates
- Sample applications deployed and healthy
- Monitoring dashboards available in Grafana

### Troubleshooting

#### IDE Environment Issues

```bash
# If platform services are not accessible from within the IDE
cd /workspace/appmod-blueprints
./scripts/0-install.sh

# This reconfigures:
# - Environment variables for platform services
# - kubectl cluster access
# - Tool installations and dependencies
# - Platform service connectivity verification
```

#### Platform Services Not Ready

```bash
# Check ArgoCD application sync status
kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.sync.status}{"\t"}{.status.health.status}{"\n"}{end}'

# Restart ArgoCD if needed
kubectl rollout restart deployment argocd-server -n argocd

# Check GitLab pod status
kubectl get pods -n gitlab -l app=gitlab
```

## Scenario 2: CloudFormation IDE-Only

**Best for**: Development environment testing, tool evaluation, minimal resource usage

### What You Get

- Browser-accessible VSCode IDE
- Pre-configured development tools
- Git and AWS CLI setup
- No EKS clusters or platform services (you can connect to existing ones)

### Deployment Steps

#### 1. Deploy IDE-Only Template

```bash
# Download IDE-only template
curl -o ide-stack.yaml \
  https://raw.githubusercontent.com/aws-samples/java-on-aws/main/infrastructure/cfn/ide-stack.yaml

# Create unique S3 bucket for deployment
CFN_S3=cfn-$(uuidgen | tr -d - | tr '[:upper:]' '[:lower:]')
aws s3 mb s3://$CFN_S3

# Deploy IDE-only stack
aws cloudformation deploy \
  --stack-name ide-stack \
  --template-file ./ide-stack.yaml \
  --s3-bucket $CFN_S3 \
  --capabilities CAPABILITY_NAMED_IAM
```

#### 2. Configure Development Environment

```bash
# Get IDE access details
IDE_URL=$(aws cloudformation describe-stacks --stack-name ide-stack --query "Stacks[0].Outputs[?OutputKey=='IdeUrl'].OutputValue" --output text)
IDE_PASSWORD=$(aws cloudformation describe-stacks --stack-name ide-stack --query "Stacks[0].Outputs[?OutputKey=='IdePassword'].OutputValue" --output text)

echo "Access your IDE at: $IDE_URL"
echo "Password: $IDE_PASSWORD"
```

#### 3. Setup Platform Repository (from within IDE)

```bash
# Configure workspace environment
cat << EOF > ~/environment/.envrc
export AWS_REGION=us-west-2
export WORKSPACE_PATH="\$HOME/environment"
export AWS_ACCOUNT_ID=\$(aws sts get-caller-identity --output text --query Account)
export WORKSHOP_GIT_URL="https://github.com/aws-samples/appmod-blueprints.git"
export WORKSHOP_GIT_BRANCH="main"
EOF

# If direnv is installed (recommended)
cd ~/environment && direnv allow

# Or manually source the file
source ~/environment/.envrc

# Verify environment variables
echo "AWS_REGION: $AWS_REGION"
echo "WORKSPACE_PATH: $WORKSPACE_PATH"

# Clone the blueprints repository
git clone $WORKSHOP_GIT_URL $WORKSPACE_PATH/appmod-blueprints
cd $WORKSPACE_PATH/appmod-blueprints
git checkout $WORKSHOP_GIT_BRANCH
```

### Expected Outcomes

✅ **Success Criteria**:
- IDE accessible via browser
- Development tools functional (Git, AWS CLI, kubectl)
- Platform repository cloned and accessible
- Ready to connect to existing EKS clusters

## Scenario 3: Platform Adoption

**Best for**: Organizations implementing platform engineering practices

### Prerequisites

- Existing EKS cluster or ability to create one
- Understanding of GitOps workflows
- Kubernetes cluster admin access
- Helm 3.x installed

### Step 1: Prepare EKS Cluster

#### Option A: Create New EKS Cluster

```bash
# Set cluster configuration
export CLUSTER_NAME=platform-adoption-cluster
export AWS_REGION=us-west-2

# Create EKS cluster (using AWS CLI or Console)
# Option 1: Use AWS Console to create EKS cluster with Auto Mode
# Option 2: Use AWS CLI
aws eks create-cluster \
  --name $CLUSTER_NAME \
  --version 1.31 \
  --role-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/eks-service-role \
  --resources-vpc-config subnetIds=subnet-xxx,subnet-yyy \
  --compute-config nodePoolsToCreate=system
```

#### Option B: Use Existing EKS Cluster

```bash
# Update kubeconfig for existing cluster
aws eks update-kubeconfig --region $AWS_REGION --name $CLUSTER_NAME

# Verify cluster access
kubectl get nodes
```

### Step 2: Install Core Platform Components

#### 1. Install ArgoCD

```bash
# Create ArgoCD namespace
kubectl create namespace argocd

# Install ArgoCD
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get ArgoCD admin password
ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
echo "ArgoCD admin password: $ARGOCD_PASSWORD"
```

#### 2. Configure ArgoCD Access

```bash
# Port forward to access ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443 &

# Or configure ingress for production access
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
spec:
  rules:
  - host: argocd.your-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port:
              number: 443
EOF
```

### Step 3: Deploy Platform Applications

#### 1. Clone Platform Repository

```bash
# Clone the blueprints repository
git clone https://github.com/aws-samples/appmod-blueprints.git
cd appmod-blueprints
```

#### 2. Configure Platform Applications

```bash
# Create platform project in ArgoCD
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: platform
  namespace: argocd
spec:
  description: Platform Engineering Applications
  sourceRepos:
  - 'https://github.com/aws-samples/appmod-blueprints.git'
  destinations:
  - namespace: '*'
    server: https://kubernetes.default.svc
  clusterResourceWhitelist:
  - group: '*'
    kind: '*'
EOF
```

#### 3. Deploy Core Platform Services

```bash
# Deploy Backstage
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: backstage
  namespace: argocd
spec:
  project: platform
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints.git
    targetRevision: HEAD
    path: packages/backstage/base
  destination:
    server: https://kubernetes.default.svc
    namespace: backstage
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF

# Deploy monitoring stack
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring
  namespace: argocd
spec:
  project: platform
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints.git
    targetRevision: HEAD
    path: packages/grafana/base
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF
```

### Step 4: Configure Application Templates

```bash
# Deploy application templates to Backstage
kubectl apply -f gitops/platform/bootstrap/

# Verify applications are syncing
kubectl get applications -n argocd
```

### Validation Steps

```bash
# Check all platform applications
kubectl get applications -n argocd -o wide

# Verify platform services are running
kubectl get pods --all-namespaces | grep -E "(backstage|grafana|argocd)"

# Test Backstage access
kubectl port-forward svc/backstage -n backstage 7007:7007 &

# Check ArgoCD application health
kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.health.status}{"\n"}{end}'
```

### Expected Outcomes

✅ **Success Criteria**:
- ArgoCD managing all platform applications
- Backstage developer portal accessible
- Monitoring stack operational
- Application templates available in Backstage
- GitOps workflows functional

## Scenario 4: Custom Implementation

**Best for**: Production deployment with specific organizational requirements

### Prerequisites

- Advanced Kubernetes and platform engineering knowledge
- Understanding of Crossplane, ArgoCD, and Backstage
- Production security and compliance requirements defined
- CI/CD pipeline integration planned

### Step 1: Architecture Planning

#### 1. Define Platform Requirements

```bash
# Create platform specification
cat > platform-spec.yaml <<EOF
platform:
  name: "production-platform"
  version: "1.0.0"
  
clusters:
  hub:
    name: "prod-platform-hub"
    region: "us-west-2"
    version: "1.31"
    computeConfig: "auto-mode"
        
  spokes:
    - name: "prod-workloads"
      region: "us-west-2"
      version: "1.31"
      computeConfig: "auto-mode"

services:
  argocd:
    enabled: true
    ha: true
    sso: true
    
  backstage:
    enabled: true
    database: "postgresql"
    auth: "oauth2"
    
  crossplane:
    enabled: true
    providers: ["aws", "kubernetes"]
    
  monitoring:
    enabled: true
    stack: "prometheus-grafana"
    retention: "30d"
EOF
```

#### 2. Security and Compliance Configuration

```bash
# Define security policies
cat > security-policies.yaml <<EOF
security:
  networkPolicies:
    enabled: true
    defaultDeny: true
    
  podSecurityStandards:
    enforce: "restricted"
    audit: "restricted"
    warn: "restricted"
    
  rbac:
    enabled: true
    minimumPrivileges: true
    
  encryption:
    atRest: true
    inTransit: true
    
  imageScanning:
    enabled: true
    policy: "high-severity-block"
    
  compliance:
    frameworks: ["SOC2", "PCI-DSS"]
    auditLogging: true
EOF
```

### Step 2: Infrastructure Deployment

#### 1. Deploy Hub Cluster with Advanced Configuration

```bash
# Create production-ready EKS cluster with Auto Mode
aws eks create-cluster \
  --name prod-platform-hub \
  --version 1.31 \
  --role-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/eks-service-role \
  --resources-vpc-config subnetIds=subnet-xxx,subnet-yyy \
  --compute-config nodePoolsToCreate=system \
  --access-config authenticationMode=API_AND_CONFIG_MAP \
  --logging '{"enable":["api","audit","authenticator","controllerManager","scheduler"]}'

# Wait for cluster to be active
aws eks wait cluster-active --name prod-platform-hub

# Update kubeconfig
aws eks update-kubeconfig --region us-west-2 --name prod-platform-hub
```

#### 2. Install Platform Services with Production Configuration

```bash
# Install ArgoCD with HA configuration
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --values - <<EOF
server:
  replicas: 3
  service:
    type: LoadBalancer
  config:
    url: https://argocd.your-domain.com
    oidc.config: |
      name: OIDC
      issuer: https://your-oidc-provider.com
      clientId: argocd
      clientSecret: \$oidc.clientSecret
      requestedScopes: ["openid", "profile", "email", "groups"]

controller:
  replicas: 3

repoServer:
  replicas: 3

redis-ha:
  enabled: true

postgresql-ha:
  enabled: true
EOF

# Install Crossplane
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace

# Install AWS Provider for Crossplane
kubectl apply -f - <<EOF
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-aws
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-aws:v0.44.0
EOF
```

### Step 3: Application Platform Configuration

#### 1. Deploy Backstage with Production Settings

```bash
# Create Backstage configuration
kubectl create secret generic backstage-secrets \
  --namespace backstage \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -base64 32)" \
  --from-literal=GITHUB_TOKEN="your-github-token" \
  --from-literal=AUTH_OAUTH2_CLIENT_SECRET="your-oauth2-secret"

# Deploy Backstage
helm repo add backstage https://backstage.github.io/charts
helm install backstage backstage/backstage \
  --namespace backstage \
  --create-namespace \
  --values - <<EOF
backstage:
  image:
    repository: your-registry/backstage
    tag: latest
  
  config:
    app:
      title: "Production Platform"
      baseUrl: https://backstage.your-domain.com
    
    backend:
      baseUrl: https://backstage.your-domain.com
      database:
        client: pg
        connection:
          host: postgresql
          port: 5432
          user: backstage
          password: \${POSTGRES_PASSWORD}
    
    auth:
      providers:
        oauth2:
          production:
            clientId: \${AUTH_OAUTH2_CLIENT_ID}
            clientSecret: \${AUTH_OAUTH2_CLIENT_SECRET}
            authorizationUrl: https://your-oauth-provider.com/oauth/authorize
            tokenUrl: https://your-oauth-provider.com/oauth/token

postgresql:
  enabled: true
  auth:
    existingSecret: backstage-secrets
    secretKeys:
      adminPasswordKey: POSTGRES_PASSWORD

ingress:
  enabled: true
  className: alb
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
  hosts:
  - host: backstage.your-domain.com
    paths:
    - path: /
      pathType: Prefix
EOF
```

#### 2. Configure Monitoring and Observability

```bash
# Install Prometheus and Grafana
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values - <<EOF
prometheus:
  prometheusSpec:
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: gp3
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 100Gi

grafana:
  adminPassword: "$(openssl rand -base64 32)"
  persistence:
    enabled: true
    storageClassName: gp3
    size: 10Gi
  
  ingress:
    enabled: true
    ingressClassName: alb
    annotations:
      alb.ingress.kubernetes.io/scheme: internet-facing
    hosts:
    - grafana.your-domain.com

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: gp3
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
EOF
```

### Step 4: Security Hardening

#### 1. Implement Network Policies via GitOps

Security configurations should be managed through GitOps workflows for consistency and auditability:

```bash
# Create security configuration repository structure
mkdir -p platform-security/{network-policies,pod-security-standards,rbac}

# 1. Network Policies Configuration
cat > platform-security/network-policies/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- default-deny.yaml
- argocd-policies.yaml
- backstage-policies.yaml
- monitoring-policies.yaml
EOF

cat > platform-security/network-policies/default-deny.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: default
spec:
  podSelector: {}
  policyTypes:
  - Ingress
EOF

cat > platform-security/network-policies/argocd-policies.yaml <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-server-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-system
    ports:
    - protocol: TCP
      port: 8080
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 80
EOF

# 2. Deploy network policies via ArgoCD
cat > platform-security/network-policies-app.yaml <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: network-policies
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/platform-security.git
    targetRevision: HEAD
    path: network-policies
  destination:
    server: https://kubernetes.default.svc
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

#### 2. Configure Pod Security Standards via GitOps

```bash
# Pod Security Standards Configuration
cat > platform-security/pod-security-standards/namespace-security.yaml <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: argocd
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: backstage
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: crossplane-system
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
EOF

# Deploy pod security standards via ArgoCD
cat > platform-security/pod-security-app.yaml <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: pod-security-standards
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"  # Deploy first
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/platform-security.git
    targetRevision: HEAD
    path: pod-security-standards
  destination:
    server: https://kubernetes.default.svc
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

#### 3. AWS Load Balancer Controller via GitOps-Bridge

When using Terraform for infrastructure and ArgoCD for applications, use GitOps-Bridge pattern for resources that depend on both:

```bash
# GitOps-Bridge configuration for AWS Load Balancer Controller
cat > platform-security/aws-load-balancer-controller.yaml <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: aws-load-balancer-controller
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "2"
spec:
  project: default
  source:
    repoURL: https://aws.github.io/eks-charts
    chart: aws-load-balancer-controller
    targetRevision: 1.7.2
    helm:
      parameters:
      - name: clusterName
        value: "prod-platform-hub"
      - name: serviceAccount.create
        value: "false"
      - name: serviceAccount.name
        value: "aws-load-balancer-controller"
      - name: region
        value: "us-west-2"
  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF

# Note: The service account and IAM role should be created by Terraform:
# resource "kubernetes_service_account" "aws_load_balancer_controller" {
#   metadata {
#     name      = "aws-load-balancer-controller"
#     namespace = "kube-system"
#     annotations = {
#       "eks.amazonaws.com/role-arn" = aws_iam_role.aws_load_balancer_controller.arn
#     }
#   }
# }
```

### Step 5: GitOps Configuration

#### 1. Configure Application of Applications Pattern

```bash
# Create root application
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/platform-config.git
    targetRevision: HEAD
    path: applications
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

#### 2. Set Up Multi-Environment Promotion

```bash
# Create environment-specific applications
for env in dev staging prod; do
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-$env
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/platform-config.git
    targetRevision: HEAD
    path: environments/$env
  destination:
    server: https://kubernetes.default.svc
    namespace: $env
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF
done
```

### Validation Steps

```bash
# Comprehensive platform health check
kubectl get applications -n argocd -o wide

# Check all platform services
kubectl get pods --all-namespaces | grep -E "(argocd|backstage|crossplane|prometheus|grafana)"

# Verify security policies
kubectl get networkpolicies --all-namespaces
kubectl get psp,pss --all-namespaces

# Test application deployment workflow
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: test-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/test-application.git
    targetRevision: HEAD
    path: manifests
  destination:
    server: https://kubernetes.default.svc
    namespace: test
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF
```

### Expected Outcomes

✅ **Success Criteria**:
- Production-ready EKS cluster with HA configuration
- ArgoCD managing all platform and application deployments
- Backstage providing self-service developer capabilities
- Comprehensive monitoring and alerting operational
- Security policies enforced across all namespaces
- Multi-environment GitOps workflows functional
- Application templates available for development teams

## Advanced Configuration

### Custom Domain Setup

For production deployments, you'll want to use custom domains for your platform services. This section covers setting up external-dns with Route53 for automatic DNS management and SSL certificate handling.

#### Prerequisites

- A registered domain name (e.g., `platform.example.com`)
- Route53 hosted zone for your domain
- AWS Load Balancer Controller installed in your cluster
- EKS cluster with OIDC provider enabled

#### Step 1: Create Route53 Hosted Zone

```bash
# Set your domain configuration
export DOMAIN_NAME="platform.example.com"
export HOSTED_ZONE_NAME="example.com"
export CLUSTER_NAME="prod-platform-hub"

# Create hosted zone (if not already exists)
aws route53 create-hosted-zone \
  --name $HOSTED_ZONE_NAME \
  --caller-reference $(date +%s) \
  --hosted-zone-config Comment="Platform Engineering hosted zone"

# Get the hosted zone ID
export HOSTED_ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name $HOSTED_ZONE_NAME \
  --query 'HostedZones[0].Id' \
  --output text | cut -d'/' -f3)

echo "Hosted Zone ID: $HOSTED_ZONE_ID"
echo "Update your domain registrar's nameservers to:"
aws route53 get-hosted-zone --id $HOSTED_ZONE_ID --query 'DelegationSet.NameServers'
```

#### Step 2: Install AWS Load Balancer Controller

```bash
# Download IAM policy for AWS Load Balancer Controller
curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.2/docs/install/iam_policy.json

# Create IAM policy
aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam_policy.json

# Create IAM role and service account
cat > load-balancer-controller-service-account.yaml <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  labels:
    app.kubernetes.io/component: controller
    app.kubernetes.io/name: aws-load-balancer-controller
  name: aws-load-balancer-controller
  namespace: kube-system
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/AmazonEKSLoadBalancerControllerRole
EOF

kubectl apply -f load-balancer-controller-service-account.yaml

# Install AWS Load Balancer Controller via Helm
helm repo add eks https://aws.github.io/eks-charts
helm repo update

helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=$CLUSTER_NAME \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set region=us-west-2 \
  --set vpcId=$(aws eks describe-cluster --name $CLUSTER_NAME --query 'cluster.resourcesVpcConfig.vpcId' --output text)
```

#### Step 3: Install and Configure external-dns

```bash
# Create IAM policy for external-dns
cat > external-dns-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ChangeResourceRecordSets"
      ],
      "Resource": [
        "arn:aws:route53:::hostedzone/$HOSTED_ZONE_ID"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:ListResourceRecordSets"
      ],
      "Resource": [
        "*"
      ]
    }
  ]
}
EOF

aws iam create-policy \
  --policy-name ExternalDNSPolicy \
  --policy-document file://external-dns-policy.json

# Create service account for external-dns
cat > external-dns-service-account.yaml <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: external-dns
  namespace: kube-system
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/ExternalDNSRole
EOF

kubectl apply -f external-dns-service-account.yaml

# Install external-dns
helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/
helm install external-dns external-dns/external-dns \
  --namespace kube-system \
  --set serviceAccount.create=false \
  --set serviceAccount.name=external-dns \
  --set provider=aws \
  --set aws.zoneType=public \
  --set txtOwnerId=$HOSTED_ZONE_ID \
  --set domainFilters[0]=$HOSTED_ZONE_NAME \
  --set policy=sync \
  --set registry=txt
```

#### Step 4: Request SSL Certificates

```bash
# Request wildcard SSL certificate via AWS Certificate Manager
aws acm request-certificate \
  --domain-name "*.$HOSTED_ZONE_NAME" \
  --subject-alternative-names "$HOSTED_ZONE_NAME" \
  --validation-method DNS \
  --region us-west-2

# Get certificate ARN
CERT_ARN=$(aws acm list-certificates \
  --query "CertificateSummaryList[?DomainName=='*.$HOSTED_ZONE_NAME'].CertificateArn" \
  --output text)

echo "Certificate ARN: $CERT_ARN"

# Get validation records and add them to Route53
aws acm describe-certificate --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord' \
  --output table

# Note: Add the CNAME records shown above to your Route53 hosted zone
# Or use the following command to add them automatically:
aws acm describe-certificate --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord' \
  --output json | jq -r '"aws route53 change-resource-record-sets --hosted-zone-id '$HOSTED_ZONE_ID' --change-batch {\"Changes\":[{\"Action\":\"CREATE\",\"ResourceRecordSet\":{\"Name\":\"\(.Name)\",\"Type\":\"\(.Type)\",\"TTL\":300,\"ResourceRecords\":[{\"Value\":\"\\\"\(.Value)\\\"\"}]}}]}"' | bash
```

#### Step 5: Configure Platform Services with Custom Domains

```bash
# Update ArgoCD configuration for custom domain
kubectl patch configmap argocd-server-config -n argocd --patch "{\"data\":{\"url\":\"https://argocd.$DOMAIN_NAME\"}}"

# Create ingress for ArgoCD
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/ssl-redirect: '443'
    alb.ingress.kubernetes.io/certificate-arn: $CERT_ARN
    alb.ingress.kubernetes.io/backend-protocol: HTTPS
    alb.ingress.kubernetes.io/healthcheck-protocol: HTTPS
    external-dns.alpha.kubernetes.io/hostname: argocd.$DOMAIN_NAME
spec:
  rules:
  - host: argocd.$DOMAIN_NAME
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port:
              number: 443
EOF

# Create ingress for Backstage
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: backstage-ingress
  namespace: backstage
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/ssl-redirect: '443'
    alb.ingress.kubernetes.io/certificate-arn: $CERT_ARN
    external-dns.alpha.kubernetes.io/hostname: backstage.$DOMAIN_NAME
spec:
  rules:
  - host: backstage.$DOMAIN_NAME
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: backstage
            port:
              number: 7007
EOF

# Create ingress for Grafana (monitoring)
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana-ingress
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: alb
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/ssl-redirect: '443'
    alb.ingress.kubernetes.io/certificate-arn: $CERT_ARN
    external-dns.alpha.kubernetes.io/hostname: grafana.$DOMAIN_NAME
spec:
  rules:
  - host: grafana.$DOMAIN_NAME
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: monitoring-grafana
            port:
              number: 80
EOF
```

#### Step 6: Update Platform Service Configurations

```bash
# Update Backstage configuration to use custom domain
kubectl patch configmap backstage-config -n backstage --patch "{\"data\":{\"app-config.yaml\":\"$(kubectl get configmap backstage-config -n backstage -o jsonpath='{.data.app-config\.yaml}' | sed "s|baseUrl:.*|baseUrl: https://backstage.$DOMAIN_NAME|g")\"}}"

# Update ArgoCD to trust the new domain
kubectl patch configmap argocd-cmd-params-cm -n argocd --patch '{"data":{"server.insecure":"false"}}'

# Restart services to pick up new configuration
kubectl rollout restart deployment argocd-server -n argocd
kubectl rollout restart deployment backstage -n backstage
```

#### Step 7: Validation and Testing

```bash
# Check external-dns is working
kubectl logs -n kube-system -l app.kubernetes.io/name=external-dns --tail=50

# Verify DNS records are created in Route53
aws route53 list-resource-record-sets --hosted-zone-id $HOSTED_ZONE_ID \
  --query "ResourceRecordSets[?Type=='A' || Type=='CNAME']" \
  --output table

# Test DNS resolution
nslookup argocd.$DOMAIN_NAME
nslookup backstage.$DOMAIN_NAME
nslookup grafana.$DOMAIN_NAME

# Test HTTPS access
curl -I https://argocd.$DOMAIN_NAME
curl -I https://backstage.$DOMAIN_NAME
curl -I https://grafana.$DOMAIN_NAME

# Check ingress status and load balancer creation
kubectl get ingress --all-namespaces
kubectl describe ingress argocd-server-ingress -n argocd
```

#### Expected Outcomes

✅ **Success Criteria**:
- Route53 hosted zone configured with proper nameservers
- SSL certificate issued and validated via ACM
- external-dns automatically creating/managing DNS records
- AWS Load Balancer Controller creating ALBs for each ingress
- Platform services accessible via custom domains:
  - ArgoCD: `https://argocd.platform.example.com`
  - Backstage: `https://backstage.platform.example.com`
  - Grafana: `https://grafana.platform.example.com`
- Automatic SSL termination at the load balancer
- DNS records automatically updated when services are added/removed

#### Troubleshooting Custom Domains

```bash
# Check external-dns permissions and logs
kubectl describe serviceaccount external-dns -n kube-system
kubectl logs -n kube-system -l app.kubernetes.io/name=external-dns --tail=100

# Verify AWS Load Balancer Controller
kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller --tail=50

# Check certificate validation status
aws acm describe-certificate --certificate-arn $CERT_ARN \
  --query 'Certificate.DomainValidationOptions[].ValidationStatus'

# Verify Route53 records
aws route53 list-resource-record-sets --hosted-zone-id $HOSTED_ZONE_ID

# Check ingress events for issues
kubectl describe ingress --all-namespaces

# Test load balancer health
ALB_DNS=$(kubectl get ingress argocd-server-ingress -n argocd -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl -I http://$ALB_DNS
```

## Operational Procedures

### Backup and Recovery

```bash
# Backup ArgoCD configuration
kubectl get applications -n argocd -o yaml > argocd-applications-backup.yaml
kubectl get appprojects -n argocd -o yaml > argocd-projects-backup.yaml

# Backup Backstage configuration
kubectl get configmaps -n backstage -o yaml > backstage-config-backup.yaml
kubectl get secrets -n backstage -o yaml > backstage-secrets-backup.yaml

# Create EBS snapshots for persistent volumes
aws ec2 describe-volumes --filters "Name=tag:kubernetes.io/cluster/prod-platform-hub,Values=owned" \
  --query 'Volumes[].VolumeId' --output text | \
  xargs -I {} aws ec2 create-snapshot --volume-id {} --description "Platform backup $(date +%Y-%m-%d)"
```

### Monitoring and Alerting

```bash
# Configure critical alerts
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: platform-alerts
  namespace: monitoring
spec:
  groups:
  - name: platform.rules
    rules:
    - alert: ArgocdDown
      expr: up{job="argocd-server-metrics"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "ArgoCD server is down"
        
    - alert: BackstageDown
      expr: up{job="backstage"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Backstage is down"
        
    - alert: HighPodRestarts
      expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High pod restart rate detected"
EOF
```

### Maintenance Procedures

```bash
# Update platform components
helm upgrade argocd argo/argo-cd --namespace argocd --reuse-values
helm upgrade backstage backstage/backstage --namespace backstage --reuse-values
helm upgrade monitoring prometheus-community/kube-prometheus-stack --namespace monitoring --reuse-values

# Update EKS cluster
aws eks update-cluster-version --name prod-platform-hub --version 1.32

# Note: EKS Auto Mode handles node updates automatically
```

## Cleanup and Maintenance

### Complete Cleanup

#### CloudFormation Deployments

```bash
# For CloudFormation workshop deployments
aws cloudformation delete-stack --stack-name platform-engineering-workshop

# For IDE-only deployments
aws cloudformation delete-stack --stack-name ide-stack

# Clean up S3 bucket used for deployment (if created)
aws s3 rb s3://$CFN_S3 --force

# Comprehensive cleanup of any remaining platform resources
# This handles resources that may not be cleaned up by CloudFormation deletion
task taskcat-clean-deployment-force --region us-west-2 --prefix peeks
```

#### Platform Adoption Deployments

```bash
# Remove ArgoCD applications (in reverse order of dependencies)
kubectl delete application test-app -n argocd
kubectl delete application monitoring -n argocd  
kubectl delete application backstage -n argocd
kubectl delete application platform-security -n argocd

# Remove ArgoCD itself
helm uninstall argocd -n argocd
kubectl delete namespace argocd

# Remove other platform components
helm uninstall monitoring -n monitoring
kubectl delete namespace monitoring

# Clean up persistent volumes
kubectl get pv | grep -E "(argocd|backstage|monitoring)" | awk '{print $1}' | xargs kubectl delete pv

# Remove custom resources
kubectl delete crd -l app.kubernetes.io/part-of=argocd
```

#### Custom Implementation Cleanup

```bash
# Remove all ArgoCD applications
kubectl get applications -n argocd -o name | xargs kubectl delete

# Remove platform applications in dependency order
helm uninstall backstage -n backstage
helm uninstall monitoring -n monitoring  
helm uninstall crossplane -n crossplane-system
helm uninstall aws-load-balancer-controller -n kube-system
helm uninstall external-dns -n kube-system
helm uninstall argocd -n argocd

# Clean up namespaces
kubectl delete namespace backstage monitoring crossplane-system argocd

# Remove EKS cluster (if created for this platform)
aws eks delete-cluster --name prod-platform-hub

# Clean up any remaining AWS resources
# Use the comprehensive cleanup tool from platform-engineering-on-eks
curl -o cleanup.sh https://raw.githubusercontent.com/aws-samples/platform-engineering-on-eks/main/taskcat/scripts/enhanced-cleanup/enhanced-cleanup.sh
chmod +x cleanup.sh
./cleanup.sh --force --yes --region us-west-2 --prefix platform
```

### Maintenance Procedures

#### Regular Maintenance Tasks

```bash
# Update platform components
helm repo update

# Update ArgoCD
helm upgrade argocd argo/argo-cd --namespace argocd --reuse-values

# Update monitoring stack
helm upgrade monitoring prometheus-community/kube-prometheus-stack --namespace monitoring --reuse-values

# Update Backstage
helm upgrade backstage backstage/backstage --namespace backstage --reuse-values

# Update AWS Load Balancer Controller
helm upgrade aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system --reuse-values
```

#### Backup Procedures

```bash
# Backup ArgoCD configuration
kubectl get applications -n argocd -o yaml > argocd-applications-backup-$(date +%Y%m%d).yaml
kubectl get appprojects -n argocd -o yaml > argocd-projects-backup-$(date +%Y%m%d).yaml

# Backup Backstage configuration
kubectl get configmaps -n backstage -o yaml > backstage-config-backup-$(date +%Y%m%d).yaml
kubectl get secrets -n backstage -o yaml > backstage-secrets-backup-$(date +%Y%m%d).yaml

# Backup monitoring configuration
kubectl get prometheusrules -n monitoring -o yaml > monitoring-rules-backup-$(date +%Y%m%d).yaml
kubectl get servicemonitors --all-namespaces -o yaml > service-monitors-backup-$(date +%Y%m%d).yaml

# Create EBS snapshots for persistent volumes
aws ec2 describe-volumes --filters "Name=tag:kubernetes.io/cluster/prod-platform-hub,Values=owned" \
  --query 'Volumes[].VolumeId' --output text | \
  xargs -I {} aws ec2 create-snapshot --volume-id {} --description "Platform backup $(date +%Y-%m-%d)"
```

#### Disaster Recovery

```bash
# Restore ArgoCD applications from backup
kubectl apply -f argocd-applications-backup-YYYYMMDD.yaml
kubectl apply -f argocd-projects-backup-YYYYMMDD.yaml

# Restore Backstage configuration
kubectl apply -f backstage-config-backup-YYYYMMDD.yaml
kubectl apply -f backstage-secrets-backup-YYYYMMDD.yaml

# Restore monitoring configuration
kubectl apply -f monitoring-rules-backup-YYYYMMDD.yaml
kubectl apply -f service-monitors-backup-YYYYMMDD.yaml

# Verify all applications are syncing
kubectl get applications -n argocd -o wide
```

## Cost Optimization

### Resource Right-Sizing

```bash
# Analyze resource usage
kubectl top nodes
kubectl top pods --all-namespaces

# Implement resource quotas
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: platform-quota
  namespace: default
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    persistentvolumeclaims: "10"
EOF
```

### Automated Scaling

```bash
# Install cluster autoscaler
helm repo add autoscaler https://kubernetes.github.io/autoscaler
helm install cluster-autoscaler autoscaler/cluster-autoscaler \
  --namespace kube-system \
  --set autoDiscovery.clusterName=prod-platform-hub \
  --set awsRegion=us-west-2

# Configure horizontal pod autoscaling
kubectl apply -f - <<EOF
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backstage-hpa
  namespace: backstage
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backstage
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
EOF
```

## Troubleshooting

### Common Issues

#### Tool Installation Issues

```bash
# If jq is not found
# macOS: brew install jq
# Ubuntu/Debian: sudo apt-get update && sudo apt-get install jq
# Amazon Linux: sudo yum install jq

# If yq is not found
# Download latest version manually
sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
sudo chmod +x /usr/local/bin/yq

# If kubectl is not found or wrong version
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# If Helm is not found
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# If ArgoCD CLI is not found
# Linux
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64

# If direnv is not working
# Add to your shell profile (~/.bashrc, ~/.zshrc)
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc  # for bash
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc    # for zsh
# Then restart your shell or source the profile
```

#### ArgoCD Sync Failures

```bash
# Check application status
kubectl describe application <app-name> -n argocd

# View sync logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server

# Force refresh and sync
argocd app refresh <app-name>
argocd app sync <app-name>
```

#### Backstage Connection Issues

```bash
# Check Backstage logs
kubectl logs -n backstage -l app.kubernetes.io/name=backstage

# Verify database connectivity
kubectl exec -n backstage -it deployment/backstage -- nc -zv postgresql 5432

# Check configuration
kubectl get configmap backstage-config -n backstage -o yaml
```

#### Resource Constraints

```bash
# Check node resources
kubectl describe nodes

# View resource usage
kubectl top nodes
kubectl top pods --all-namespaces --sort-by=memory

# Check for evicted pods
kubectl get pods --all-namespaces --field-selector=status.phase=Failed
```

### Performance Optimization

```bash
# Optimize ArgoCD performance
kubectl patch configmap argocd-cmd-params-cm -n argocd --patch '{"data":{"controller.repo.server.timeout.seconds":"300","controller.self.heal.timeout.seconds":"30"}}'

# Configure resource limits
kubectl patch deployment argocd-server -n argocd --patch '{"spec":{"template":{"spec":{"containers":[{"name":"argocd-server","resources":{"limits":{"cpu":"500m","memory":"1Gi"},"requests":{"cpu":"250m","memory":"512Mi"}}}]}}}}'
```

## Next Steps

After successful platform deployment:

1. **Team Onboarding**: Train development teams on platform capabilities and workflows
2. **Application Migration**: Begin migrating existing applications to the platform
3. **Custom Templates**: Create organization-specific Backstage templates
4. **Security Integration**: Integrate with organizational identity providers and security tools
5. **Compliance Validation**: Ensure platform meets regulatory requirements
6. **Continuous Improvement**: Establish feedback loops and platform evolution processes

For detailed application development patterns and platform usage, explore the application blueprints in the `applications/` directory.