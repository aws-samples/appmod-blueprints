#!/bin/bash
# argocd-sync — Force refresh and recover ArgoCD applications
# Usage: ./scripts/argocd-sync.sh [app-name]
#   No args: refresh all apps
#   With arg: refresh specific app

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
print_info() { echo -e "${CYAN}▸ $*${NC}"; }
print_ok() { echo -e "${GREEN}✓ $*${NC}"; }
print_warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
print_err() { echo -e "${RED}✗ $*${NC}"; }

APP_NAME="${1:-}"

if [ -n "$APP_NAME" ]; then
  print_info "Hard-refreshing app: $APP_NAME"
  kubectl annotate applications.argoproj.io "$APP_NAME" -n argocd argocd.argoproj.io/refresh=hard --overwrite
  sleep 5
  STATUS=$(kubectl get applications.argoproj.io "$APP_NAME" -n argocd -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null)
  echo "  $APP_NAME: $STATUS"
  exit 0
fi

print_info "Hard-refreshing all applications..."
for app in $(kubectl get applications.argoproj.io -n argocd -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
  kubectl annotate applications.argoproj.io "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
done

print_info "Checking for stuck apps (OutOfSync/Error > 5 min)..."
sleep 10

# Find and retry stuck apps
STUCK=$(kubectl get applications.argoproj.io -n argocd -o json 2>/dev/null | \
  jq -r '.items[] | select(.status.sync.status != "Synced" or .status.health.status == "Degraded") | .metadata.name' 2>/dev/null || echo "")

if [ -n "$STUCK" ]; then
  print_warn "Stuck apps found:"
  for app in $STUCK; do
    MSG=$(kubectl get applications.argoproj.io "$app" -n argocd -o jsonpath='{.status.operationState.message}' 2>/dev/null | head -c 100)
    echo "  - $app: $MSG"
  done
fi

echo ""
print_info "Final status:"
echo "----------------------------------------"
kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null | while read -r name sync health rest; do
  if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ]; then
    print_ok "$name"
  else
    print_err "$name: $sync/$health"
  fi
done
echo "----------------------------------------"
TOTAL=$(kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null | wc -l)
HEALTHY=$(kubectl get applications.argoproj.io -n argocd --no-headers 2>/dev/null | awk '$2=="Synced" && $3=="Healthy"' | wc -l)
echo -e "${CYAN}$HEALTHY/$TOTAL apps Synced/Healthy${NC}"
