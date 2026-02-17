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

stuck_apps=$(echo -e "$stuck_apps_time\n$stuck_apps_revision\n$stuck_apps_crd_annotations" | grep -v '^$' | sort -u)

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

echo "$stuck_apps" | while IFS='|' read -r app health sync phase finished issue_type; do
    if [ -n "$app" ]; then
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
print_info "Final Application Status:"
echo "----------------------------------------"
kubectl get applications -n argocd -o json | jq -r '.items[] | "\(.metadata.name)|\(.status.sync.status // "Unknown")|\(.status.health.status // "Unknown")|\(.status.operationState.message // .status.conditions[]?.message // "" | gsub("\n"; " "))"' | \
while IFS='|' read -r name sync health message; do
    if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
        print_success "$name: OK"
    else
        # Extract key error message
        error_msg=$(echo "$message" | sed -n 's/.*\(Resource count [0-9]* exceeds limit of [0-9]*\).*/\1/p')
        if [ -z "$error_msg" ]; then
            error_msg=$(echo "$message" | sed -n 's/.*ComparisonError: \(.*\)/\1/p' | head -c 80)
        fi
        if [ -z "$error_msg" ] && [ -n "$message" ]; then
            error_msg=$(echo "$message" | head -c 80)
        fi
        if [ -n "$error_msg" ]; then
            print_error "$name: KO - $error_msg"
        else
            print_error "$name: KO - $sync/$health"
        fi
    fi
done
echo "----------------------------------------"
