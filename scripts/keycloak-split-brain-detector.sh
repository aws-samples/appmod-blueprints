#!/bin/bash
# Keycloak Split-Brain Detection and Auto-Healing Script
# Detects when Keycloak pods fail to join the cluster and restarts the isolated pod

set -euo pipefail

NAMESPACE="${KEYCLOAK_NAMESPACE:-keycloak}"
STATEFULSET="keycloak"
LOG_FILE="${LOG_FILE:-/tmp/keycloak-split-brain.log}"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

get_cluster_members() {
    local pod=$1
    kubectl logs -n "$NAMESPACE" "$pod" --tail=1000 2>/dev/null | \
        grep "Received new cluster view" | tail -1 | \
        grep -oP '\(\K[0-9]+(?=\))' || echo "0"
}

check_split_brain() {
    log "Checking Keycloak cluster health..."
    
    # Get all Keycloak pods
    local pods=($(kubectl get pods -n "$NAMESPACE" -l app=keycloak -o jsonpath='{.items[*].metadata.name}'))
    
    if [ ${#pods[@]} -lt 2 ]; then
        log "Only ${#pods[@]} pod(s) found, skipping split-brain check"
        return 0
    fi
    
    log "Found ${#pods[@]} Keycloak pods: ${pods[*]}"
    
    # Check cluster membership for each pod
    declare -A cluster_sizes
    for pod in "${pods[@]}"; do
        local members=$(get_cluster_members "$pod")
        cluster_sizes[$pod]=$members
        log "Pod $pod reports cluster size: $members"
    done
    
    # Detect split-brain: pods reporting different cluster sizes
    local expected_size=${#pods[@]}
    local split_brain_detected=false
    local isolated_pod=""
    
    for pod in "${pods[@]}"; do
        local size=${cluster_sizes[$pod]}
        if [ "$size" -eq 1 ] && [ "$expected_size" -gt 1 ]; then
            log "⚠️  SPLIT-BRAIN DETECTED: $pod is isolated (cluster size: 1, expected: $expected_size)"
            split_brain_detected=true
            isolated_pod=$pod
            break
        elif [ "$size" -ne "$expected_size" ] && [ "$size" -ne 0 ]; then
            log "⚠️  SPLIT-BRAIN DETECTED: $pod reports cluster size $size (expected: $expected_size)"
            split_brain_detected=true
            isolated_pod=$pod
            break
        fi
    done
    
    if [ "$split_brain_detected" = true ]; then
        log "🔧 Attempting to heal split-brain by restarting $isolated_pod"
        heal_split_brain "$isolated_pod"
        return 1
    else
        log "✅ Cluster is healthy, all pods in sync"
        return 0
    fi
}

heal_split_brain() {
    local pod=$1
    
    log "Deleting isolated pod: $pod"
    kubectl delete pod -n "$NAMESPACE" "$pod" --grace-period=30
    
    log "Waiting for pod to restart..."
    kubectl wait --for=condition=ready pod -n "$NAMESPACE" "$pod" --timeout=300s
    
    log "Waiting 30s for cluster to stabilize..."
    sleep 30
    
    # Verify healing
    local new_size=$(get_cluster_members "$pod")
    local expected_size=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=keycloak --no-headers | wc -l)
    
    if [ "$new_size" -eq "$expected_size" ]; then
        log "✅ Split-brain healed! Pod $pod successfully joined cluster (size: $new_size)"
    else
        log "❌ Healing failed! Pod $pod still reports cluster size: $new_size (expected: $expected_size)"
    fi
}

# Main execution
log "=== Keycloak Split-Brain Detector Started ==="
check_split_brain
exit_code=$?
log "=== Check completed with exit code: $exit_code ==="
exit $exit_code
