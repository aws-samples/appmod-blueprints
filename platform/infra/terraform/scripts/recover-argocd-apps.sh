#!/bin/bash
set -e

# Fixed 2026-02-05: Added hard refresh to resolve Git revision conflicts
# Source utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/colors.sh"
source "$SCRIPT_DIR/argocd-utils.sh"

# Show current status
print_info "ArgoCD Applications Status:"
echo "----------------------------------------"
kubectl get applications -n argocd -o custom-columns="NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status" --no-headers | \
while read name sync health; do
    if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
        print_success "$name: $sync/$health"
    elif [ "$health" = "Healthy" ]; then
        print_warning "$name: $sync/$health"
    else
        print_error "$name: $sync/$health"
    fi
done
echo "----------------------------------------"
echo ""

# Check for pods in CrashLoopBackOff that need restart across all clusters
print_info "Checking for pods in CrashLoopBackOff across all clusters..."
for context in $(kubectl config get-contexts -o name 2>/dev/null | grep -E "peeks-(hub|spoke)"); do
    cluster_name=$(echo "$context" | sed 's/.*peeks-/peeks-/')
    crashloop_pods=$(kubectl get pods -A --context "$context" -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.containerStatuses[]? | select(.state.waiting.reason == "CrashLoopBackOff" and .restartCount > 50)) | "\(.metadata.namespace)/\(.metadata.name)"' 2>/dev/null || echo "")
    
    if [ -n "$crashloop_pods" ]; then
        print_warning "Found pods in CrashLoopBackOff (>50 restarts) in $cluster_name:"
        echo "$crashloop_pods" | while read pod; do
            if [ -n "$pod" ]; then
                namespace="${pod%%/*}"
                podname="${pod##*/}"
                echo "  → Restarting pod: $podname in namespace $namespace"
                kubectl delete pod "$podname" -n "$namespace" --context "$context" 2>/dev/null || echo "    ⚠ Failed to delete pod"
            fi
        done
    fi
done
echo ""

# Find stuck apps with their status (including revision conflicts and stale finished operations)
stuck_apps_time=$(kubectl get applications -n argocd -o json 2>/dev/null | \
    jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '.items[] | select(
        ((.status.operationState.phase == "Running") or (.status.health.status == "Progressing")) and 
        ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)
    ) | "\(.metadata.name)|\(.status.health.status // "Unknown")|\(.status.sync.status // "Unknown")|\(.status.operationState.phase // "None")|\(.status.operationState.finishedAt // "none")"' 2>/dev/null || echo "")

stuck_apps_revision=$(kubectl get applications -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(
        ((.status.operationState.message // "") | contains("ComparisonError") or contains("cannot reference a different revision")) or
        ((.status.conditions[]?.message // "") | contains("ComparisonError") or contains("cannot reference a different revision"))
    ) | "\(.metadata.name)|\(.status.health.status // "Unknown")|\(.status.sync.status // "Unknown")|\(.status.operationState.phase // "None")|\(.status.operationState.finishedAt // "none")"' 2>/dev/null || echo "")

stuck_apps_crd_annotations=$(kubectl get applications -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(
        ((.status.operationState.message // "") | contains("Too long: may not be more than 262144 bytes")) or
        ((.status.conditions[]?.message // "") | contains("Too long: may not be more than 262144 bytes"))
    ) | "\(.metadata.name)|\(.status.health.status // "Unknown")|\(.status.sync.status // "Unknown")|\(.status.operationState.phase // "None")|\(.status.operationState.finishedAt // "none")|crd-annotations"' 2>/dev/null || echo "")

stuck_apps_degraded=$(kubectl get applications -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(.status.sync.status == "Synced" and .status.health.status == "Degraded") | "\(.metadata.name)|\(.status.health.status)|\(.status.sync.status)|None|none|degraded"' 2>/dev/null || echo "")

stuck_apps=$(echo -e "$stuck_apps_time\n$stuck_apps_revision\n$stuck_apps_crd_annotations\n$stuck_apps_degraded" | grep -v '^$' | sort -u)

total_apps=$(kubectl get applications -n argocd --no-headers 2>/dev/null | wc -l)
healthy_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | jq '[.items[] | select(.status.health.status == "Healthy" and .status.sync.status == "Synced")] | length')

if [ -z "$stuck_apps" ]; then
    if [ "$healthy_apps" -eq "$total_apps" ]; then
        print_success "All $total_apps applications are currently healthy!"
    else
        print_warning "$healthy_apps/$total_apps applications are healthy. No stuck operations found (>5min)."
    fi
    exit 0
fi

print_warning "Found stuck applications (>5min) or revision conflicts:"
echo "$stuck_apps" | while IFS='|' read -r app health sync phase finished; do
    [ -n "$app" ] && echo "  - $app (health=$health, sync=$sync, phase=$phase, finished=$finished)"
done

echo ""
print_info "Recovering stuck applications..."

# Infrastructure Verification
echo ""
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "Phase 1: Infrastructure Verification"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
get_infrastructure_report

# Sync Timeout Detection (>15 minutes)
echo ""
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "Phase 2: Sync Timeout Detection (>15 minutes)"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

timeout_apps=$(detect_sync_timeout_pattern 900)

if [ -n "$timeout_apps" ]; then
    print_warning "Found applications with sync timeout pattern:"
    echo "$timeout_apps" | while IFS='|' read -r app duration message resources; do
        if [ -n "$app" ]; then
            duration_min=$((duration / 60))
            retry_count=$(echo "$message" | grep -oP 'attempt #\K\d+' || echo "unknown")
            print_error "  $app: ${duration_min}m (retry #${retry_count})"
            [ -n "$resources" ] && print_info "    OutOfSync resources: $resources"
            
            # Aggressive recovery for timeout apps
            print_info "    → Terminating stuck operation..."
            terminate_argocd_operation "$app"
            sleep 2
            
            print_info "    → Forcing hard refresh..."
            kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
            sleep 3
            
            print_info "    → Syncing application..."
            sync_argocd_app "$app"
            sleep 2
        fi
    done
else
    print_success "No applications with sync timeout pattern found"
fi

# Workflow Dependency Check
echo ""
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "Phase 3: Workflow Dependency Check"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check apps with workflows (devlake, etc.)
workflow_namespaces="devlake"

for ns in $workflow_namespaces; do
    if verify_namespace_exists "$ns" >/dev/null 2>&1; then
        print_info "Checking namespace: $ns"
        verify_kubevela_dependencies "$ns" || true
        
        # Detect null-phase workflows
        null_workflows=$(detect_null_phase_workflows "$ns" 2>/dev/null || echo "")
        
        if [ -n "$null_workflows" ]; then
            echo "$null_workflows" | while IFS='|' read -r wf_name created_at; do
                if [ -n "$wf_name" ]; then
                    print_warning "  Found null-phase workflow: $wf_name (created: $created_at)"
                    trigger_workflow_manually "$wf_name" "$ns" || true
                fi
            done
        else
            print_success "  No null-phase workflows found in $ns"
        fi
    fi
done

# Phase 3.5: Keycloak Secret Verification
echo ""
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "Phase 3.5: Keycloak Secret Verification"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if verify_keycloak_secrets; then
    refresh_keycloak_dependent_apps
else
    print_warning "Keycloak secrets verification failed - dependent apps may remain unhealthy"
fi

# Existing recovery logic
echo ""
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "Phase 4: Standard Recovery (CRD, Revision, Degraded)"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "$stuck_apps" | while IFS='|' read -r app health sync phase finished issue_type; do
    if [ -n "$app" ]; then
        # Handle degraded applications
        if [ "$issue_type" = "degraded" ]; then
            echo "  → Refreshing degraded application: $app"
            kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
            sleep 2
            sync_argocd_app "$app"
            continue
        fi
        
        # Handle CRD annotation size limit issues
        if [ "$issue_type" = "crd-annotations" ]; then
            echo "  → Fixing CRD annotation size limit for: $app"
            
            # Extract CRD names from error message
            error_msg=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
                jq -r '.status.operationState.message // .status.conditions[]?.message // ""')
            
            # Find all CRDs mentioned in the error
            crds=$(echo "$error_msg" | grep -oP 'CustomResourceDefinition\.apiextensions\.k8s\.io "\K[^"]+' | sort -u)
            
            if [ -n "$crds" ]; then
                echo "$crds" | while read -r crd; do
                    echo "    → Removing last-applied-configuration from: $crd"
                    kubectl annotate crd "$crd" kubectl.kubernetes.io/last-applied-configuration- 2>/dev/null || true
                done
                
                # Force hard refresh to retry sync
                kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
                kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status"}]' 2>/dev/null || true
                kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite || echo "    ⚠ Failed to add hard refresh annotation"
            else
                echo "    ⚠ Could not extract CRD names from error message"
            fi
            continue
        fi
        
        # Check if operation already finished (stale state)
        if [ "$finished" != "none" ]; then
            echo "  → Clearing stale operation state for: $app (finished at $finished)"
            kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
            kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status"}]' 2>/dev/null || true
            kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite || echo "    ⚠ Failed to add hard refresh annotation"
            continue
        fi
        
        # Check if this is a revision conflict
        revision_conflict=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
            jq -r '(.status.operationState.message // .status.conditions[]?.message // "") | contains("cannot reference a different revision")')
        
        if [ "$revision_conflict" = "true" ]; then
            echo "  → Fixing revision conflict for: $app"
            # Clear operation and status
            kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
            kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status"}]' 2>/dev/null || true
            # Force hard refresh
            kubectl patch application "$app" -n argocd --type merge -p='{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}' 2>/dev/null || true
        else
            echo "  → Terminating operation for: $app"
            terminate_argocd_operation "$app"
            kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
            sleep 2
            echo "  → Syncing: $app"
            sync_argocd_app "$app"
        fi
        sleep 1
    fi
done

echo ""
print_success "Recovery complete. Run again to verify all apps are healthy."

echo ""
generate_dependency_report

echo ""
print_info "Final Application Status:"
echo "----------------------------------------"
kubectl get applications -n argocd -o json | jq -r '.items[] | "\(.metadata.name)|\(.status.sync.status // "Unknown")|\(.status.health.status // "Unknown")|\(.status.operationState.message // .status.conditions[]?.message // "" | gsub("\n"; " "))"' | \
while IFS='|' read -r name sync health message; do
    # Determine issue category for reporting
    issue_cat=""
    if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
        print_success "$name: OK"
    else
        # Categorize the issue
        if echo "$message" | grep -q "controller sync timeout"; then
            issue_cat="[Sync Timeout]"
        elif echo "$message" | grep -q "Too long: may not be more than 262144 bytes"; then
            issue_cat="[CRD Size]"
        elif echo "$message" | grep -q "cannot reference a different revision"; then
            issue_cat="[Revision Conflict]"
        elif echo "$message" | grep -q "waiting for healthy state.*Workflow"; then
            issue_cat="[Workflow Dep]"
        elif [ "$health" = "Degraded" ]; then
            issue_cat="[Degraded]"
        elif [ "$health" = "Missing" ]; then
            issue_cat="[Missing]"
        else
            issue_cat="[Unknown]"
        fi
        
        # Extract key error message
        error_msg=$(echo "$message" | sed -n 's/.*\(Resource count [0-9]* exceeds limit of [0-9]*\).*/\1/p')
        if [ -z "$error_msg" ]; then
            error_msg=$(echo "$message" | sed -n 's/.*ComparisonError: \(.*\)/\1/p' | head -c 80)
        fi
        if [ -z "$error_msg" ] && [ -n "$message" ]; then
            error_msg=$(echo "$message" | head -c 80)
        fi
        if [ -n "$error_msg" ]; then
            print_error "$name: KO $issue_cat - $error_msg"
        else
            print_error "$name: KO $issue_cat - $sync/$health"
        fi
    fi
done
echo "----------------------------------------"
