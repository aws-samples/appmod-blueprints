#!/bin/bash
set -e

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

# Find stuck apps with their status (including revision conflicts)
stuck_apps_time=$(kubectl get applications -n argocd -o json 2>/dev/null | \
    jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '.items[] | select(
        ((.status.operationState.phase == "Running") or (.status.health.status == "Progressing")) and 
        ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)
    ) | "\(.metadata.name)|\(.status.health.status // "Unknown")|\(.status.sync.status // "Unknown")|\(.status.operationState.phase // "None")"' 2>/dev/null || echo "")

stuck_apps_revision=$(kubectl get applications -n argocd -o json 2>/dev/null | \
    jq -r '.items[] | select(
        (.status.operationState.message // "") | contains("ComparisonError") or contains("cannot reference a different revision")
    ) | "\(.metadata.name)|\(.status.health.status // "Unknown")|\(.status.sync.status // "Unknown")|\(.status.operationState.phase // "None")"' 2>/dev/null || echo "")

stuck_apps=$(echo -e "$stuck_apps_time\n$stuck_apps_revision" | grep -v '^$' | sort -u)

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
echo "$stuck_apps" | while IFS='|' read -r app health sync phase; do
    [ -n "$app" ] && echo "  - $app (health=$health, sync=$sync, phase=$phase)"
done

echo ""
print_info "Recovering stuck applications..."

echo "$stuck_apps" | while IFS='|' read -r app health sync phase; do
    if [ -n "$app" ]; then
        # Check if this is a revision conflict
        revision_conflict=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
            jq -r '.status.operationState.message // "" | contains("cannot reference a different revision")')
        
        if [ "$revision_conflict" = "true" ]; then
            echo "  → Fixing revision conflict for: $app"
            # Clear the stuck operation first
            kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
            kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
            # Force refresh
            kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
            sleep 2
            # Trigger fresh sync
            kubectl patch application "$app" -n argocd --type='merge' -p='{"operation":{"sync":{"syncOptions":["CreateNamespace=true","ServerSideApply=true"]}}}' 2>/dev/null || true
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
