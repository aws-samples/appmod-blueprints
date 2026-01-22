#!/bin/bash

# EKS Auto Mode Cluster Validation Script
# This script validates all aspects of the auto mode cluster functionality

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if kubectl is available and cluster is accessible
check_cluster_access() {
    log_info "Checking cluster access..."
    if ! kubectl cluster-info &>/dev/null; then
        log_error "Cannot access Kubernetes cluster. Please ensure kubectl is configured correctly."
        exit 1
    fi
    log_info "✓ Cluster access confirmed"
}

# Validate auto mode nodes are present and healthy
validate_auto_mode_nodes() {
    log_info "Validating auto mode nodes..."
    
    # Check if nodes exist
    NODE_COUNT=$(kubectl get nodes --no-headers | wc -l)
    if [ "$NODE_COUNT" -eq 0 ]; then
        log_error "No nodes found in cluster"
        return 1
    fi
    
    log_info "Found $NODE_COUNT nodes"
    
    # Check node readiness
    NOT_READY=$(kubectl get nodes --no-headers | grep -v " Ready " | wc -l)
    if [ "$NOT_READY" -gt 0 ]; then
        log_warn "$NOT_READY nodes are not ready"
        kubectl get nodes
    else
        log_info "✓ All nodes are ready"
    fi
    
    # Check for auto mode labels/annotations
    log_info "Checking for auto mode characteristics..."
    kubectl get nodes -o yaml | grep -E "(eks.amazonaws.com/compute-type|eks.amazonaws.com/nodegroup)" || true
    
    # Display node details
    log_info "Node details:"
    kubectl get nodes -o wide
}

# Validate all addons are working with auto mode nodes
validate_addons() {
    log_info "Validating EKS addons..."
    
    # List all addons
    ADDONS=$(kubectl get pods -A --no-headers | grep -E "(kube-system|amazon-cloudwatch|external-secrets)" | wc -l)
    log_info "Found $ADDONS addon pods across system namespaces"
    
    # Check core addons
    local addons_to_check=(
        "kube-system:coredns"
        "kube-system:aws-node"
        "kube-system:kube-proxy"
        "amazon-cloudwatch:cloudwatch-agent"
        "external-secrets-system:external-secrets"
    )
    
    for addon in "${addons_to_check[@]}"; do
        namespace=$(echo $addon | cut -d: -f1)
        name=$(echo $addon | cut -d: -f2)
        
        if kubectl get pods -n $namespace | grep -q $name; then
            READY_PODS=$(kubectl get pods -n $namespace | grep $name | grep -c "Running\|Completed" || echo "0")
            TOTAL_PODS=$(kubectl get pods -n $namespace | grep $name | wc -l)
            
            if [ "$READY_PODS" -eq "$TOTAL_PODS" ] && [ "$TOTAL_PODS" -gt 0 ]; then
                log_info "✓ $name addon is healthy ($READY_PODS/$TOTAL_PODS pods ready)"
            else
                log_warn "⚠ $name addon may have issues ($READY_PODS/$TOTAL_PODS pods ready)"
            fi
        else
            log_warn "⚠ $name addon not found in namespace $namespace"
        fi
    done
}

# Test ArgoCD connectivity and cluster management
validate_argocd_connectivity() {
    log_info "Validating ArgoCD connectivity..."
    
    # Check if ArgoCD namespace exists
    if kubectl get namespace argocd &>/dev/null; then
        log_info "✓ ArgoCD namespace found"
        
        # Check ArgoCD pods
        ARGOCD_PODS=$(kubectl get pods -n argocd --no-headers | wc -l)
        READY_ARGOCD_PODS=$(kubectl get pods -n argocd --no-headers | grep -c "Running" || echo "0")
        
        log_info "ArgoCD pods: $READY_ARGOCD_PODS/$ARGOCD_PODS ready"
        
        # Check for cluster secrets (indicates hub connectivity)
        CLUSTER_SECRETS=$(kubectl get secrets -n argocd | grep -c "cluster-" || echo "0")
        if [ "$CLUSTER_SECRETS" -gt 0 ]; then
            log_info "✓ Found $CLUSTER_SECRETS cluster secrets (hub connectivity configured)"
        else
            log_warn "⚠ No cluster secrets found - hub connectivity may not be configured"
        fi
        
    else
        log_warn "⚠ ArgoCD namespace not found - checking for GitOps configuration"
        
        # Check for other GitOps indicators
        if kubectl get configmaps -A | grep -q "argocd\|gitops"; then
            log_info "✓ GitOps configuration found"
        else
            log_warn "⚠ No GitOps configuration detected"
        fi
    fi
}

# Verify pod identity associations are working
validate_pod_identity() {
    log_info "Validating pod identity associations..."
    
    # Check for pod identity webhook
    if kubectl get pods -n kube-system | grep -q "eks-pod-identity"; then
        log_info "✓ EKS Pod Identity webhook found"
        
        # Check webhook status
        POD_IDENTITY_STATUS=$(kubectl get pods -n kube-system | grep eks-pod-identity | awk '{print $3}')
        if [ "$POD_IDENTITY_STATUS" = "Running" ]; then
            log_info "✓ Pod Identity webhook is running"
        else
            log_warn "⚠ Pod Identity webhook status: $POD_IDENTITY_STATUS"
        fi
    else
        log_warn "⚠ EKS Pod Identity webhook not found"
    fi
    
    # Check for service accounts with pod identity annotations
    SA_WITH_IDENTITY=$(kubectl get serviceaccounts -A -o yaml | grep -c "eks.amazonaws.com/role-arn" || echo "0")
    if [ "$SA_WITH_IDENTITY" -gt 0 ]; then
        log_info "✓ Found $SA_WITH_IDENTITY service accounts with pod identity annotations"
    else
        log_warn "⚠ No service accounts with pod identity annotations found"
    fi
    
    # Test specific pod identity services
    local services_to_check=(
        "external-secrets-system:external-secrets"
        "amazon-cloudwatch:cloudwatch-agent"
    )
    
    for service in "${services_to_check[@]}"; do
        namespace=$(echo $service | cut -d: -f1)
        name=$(echo $service | cut -d: -f2)
        
        if kubectl get serviceaccount -n $namespace $name &>/dev/null; then
            ROLE_ARN=$(kubectl get serviceaccount -n $namespace $name -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}' 2>/dev/null || echo "")
            if [ -n "$ROLE_ARN" ]; then
                log_info "✓ $name has pod identity role: $ROLE_ARN"
            else
                log_warn "⚠ $name service account exists but no pod identity role found"
            fi
        else
            log_warn "⚠ Service account $name not found in namespace $namespace"
        fi
    done
}

# Test workload deployment and scaling
test_workload_deployment() {
    log_info "Testing workload deployment and scaling..."
    
    # Create a test deployment
    cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: automode-test-deployment
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: automode-test
  template:
    metadata:
      labels:
        app: automode-test
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
        ports:
        - containerPort: 80
EOF

    # Wait for deployment to be ready
    log_info "Waiting for test deployment to be ready..."
    if kubectl wait --for=condition=available --timeout=300s deployment/automode-test-deployment; then
        log_info "✓ Test deployment is ready"
        
        # Check pod placement
        log_info "Checking pod placement on auto mode nodes..."
        kubectl get pods -l app=automode-test -o wide
        
        # Test scaling
        log_info "Testing horizontal scaling..."
        kubectl scale deployment automode-test-deployment --replicas=4
        
        if kubectl wait --for=condition=available --timeout=180s deployment/automode-test-deployment; then
            log_info "✓ Scaling test successful"
            kubectl get pods -l app=automode-test -o wide
        else
            log_warn "⚠ Scaling test failed or timed out"
        fi
        
        # Clean up test deployment
        kubectl delete deployment automode-test-deployment
        log_info "✓ Test deployment cleaned up"
        
    else
        log_error "✗ Test deployment failed to become ready"
        kubectl describe deployment automode-test-deployment
        return 1
    fi
}

# Test HPA functionality (if metrics server is available)
test_hpa_functionality() {
    log_info "Testing HPA functionality..."
    
    # Check if metrics server is available
    if kubectl get deployment metrics-server -n kube-system &>/dev/null; then
        log_info "✓ Metrics server found, testing HPA"
        
        # Create test deployment with HPA
        cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hpa-test-deployment
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hpa-test
  template:
    metadata:
      labels:
        app: hpa-test
    spec:
      containers:
      - name: php-apache
        image: registry.k8s.io/hpa-example
        ports:
        - containerPort: 80
        resources:
          limits:
            cpu: 500m
          requests:
            cpu: 200m
---
apiVersion: v1
kind: Service
metadata:
  name: hpa-test-service
  namespace: default
spec:
  ports:
  - port: 80
  selector:
    app: hpa-test
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hpa-test-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hpa-test-deployment
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 50
EOF

        # Wait for HPA to be ready
        sleep 30
        HPA_STATUS=$(kubectl get hpa hpa-test-hpa -o jsonpath='{.status.conditions[0].type}' 2>/dev/null || echo "")
        if [ "$HPA_STATUS" = "AbleToScale" ]; then
            log_info "✓ HPA is functional"
        else
            log_warn "⚠ HPA status: $HPA_STATUS"
        fi
        
        # Clean up HPA test
        kubectl delete hpa hpa-test-hpa
        kubectl delete service hpa-test-service
        kubectl delete deployment hpa-test-deployment
        log_info "✓ HPA test resources cleaned up"
        
    else
        log_warn "⚠ Metrics server not found, skipping HPA test"
    fi
}

# Generate validation report
generate_report() {
    log_info "Generating validation report..."
    
    cat <<EOF > automode-validation-report.txt
EKS Auto Mode Cluster Validation Report
Generated: $(date)
Cluster: $(kubectl config current-context)

=== CLUSTER OVERVIEW ===
$(kubectl get nodes -o wide)

=== ADDON STATUS ===
$(kubectl get pods -A | grep -E "(kube-system|amazon-cloudwatch|external-secrets)")

=== POD IDENTITY ASSOCIATIONS ===
$(kubectl get serviceaccounts -A -o yaml | grep -A1 -B1 "eks.amazonaws.com/role-arn" || echo "No pod identity associations found")

=== ARGOCD STATUS ===
$(kubectl get pods -n argocd 2>/dev/null || echo "ArgoCD namespace not found")

=== CLUSTER EVENTS (LAST 10) ===
$(kubectl get events --sort-by='.lastTimestamp' | tail -10)

EOF

    log_info "✓ Validation report saved to automode-validation-report.txt"
}

# Main execution
main() {
    log_info "Starting EKS Auto Mode Cluster Validation"
    log_info "=========================================="
    
    check_cluster_access
    validate_auto_mode_nodes
    validate_addons
    validate_argocd_connectivity
    validate_pod_identity
    test_workload_deployment
    test_hpa_functionality
    generate_report
    
    log_info "=========================================="
    log_info "EKS Auto Mode Cluster Validation Complete"
    log_info "Check automode-validation-report.txt for detailed results"
}

# Run main function
main "$@"