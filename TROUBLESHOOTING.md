---
title: "Troubleshooting Guide - Application Modernization Blueprints"
persona: ["platform-adopter", "infrastructure-engineer", "developer", "workshop-participant"]
deployment-scenario: ["platform-only", "full-workshop", "manual"]
difficulty: "intermediate"
estimated-time: "varies"
prerequisites: ["Platform access", "kubectl", "Basic troubleshooting skills"]
related-pages: ["DEPLOYMENT-GUIDE.md", "ARCHITECTURE.md", "platform-engineering-on-eks/TROUBLESHOOTING.md"]
repository: "appmod-blueprints"
last-updated: "2025-01-19"
---

# Troubleshooting Guide - Application Modernization Blueprints

## Overview

This guide provides solutions to common issues encountered when using the Application Modernization Blueprints platform. Issues are organized by symptoms to help you quickly identify and resolve problems during platform operations and application development.

**📚 For Workshop Participants**: Focus on platform access and application deployment issues to complete workshop exercises
**🏢 For Platform Adopters**: Review GitOps workflows and platform operations troubleshooting for production use  
**⚙️ For Infrastructure Engineers**: Use advanced diagnostics and performance optimization procedures for platform management
**👩‍💻 For Developers**: Check application development and CI/CD pipeline issues for daily development workflows

> **Quick Navigation**: Jump to [Platform Access](#platform-access-issues) | [GitOps Issues](#gitops-and-argocd-issues) | [Application Development](#application-development-issues) | [Performance](#performance-optimization) | [Getting Help](#getting-additional-help)

## Prerequisites

Before troubleshooting, ensure you have:

- Access to the EKS cluster with `kubectl` configured
- ArgoCD CLI installed (optional but helpful)
- Access to platform services (Backstage, GitLab, ArgoCD)
- Proper environment variables set in your development environment
- Understanding of your platform deployment scenario

## Quick Diagnostic Commands

Before diving into specific issues, run these commands to gather basic information:

```bash
# Check platform service status
kubectl get pods -A | grep -E "(argocd|backstage|gitlab|grafana)" | grep -v Running

# Check ArgoCD applications
kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status"

# Check cluster connectivity
kubectl get nodes
kubectl cluster-info

# Check recent events
kubectl get events --sort-by='.lastTimestamp' | tail -10

# Run platform health check
./scripts/0-install.sh --check-only 2>/dev/null || echo "Run ./scripts/0-install.sh to initialize platform"
```

### Platform Service URLs

Get current platform service URLs:

```bash
# Get platform URLs (requires access to hub cluster secrets)
kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null || echo "Platform domain not available"

# Check service endpoints
kubectl get ingress -A
kubectl get services -A --field-selector spec.type=LoadBalancer
```

## Platform Access Issues

### Cannot Access Platform Services

**Symptoms:**
- Backstage, ArgoCD, or GitLab URLs return connection errors
- Services show as running but are not accessible
- Authentication failures across platform services

**Diagnostic Commands:**
```bash
# Check service status
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server
kubectl get pods -n backstage -l app.kubernetes.io/name=backstage
kubectl get pods -n gitlab -l app=gitlab-webservice-default

# Check ingress configuration
kubectl get ingress -A
kubectl get services -A --field-selector spec.type=LoadBalancer

# Check platform URLs script
./scripts/6-tools-urls.sh
```

**Common Causes & Solutions:**

1. **CloudFront Distribution Issues**
   ```bash
   # Check CloudFront distribution status
   aws cloudfront list-distributions --query 'DistributionList.Items[?contains(Origins.Items[0].Id, `http-origin`)]'
   
   # Get current domain name
   DOMAIN_NAME=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null)
   echo "Platform domain: $DOMAIN_NAME"
   ```

2. **Service Pod Issues**
   ```bash
   # Restart problematic services
   kubectl rollout restart deployment argocd-server -n argocd
   kubectl rollout restart deployment backstage -n backstage
   kubectl rollout restart deployment gitlab-webservice-default -n gitlab
   
   # Check pod logs for errors
   kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=50
   kubectl logs -n backstage -l app.kubernetes.io/name=backstage --tail=50
   ```

3. **Authentication Service Issues**
   ```bash
   # Check Keycloak status
   kubectl get pods -n keycloak
   kubectl logs -n keycloak -l app.kubernetes.io/name=keycloak --tail=50
   
   # Restart Keycloak if needed
   kubectl rollout restart deployment keycloak -n keycloak
   ```

### IDE Environment Not Working

**Symptoms:**
- Cannot access development environment
- Environment variables not set correctly
- Tools not available in IDE

**Diagnostic Commands:**
```bash
# Check environment variables
env | grep -E "(AWS_|CLUSTER_|RESOURCE_|WORKSPACE_)"

# Check if bootstrap script ran
ls -la /workspace/appmod-blueprints/scripts/
cat /workspace/appmod-blueprints/.bootstrap-complete 2>/dev/null || echo "Bootstrap not completed"

# Check tool availability
kubectl version --client
aws --version
argocd version --client 2>/dev/null || echo "ArgoCD CLI not available"
```

**Solutions:**
```bash
# Re-run bootstrap script
cd /workspace/appmod-blueprints
./scripts/0-install.sh

# Manually set environment variables if needed
source /etc/profile.d/workshop.sh

# Source bashrc configurations
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        [ -f "$file" ] && source "$file"
    done
fi

# Verify cluster access
kubectl get nodes
```

## GitOps and ArgoCD Issues

### ArgoCD Applications Not Syncing

**Symptoms:**
- Applications stuck in "OutOfSync" state
- Sync operations fail or timeout
- Applications show "Progressing" for extended periods

**Diagnostic Commands:**
```bash
# Check application status
kubectl get applications -n argocd -o wide

# Check specific application details
kubectl describe application <app-name> -n argocd

# Check ArgoCD server logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=100

# Check repository server logs
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=100
```

**Solutions:**

1. **Force Application Sync**
   ```bash
   # Using ArgoCD CLI (if available)
   argocd app sync <app-name> --force
   
   # Using kubectl
   kubectl patch application <app-name> -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
   
   # Terminate stuck operations
   kubectl patch application <app-name> -n argocd --type merge -p '{"operation":null}'
   ```

2. **Repository Access Issues**
   ```bash
   # Check repository secrets
   kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository
   
   # Test repository connectivity
   kubectl exec -n argocd deployment/argocd-repo-server -- git ls-remote https://github.com/aws-samples/appmod-blueprints.git
   
   # Refresh repository cache
   kubectl delete pods -n argocd -l app.kubernetes.io/name=argocd-repo-server
   ```

3. **Resource Conflicts**
   ```bash
   # Check for resource conflicts
   kubectl get events -n <target-namespace> --sort-by='.lastTimestamp'
   
   # Check resource quotas
   kubectl describe resourcequotas -n <target-namespace>
   
   # Check for stuck resources
   kubectl get all -n <target-namespace> | grep -E "(Terminating|Pending)"
   ```

### Cluster Registration Issues

**Symptoms:**
- Spoke clusters not visible in ArgoCD
- Cross-cluster deployments failing
- Cluster secrets missing

**Diagnostic Commands:**
```bash
# Check cluster secrets in ArgoCD
kubectl get secrets -n argocd | grep cluster-

# Check cluster registration script logs
kubectl logs -n argocd job/cluster-registration 2>/dev/null || echo "No cluster registration job found"

# Verify spoke cluster access
kubectl config get-contexts
```

**Solutions:**
```bash
# Re-register spoke clusters
./scripts/3-register-terraform-spoke-clusters.sh dev
./scripts/3-register-terraform-spoke-clusters.sh prod

# Manually add cluster if script fails
argocd cluster add <cluster-context-name> --name <cluster-name>

# Check cluster connectivity
argocd cluster list
```

## Application Development Issues

### Backstage Templates Not Working

**Symptoms:**
- Cannot create new applications from templates
- Template scaffolding fails
- Generated repositories are empty or malformed

**Diagnostic Commands:**
```bash
# Check Backstage pod status
kubectl get pods -n backstage -l app.kubernetes.io/name=backstage

# Check Backstage logs
kubectl logs -n backstage -l app.kubernetes.io/name=backstage --tail=100

# Check template configuration
kubectl get configmap backstage-app-config -n backstage -o yaml | grep -A 20 "catalog:"
```

**Solutions:**
```bash
# Restart Backstage
kubectl rollout restart deployment backstage -n backstage

# Check template repository access
kubectl exec -n backstage deployment/backstage -- curl -s https://github.com/aws-samples/appmod-blueprints/tree/main/backstage/examples/template

# Verify GitLab integration
kubectl get secrets -n backstage | grep gitlab
kubectl logs -n backstage -l app.kubernetes.io/name=backstage | grep -i gitlab
```

### Application Deployment Failures

**Symptoms:**
- Applications created in Backstage don't deploy
- GitOps workflows not triggering
- Applications stuck in initial state

**Diagnostic Commands:**
```bash
# Check if application was created in ArgoCD
kubectl get applications -n argocd | grep <app-name>

# Check GitLab repository creation
# Access GitLab UI and verify repository exists

# Check ArgoCD application events
kubectl describe application <app-name> -n argocd
```

**Solutions:**
```bash
# Manually create ArgoCD application if missing
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app-name>
  namespace: argocd
spec:
  project: default
  source:
    repoURL: <gitlab-repo-url>
    targetRevision: HEAD
    path: deployment
  destination:
    server: https://kubernetes.default.svc
    namespace: <target-namespace>
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF

# Check GitLab webhook configuration
# Verify webhook is configured to trigger ArgoCD sync
```

### Build and CI/CD Issues

**Symptoms:**
- GitLab CI/CD pipelines failing
- Container builds not completing
- Image push failures

**Diagnostic Commands:**
```bash
# Check GitLab runner status
kubectl get pods -n gitlab-runner 2>/dev/null || echo "GitLab runner not found"

# Check GitLab CI/CD logs in GitLab UI
# Navigate to Project > CI/CD > Pipelines

# Check container registry access
kubectl get secrets -n <namespace> | grep regcred
```

**Solutions:**
```bash
# Restart GitLab runners
kubectl rollout restart deployment gitlab-runner -n gitlab-runner 2>/dev/null || echo "No GitLab runner deployment found"

# Check GitLab configuration
kubectl get configmap gitlab-gitlab -n gitlab -o yaml | grep -A 10 "registry:"

# Verify container registry credentials
kubectl create secret docker-registry regcred \
  --docker-server=<registry-url> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email>
```

## Infrastructure and Scaling Issues

### Auto Mode Scaling Problems

**Symptoms:**
- Pods stuck in Pending state
- Insufficient resources despite Auto Mode
- Nodes not scaling up

**Diagnostic Commands:**
```bash
# Check Auto Mode configuration
aws eks describe-cluster --name <cluster-name> --query 'cluster.computeConfig'

# Check pod resource requests
kubectl describe pod <pending-pod-name>

# Check node capacity
kubectl describe nodes | grep -A 5 "Capacity:"

# Check cluster autoscaler logs (if applicable)
kubectl logs -n kube-system -l app=cluster-autoscaler 2>/dev/null || echo "Cluster autoscaler not found"
```

**Solutions:**
```bash
# Verify Auto Mode is enabled
kubectl get nodes -o yaml | grep -E "(compute-type|nodegroup)"

# Check if pods have appropriate resource requests
kubectl patch deployment <deployment-name> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","resources":{"requests":{"cpu":"100m","memory":"128Mi"}}}]}}}}'

# Force pod rescheduling
kubectl delete pod <pending-pod-name>

# Check for resource quotas limiting scaling
kubectl describe resourcequotas -A
```

### Storage Issues

**Symptoms:**
- Persistent volumes not mounting
- Storage class issues
- Database connectivity problems

**Diagnostic Commands:**
```bash
# Check storage classes
kubectl get storageclass

# Check persistent volumes
kubectl get pv,pvc -A

# Check EBS CSI driver
kubectl get pods -n kube-system -l app=ebs-csi-controller
```

**Solutions:**
```bash
# Restart EBS CSI driver
kubectl rollout restart deployment ebs-csi-controller -n kube-system

# Check PVC events
kubectl describe pvc <pvc-name> -n <namespace>

# Verify storage class configuration
kubectl describe storageclass gp3
```

## Monitoring and Observability Issues

### Grafana Not Showing Data

**Symptoms:**
- Grafana dashboards empty
- No metrics data available
- Prometheus not scraping targets

**Diagnostic Commands:**
```bash
# Check Grafana pod status
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Check Prometheus targets
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &
# Visit http://localhost:9090/targets

# Check Prometheus configuration
kubectl get configmap -n monitoring | grep prometheus
```

**Solutions:**
```bash
# Restart monitoring stack
kubectl rollout restart deployment grafana -n monitoring
kubectl rollout restart statefulset prometheus-prometheus-kube-prometheus-prometheus -n monitoring

# Check service monitors
kubectl get servicemonitor -A

# Verify metrics endpoints
kubectl get endpoints -n monitoring
```

### Log Collection Issues

**Symptoms:**
- Logs not appearing in centralized logging
- Fluent Bit or log collectors not working
- High log volume causing issues

**Diagnostic Commands:**
```bash
# Check log collection pods
kubectl get pods -n amazon-cloudwatch 2>/dev/null || echo "CloudWatch logging not configured"
kubectl get pods -n logging 2>/dev/null || echo "Logging namespace not found"

# Check log collector configuration
kubectl get configmap -n amazon-cloudwatch | grep fluent
```

**Solutions:**
```bash
# Restart log collectors
kubectl rollout restart daemonset fluent-bit -n amazon-cloudwatch 2>/dev/null

# Check log collector logs
kubectl logs -n amazon-cloudwatch -l k8s-app=fluent-bit --tail=50

# Adjust log levels if needed
kubectl patch configmap fluent-bit-config -n amazon-cloudwatch --patch '{"data":{"fluent-bit.conf":"[SERVICE]\n    Log_Level info"}}'
```

## Security and Access Issues

### RBAC and Permission Problems

**Symptoms:**
- Users cannot access certain resources
- Service accounts lack necessary permissions
- Pod security policy violations

**Diagnostic Commands:**
```bash
# Check current user permissions
kubectl auth can-i --list

# Check service account permissions
kubectl describe serviceaccount <sa-name> -n <namespace>

# Check role bindings
kubectl get rolebindings,clusterrolebindings -A | grep <user-or-sa>

# Check pod security policies
kubectl get psp 2>/dev/null || echo "Pod Security Policies not configured"
```

**Solutions:**
```bash
# Create necessary role binding
kubectl create rolebinding <binding-name> \
  --clusterrole=<role-name> \
  --user=<username> \
  --namespace=<namespace>

# Check pod security standards
kubectl get namespaces -o yaml | grep -A 3 "pod-security"

# Update service account permissions
kubectl patch serviceaccount <sa-name> -n <namespace> \
  -p '{"metadata":{"annotations":{"eks.amazonaws.com/role-arn":"<role-arn>"}}}'
```

### Network Policy Issues

**Symptoms:**
- Services cannot communicate
- Network connectivity blocked
- DNS resolution failures

**Diagnostic Commands:**
```bash
# Check network policies
kubectl get networkpolicies -A

# Test connectivity between pods
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -qO- http://<service-name>.<namespace>.svc.cluster.local

# Check DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup <service-name>.<namespace>.svc.cluster.local
```

**Solutions:**
```bash
# Temporarily disable network policies for testing
kubectl delete networkpolicy --all -n <namespace>

# Create allow-all network policy for debugging
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-all
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - {}
  egress:
  - {}
EOF

# Check CoreDNS configuration
kubectl get configmap coredns -n kube-system -o yaml
```

## Performance Optimization

### High Resource Usage

**Symptoms:**
- Platform services consuming excessive CPU/memory
- Slow response times
- Frequent pod restarts due to resource limits

**Diagnostic Commands:**
```bash
# Check resource usage
kubectl top pods -A --sort-by=cpu
kubectl top pods -A --sort-by=memory

# Check resource limits and requests
kubectl describe pods -A | grep -A 5 -B 5 "Limits:\|Requests:"

# Check for memory leaks
kubectl logs <pod-name> -n <namespace> | grep -i "out of memory\|oom"
```

**Solutions:**
```bash
# Adjust resource limits
kubectl patch deployment <deployment-name> -n <namespace> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","resources":{"limits":{"cpu":"1000m","memory":"2Gi"},"requests":{"cpu":"500m","memory":"1Gi"}}}]}}}}'

# Enable horizontal pod autoscaling
kubectl autoscale deployment <deployment-name> --cpu-percent=70 --min=2 --max=10

# Check for resource quotas
kubectl describe resourcequotas -A
```

### Database Performance Issues

**Symptoms:**
- Slow database queries
- Connection timeouts
- Database pods restarting frequently

**Diagnostic Commands:**
```bash
# Check database pod status
kubectl get pods -n <namespace> | grep -E "(postgres|mysql|redis)"

# Check database logs
kubectl logs <db-pod-name> -n <namespace> --tail=100

# Check database connections
kubectl exec -it <db-pod-name> -n <namespace> -- psql -U <username> -c "SELECT count(*) FROM pg_stat_activity;"
```

**Solutions:**
```bash
# Increase database resources
kubectl patch statefulset <db-name> -n <namespace> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<db-container>","resources":{"limits":{"cpu":"2000m","memory":"4Gi"}}}]}}}}'

# Check database configuration
kubectl get configmap <db-config> -n <namespace> -o yaml

# Optimize database settings
kubectl patch configmap <db-config> -n <namespace> --patch '{"data":{"postgresql.conf":"max_connections = 200\nshared_buffers = 256MB"}}'
```

## Recovery and Maintenance

### Platform Recovery After Failure

**Symptoms:**
- Multiple services down
- Cluster in degraded state
- Data corruption or loss

**Recovery Steps:**
```bash
# 1. Assess current state
kubectl get pods -A | grep -v Running
kubectl get nodes
kubectl get applications -n argocd

# 2. Restart core services in order
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout restart deployment argocd-server -n argocd
kubectl rollout restart deployment argocd-application-controller -n argocd

# 3. Force sync critical applications
kubectl patch application bootstrap -n argocd --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'

# 4. Check application health
kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status"

# 5. Re-run bootstrap if needed
cd /workspace/appmod-blueprints
./scripts/0-install.sh
```

### Backup and Restore

**Symptoms:**
- Need to backup platform configuration
- Restore from previous state
- Migrate to new cluster

**Backup Commands:**
```bash
# Backup ArgoCD applications
kubectl get applications -n argocd -o yaml > argocd-applications-backup.yaml

# Backup secrets
kubectl get secrets -A -o yaml > secrets-backup.yaml

# Backup configmaps
kubectl get configmaps -A -o yaml > configmaps-backup.yaml

# Backup persistent volume claims
kubectl get pvc -A -o yaml > pvc-backup.yaml
```

**Restore Commands:**
```bash
# Restore ArgoCD applications
kubectl apply -f argocd-applications-backup.yaml

# Restore secrets (be careful with sensitive data)
kubectl apply -f secrets-backup.yaml

# Restore configmaps
kubectl apply -f configmaps-backup.yaml
```

## Getting Additional Help

### Escalation Paths

1. **Platform Documentation**
   - Check platform getting started: [GETTING-STARTED.md](GETTING-STARTED.md)
   - Review platform architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
   - Consult deployment scenarios: [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md)

2. **Infrastructure Issues**
   - For infrastructure deployment issues, see [platform-engineering-on-eks troubleshooting](https://gitlab.aws.dev/aws-samples/platform-engineering-on-eks/-/blob/main/TROUBLESHOOTING.md)
   - Check CDK deployment documentation

3. **Platform Team Support**
   - Check internal documentation and runbooks
   - Contact platform engineering team
   - Review platform architecture documentation

4. **Community Resources**
   - [ArgoCD Community](https://github.com/argoproj/argo-cd/discussions)
   - [Backstage Community](https://github.com/backstage/backstage/discussions)
   - [Kubernetes Slack](https://kubernetes.slack.com/)
   - [Platform Engineering Community](https://platformengineering.org/)

5. **AWS Support**
   - For EKS-related issues, create AWS support case
   - Include cluster name, region, and error messages
   - Check [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)

### Collecting Diagnostic Information

Before seeking help, collect this information:

```bash
# Create diagnostic bundle
mkdir -p platform-diagnostics/$(date +%Y%m%d-%H%M%S)
cd platform-diagnostics/$(date +%Y%m%d-%H%M%S)

# Basic cluster information
kubectl cluster-info > cluster-info.txt
kubectl get nodes -o wide > nodes.txt
kubectl version > version.txt

# Platform service status
kubectl get pods -A > all-pods.txt
kubectl get applications -n argocd -o wide > argocd-apps.txt
kubectl get ingress -A > ingress.txt
kubectl get services -A > services.txt

# Recent events
kubectl get events --sort-by='.lastTimestamp' > events.txt

# Logs from key services
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=200 > argocd-server.log
kubectl logs -n backstage -l app.kubernetes.io/name=backstage --tail=200 > backstage.log
kubectl logs -n gitlab -l app=gitlab-webservice-default --tail=200 > gitlab.log

# Configuration
kubectl get configmaps -A -o yaml > configmaps.yaml
kubectl get secrets -A -o yaml > secrets.yaml  # Be careful with sensitive data

# Create archive
cd ..
tar -czf platform-diagnostics-$(date +%Y%m%d-%H%M%S).tar.gz $(date +%Y%m%d-%H%M%S)/
```

### Log Analysis

```bash
# Search for common error patterns
grep -r -i "error\|fail\|exception" platform-diagnostics/

# Check for resource issues
grep -r -i "insufficient\|resource\|memory\|cpu" platform-diagnostics/

# Look for network issues
grep -r -i "connection\|timeout\|dns\|network" platform-diagnostics/

# Check authentication problems
grep -r -i "auth\|permission\|forbidden\|unauthorized" platform-diagnostics/
```

This diagnostic information will help support teams identify and resolve issues more efficiently.

## Platform Deployment Scenarios

### Platform-Only Deployment

**🏢 For Platform Adopters**: Troubleshooting platform without workshop components

**Symptoms:**
- Deploying platform services without workshop-specific components
- Need production-ready configuration
- Want to customize platform for organizational needs

**Verification Steps:**
```bash
# Check core platform services
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server
kubectl get pods -n backstage -l app.kubernetes.io/name=backstage

# Verify GitOps is working
kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status"

# Check platform configuration
kubectl get configmap backstage-app-config -n backstage -o yaml | grep -A 5 "organization:"
```

**Common Platform-Only Issues:**

1. **Missing Workshop Dependencies**
   ```bash
   # Remove workshop-specific applications
   kubectl delete applications -n argocd -l workshop=true 2>/dev/null
   
   # Update platform configuration for production
   kubectl patch configmap backstage-app-config -n backstage --patch '{"data":{"app-config.yaml":"organization:\n  name: Your Organization"}}'
   ```

2. **Authentication Configuration**
   ```bash
   # Configure production authentication
   kubectl get secrets -n backstage | grep auth
   kubectl get configmap backstage-app-config -n backstage -o yaml | grep -A 10 "auth:"
   
   # Update for your identity provider
   kubectl patch configmap backstage-app-config -n backstage --patch '{"data":{"app-config.yaml":"auth:\n  providers:\n    oauth2Proxy: {}\n  environment: production"}}'
   ```

### IDE-Only Setup

**👩‍💻 For Developers**: Setting up development environment without full platform

**Symptoms:**
- Want development environment without full platform overhead
- Need access to platform tools for development
- Working on platform customization

**Setup Commands:**
```bash
# Minimal environment setup
export AWS_PROFILE=your-profile
export AWS_REGION=your-region
export KUBECONFIG=~/.kube/config

# Install required tools
curl -sSL https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64 -o argocd
chmod +x argocd && sudo mv argocd /usr/local/bin/

# Connect to existing cluster
aws eks update-kubeconfig --region $AWS_REGION --name your-cluster-name
kubectl get nodes
```

**Development Workflow:**
```bash
# Clone platform repositories
git clone https://github.com/aws-samples/appmod-blueprints.git
cd appmod-blueprints

# Set up development environment
source ./scripts/setup-dev-env.sh 2>/dev/null || echo "Set environment variables manually"

# Test platform connectivity
kubectl get applications -n argocd
argocd app list --server argocd-server.argocd.svc.cluster.local
```

### Manual Configuration

**⚙️ For Infrastructure Engineers**: Step-by-step manual setup without automation

**Symptoms:**
- Automation scripts not working in your environment
- Need to understand each step for customization
- Working in restricted environment

**Manual Setup Steps:**

1. **Core Platform Services:**
   ```bash
   # Install ArgoCD
   kubectl create namespace argocd
   kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
   
   # Wait for ArgoCD to be ready
   kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
   ```

2. **Platform Applications:**
   ```bash
   # Create bootstrap application
   kubectl apply -f - <<EOF
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: bootstrap
     namespace: argocd
   spec:
     project: default
     source:
       repoURL: https://github.com/aws-samples/appmod-blueprints.git
       targetRevision: HEAD
       path: gitops/platform/bootstrap
     destination:
       server: https://kubernetes.default.svc
       namespace: argocd
     syncPolicy:
       automated:
         prune: true
         selfHeal: true
   EOF
   ```

3. **Verify Manual Setup:**
   ```bash
   # Check all applications are synced
   kubectl get applications -n argocd
   
   # Verify platform services
   kubectl get pods -A | grep -E "(argocd|backstage|gitlab)"
   
   # Test platform functionality
   kubectl port-forward svc/argocd-server -n argocd 8080:443 &
   curl -k https://localhost:8080/api/version
   ```

## GitOps Workflow Issues

### Application Sync Loops

**Symptoms:**
- Applications continuously syncing without reaching healthy state
- Sync operations succeed but immediately trigger new sync
- Resource conflicts between ArgoCD and manual changes

**Diagnostic Commands:**
```bash
# Check application sync history
kubectl describe application <app-name> -n argocd | grep -A 10 "Operation:"

# Check for resource conflicts
kubectl get events -n <target-namespace> --sort-by='.lastTimestamp' | grep -i conflict

# Check for manual changes outside GitOps
kubectl diff -f <manifest-file>

# Monitor sync operations
watch 'kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,OPERATION:.status.operationState.phase"'
```

**Solutions:**
```bash
# Disable auto-sync temporarily
kubectl patch application <app-name> -n argocd --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}'

# Force hard refresh
kubectl patch application <app-name> -n argocd --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'

# Reset application to clean state
kubectl patch application <app-name> -n argocd --type merge -p '{"operation":null}'
kubectl patch application <app-name> -n argocd --type merge -p '{"status":null}'

# Re-enable auto-sync after fixing conflicts
kubectl patch application <app-name> -n argocd --type merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

### Multi-Cluster GitOps Issues

**Symptoms:**
- Applications not deploying to spoke clusters
- Cluster connectivity issues
- Cross-cluster resource dependencies failing

**Diagnostic Commands:**
```bash
# Check cluster registration status
argocd cluster list

# Test cluster connectivity
kubectl --context=<spoke-cluster-context> get nodes

# Check cluster secrets in ArgoCD
kubectl get secrets -n argocd | grep cluster-

# Verify cluster access from ArgoCD
kubectl exec -n argocd deployment/argocd-server -- argocd cluster list
```

**Solutions:**
```bash
# Re-register spoke cluster
argocd cluster add <cluster-context> --name <cluster-name>

# Update cluster credentials
kubectl patch secret <cluster-secret> -n argocd --type merge -p '{"data":{"config":"<base64-encoded-kubeconfig>"}}'

# Test cross-cluster deployment
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: test-spoke-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/aws-samples/appmod-blueprints.git
    targetRevision: HEAD
    path: applications/rust/deployment/dev
  destination:
    server: <spoke-cluster-server>
    namespace: test
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
EOF
```

## Platform Operations Issues

### Resource Management and Scaling

**Symptoms:**
- Platform services consuming excessive resources
- Auto-scaling not working as expected
- Resource quotas preventing deployments

**Diagnostic Commands:**
```bash
# Check platform resource consumption
kubectl top pods -n argocd --sort-by=cpu
kubectl top pods -n backstage --sort-by=memory
kubectl top pods -n gitlab --sort-by=memory

# Check resource quotas and limits
kubectl describe resourcequotas -A
kubectl describe limitranges -A

# Check horizontal pod autoscaler status
kubectl get hpa -A
kubectl describe hpa <hpa-name> -n <namespace>

# Monitor resource usage over time
kubectl top nodes --sort-by=cpu
kubectl top nodes --sort-by=memory
```

**Solutions:**
```bash
# Adjust resource limits for platform services
kubectl patch deployment argocd-server -n argocd -p '{"spec":{"template":{"spec":{"containers":[{"name":"argocd-server","resources":{"limits":{"cpu":"1000m","memory":"2Gi"},"requests":{"cpu":"500m","memory":"1Gi"}}}]}}}}'

# Enable HPA for platform services
kubectl autoscale deployment backstage -n backstage --cpu-percent=70 --min=2 --max=5

# Adjust resource quotas
kubectl patch resourcequota <quota-name> -n <namespace> --type merge -p '{"spec":{"hard":{"requests.cpu":"4","requests.memory":"8Gi"}}}'

# Scale platform services based on usage
kubectl scale deployment argocd-repo-server --replicas=3 -n argocd
kubectl scale deployment gitlab-sidekiq-all-in-1-v2 --replicas=2 -n gitlab
```

### Platform Service Dependencies

**Symptoms:**
- Services failing due to dependency issues
- Database connectivity problems
- External service integration failures

**Diagnostic Commands:**
```bash
# Check service dependencies
kubectl get pods -A -o wide | grep -E "(postgres|redis|keycloak)"

# Test database connectivity
kubectl exec -it deployment/backstage -n backstage -- nc -zv postgresql 5432
kubectl exec -it deployment/gitlab-webservice-default -n gitlab -- nc -zv redis 6379

# Check external service connectivity
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -qO- https://api.github.com
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup github.com

# Check service mesh configuration (if applicable)
kubectl get virtualservices -A
kubectl get destinationrules -A
```

**Solutions:**
```bash
# Restart dependent services in order
kubectl rollout restart deployment postgresql -n postgresql
kubectl rollout restart deployment redis -n redis
kubectl rollout restart deployment keycloak -n keycloak
kubectl rollout restart deployment backstage -n backstage

# Fix database connection issues
kubectl patch deployment backstage -n backstage -p '{"spec":{"template":{"spec":{"containers":[{"name":"backstage","env":[{"name":"POSTGRES_HOST","value":"postgresql.postgresql.svc.cluster.local"}]}]}}}}'

# Update external service configurations
kubectl patch configmap backstage-app-config -n backstage --patch '{"data":{"app-config.yaml":"integrations:\n  github:\n    - host: github.com\n      token: ${GITHUB_TOKEN}"}}'
```

## Application Development Troubleshooting

### Template and Scaffolding Issues

**Symptoms:**
- Backstage templates failing to generate code
- Generated applications missing files
- Template parameters not being substituted

**Diagnostic Commands:**
```bash
# Check template catalog status
kubectl logs -n backstage -l app.kubernetes.io/name=backstage | grep -i template

# Verify template repository access
kubectl exec -n backstage deployment/backstage -- curl -s https://github.com/aws-samples/appmod-blueprints/tree/main/platform/backstage/templates

# Check template configuration
kubectl get configmap backstage-app-config -n backstage -o yaml | grep -A 20 "catalog:"

# Test template processing
kubectl exec -it deployment/backstage -n backstage -- cat /app/app-config.yaml | grep -A 10 "techdocs:"
```

**Solutions:**
```bash
# Refresh template catalog
kubectl exec -n backstage deployment/backstage -- curl -X POST http://localhost:7007/api/catalog/refresh

# Update template repository configuration
kubectl patch configmap backstage-app-config -n backstage --patch '{"data":{"app-config.yaml":"catalog:\n  locations:\n    - type: url\n      target: https://github.com/aws-samples/appmod-blueprints/blob/main/platform/backstage/templates/template.yaml"}}'

# Restart Backstage to reload templates
kubectl rollout restart deployment backstage -n backstage

# Check template validation
kubectl logs -n backstage -l app.kubernetes.io/name=backstage | grep -i "template.*error"
```

## Quick Reference

### Essential Platform Commands

```bash
# Platform health check
./scripts/0-install.sh --check-only

# ArgoCD application status
kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status"

# Platform service status
kubectl get pods -A | grep -E "(argocd|backstage|gitlab|grafana)" | grep -v Running

# Force sync all applications
kubectl patch applications -n argocd --all --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'

# Reset platform to clean state
./scripts/restore_template_defaults.sh
```

### Platform Service Access

```bash
# Get platform domain
kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null

# Port forward for local access
kubectl port-forward svc/argocd-server -n argocd 8080:443 &
kubectl port-forward svc/backstage -n backstage 8081:7007 &
kubectl port-forward svc/gitlab-webservice-default -n gitlab 8082:8181 &
```

### Development Workflow

```bash
# Create new application from template
# Use Backstage UI: https://<domain>/backstage/create

# Check application deployment
kubectl get applications -n argocd | grep <app-name>
kubectl get pods -n <app-namespace>

# Debug application issues
kubectl describe application <app-name> -n argocd
kubectl logs -n <app-namespace> -l app=<app-name>
```

### Common File Locations

- Platform configuration: `/workspace/appmod-blueprints/gitops/`
- Application templates: `/workspace/appmod-blueprints/platform/backstage/templates/`
- Platform components: `/workspace/appmod-blueprints/platform/components/`
- Deployment manifests: `/workspace/appmod-blueprints/applications/`
- Scripts: `/workspace/appmod-blueprints/scripts/`

### Related Documentation

- [Getting Started Guide](GETTING-STARTED.md) - Platform evaluation and setup
- [Architecture Documentation](ARCHITECTURE.md) - Platform components and design
- [Deployment Guide](DEPLOYMENT-GUIDE.md) - Platform deployment scenarios
- [Infrastructure Troubleshooting](https://gitlab.aws.dev/aws-samples/platform-engineering-on-eks/-/blob/main/TROUBLESHOOTING.md) - Infrastructure-specific issues

### CI/CD Pipeline Failures

**Symptoms:**
- GitLab CI/CD pipelines not triggering
- Build failures in pipelines
- Deployment stages failing

**Diagnostic Commands:**
```bash
# Check GitLab runner status
kubectl get pods -n gitlab-runner
kubectl logs -n gitlab-runner -l app=gitlab-runner --tail=50

# Check GitLab CI/CD configuration
# (Access GitLab UI and check Project > Settings > CI/CD)

# Verify container registry access
kubectl get secrets -A | grep regcred
kubectl describe secret regcred -n <namespace>

# Check pipeline logs in GitLab UI
# Navigate to Project > CI/CD > Pipelines > [Pipeline] > Jobs
```

**Solutions:**
```bash
# Restart GitLab runners
kubectl rollout restart deployment gitlab-runner -n gitlab-runner

# Update runner configuration
kubectl patch configmap gitlab-runner-config -n gitlab-runner --patch '{"data":{"config.toml":"concurrent = 4\ncheck_interval = 0\n\n[session_server]\n  session_timeout = 1800"}}'

# Fix container registry credentials
kubectl create secret docker-registry regcred \
  --docker-server=<registry-url> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n <namespace>

# Update GitLab CI/CD variables
# Use GitLab UI: Project > Settings > CI/CD > Variables
```

### Application Runtime Issues

**Symptoms:**
- Applications crashing after deployment
- Performance issues in deployed applications
- Service-to-service communication failures

**Diagnostic Commands:**
```bash
# Check application pod status
kubectl get pods -n <app-namespace> -o wide

# Check application logs
kubectl logs -n <app-namespace> -l app=<app-name> --tail=100

# Check service endpoints
kubectl get endpoints -n <app-namespace>

# Test service connectivity
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -qO- http://<service-name>.<namespace>.svc.cluster.local

# Check resource usage
kubectl top pods -n <app-namespace>
```

**Solutions:**
```bash
# Adjust application resource limits
kubectl patch deployment <app-name> -n <app-namespace> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","resources":{"limits":{"cpu":"1000m","memory":"1Gi"},"requests":{"cpu":"100m","memory":"256Mi"}}}]}}}}'

# Fix service configuration
kubectl patch service <service-name> -n <app-namespace> -p '{"spec":{"ports":[{"port":80,"targetPort":8080}]}}'

# Enable application health checks
kubectl patch deployment <app-name> -n <app-namespace> -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","livenessProbe":{"httpGet":{"path":"/health","port":8080},"initialDelaySeconds":30,"periodSeconds":10}}]}}}}'

# Scale application based on load
kubectl autoscale deployment <app-name> -n <app-namespace> --cpu-percent=70 --min=2 --max=10
```

## Security and Compliance Issues

### RBAC and Access Control

**Symptoms:**
- Users cannot access platform services
- Service accounts lack necessary permissions
- Cross-namespace access issues

**Diagnostic Commands:**
```bash
# Check current user permissions
kubectl auth can-i --list --as=<username>

# Check service account permissions
kubectl describe serviceaccount <sa-name> -n <namespace>
kubectl get rolebindings,clusterrolebindings -A | grep <sa-name>

# Check RBAC policies
kubectl get roles,clusterroles -A | grep <role-name>
kubectl describe role <role-name> -n <namespace>

# Test specific permissions
kubectl auth can-i create pods --as=system:serviceaccount:<namespace>:<sa-name>
```

**Solutions:**
```bash
# Create necessary role binding
kubectl create rolebinding <binding-name> \
  --clusterrole=<role-name> \
  --serviceaccount=<namespace>:<sa-name> \
  --namespace=<namespace>

# Create custom role for specific permissions
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: <namespace>
  name: <role-name>
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["get", "list", "create", "update", "patch", "delete"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "create", "update", "patch", "delete"]
EOF

# Update service account with IAM role (for AWS)
kubectl patch serviceaccount <sa-name> -n <namespace> \
  -p '{"metadata":{"annotations":{"eks.amazonaws.com/role-arn":"<role-arn>"}}}'
```

### Secret Management Issues

**Symptoms:**
- Applications cannot access secrets
- Secret rotation not working
- External secret integration failures

**Diagnostic Commands:**
```bash
# Check secret availability
kubectl get secrets -A | grep <secret-name>
kubectl describe secret <secret-name> -n <namespace>

# Check external secrets operator
kubectl get pods -n external-secrets-system
kubectl logs -n external-secrets-system -l app.kubernetes.io/name=external-secrets

# Check secret store configuration
kubectl get secretstore -A
kubectl describe secretstore <store-name> -n <namespace>

# Test secret access from pod
kubectl exec -it <pod-name> -n <namespace> -- env | grep <SECRET_VAR>
```

**Solutions:**
```bash
# Restart external secrets operator
kubectl rollout restart deployment external-secrets -n external-secrets-system

# Force secret refresh
kubectl patch externalsecret <external-secret-name> -n <namespace> --type merge -p '{"metadata":{"annotations":{"force-sync":"'$(date +%s)'"}}}'

# Create manual secret if external secrets fail
kubectl create secret generic <secret-name> \
  --from-literal=<key>=<value> \
  -n <namespace>

# Update secret store configuration
kubectl patch secretstore <store-name> -n <namespace> --type merge -p '{"spec":{"provider":{"aws":{"region":"<region>","auth":{"secretRef":{"accessKeyID":{"name":"<secret-name>","key":"access-key"}}}}}}}'
```

## Monitoring and Alerting

### Observability Stack Issues

**Symptoms:**
- Metrics not appearing in Grafana
- Prometheus not scraping targets
- Alert manager not sending notifications

**Diagnostic Commands:**
```bash
# Check monitoring stack status
kubectl get pods -n monitoring

# Check Prometheus targets
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &
# Visit http://localhost:9090/targets

# Check Grafana data sources
kubectl port-forward -n monitoring svc/grafana 3000:3000 &
# Visit http://localhost:3000 and check data sources

# Check alert manager configuration
kubectl get configmap alertmanager-config -n monitoring -o yaml
```

**Solutions:**
```bash
# Restart monitoring components
kubectl rollout restart deployment grafana -n monitoring
kubectl rollout restart statefulset prometheus-prometheus-kube-prometheus-prometheus -n monitoring
kubectl rollout restart statefulset alertmanager-alertmanager-kube-prometheus-alertmanager -n monitoring

# Fix service monitor configuration
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: <app-name>-metrics
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: <app-name>
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
EOF

# Update Grafana data source
kubectl patch configmap grafana-datasources -n monitoring --patch '{"data":{"datasources.yaml":"apiVersion: 1\ndatasources:\n- name: Prometheus\n  type: prometheus\n  url: http://prometheus-operated:9090\n  access: proxy\n  isDefault: true"}}'
```

This comprehensive troubleshooting guide provides platform operators and developers with the tools and procedures needed to diagnose and resolve common issues in the Application Modernization Blueprints platform.