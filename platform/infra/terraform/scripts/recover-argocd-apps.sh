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
        echo "  → Terminating operation for: $app"
        terminate_argocd_operation "$app"
        kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
        sleep 2
        echo "  → Syncing: $app"
        sync_argocd_app "$app"
        sleep 1
    fi
done

echo ""
print_success "Recovery complete. Run again to verify all apps are healthy."
