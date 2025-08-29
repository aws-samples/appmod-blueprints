#!/bin/bash

# detect-git-revision-mismatch.sh
# Script to detect Git revision mismatch issues in ArgoCD applications
# Usage: ./detect-git-revision-mismatch.sh [namespace]

set -e

NAMESPACE=${1:-argocd}
FOUND_ISSUES=0

echo "🔍 ArgoCD Git Revision Mismatch Detector"
echo "========================================"
echo "Namespace: $NAMESPACE"
echo "Timestamp: $(date)"
echo ""

# Function to check if kubectl and jq are available
check_dependencies() {
    if ! command -v kubectl &> /dev/null; then
        echo "❌ Error: kubectl is not installed or not in PATH"
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        echo "❌ Error: jq is not installed or not in PATH"
        exit 1
    fi
}

# Function to detect revision mismatch in application status
detect_revision_mismatch() {
    local app_name=$1
    local status_message
    
    status_message=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.message // ""')
    
    if [[ "$status_message" == *"cannot reference a different revision of the same repository"* ]]; then
        return 0  # Found mismatch
    else
        return 1  # No mismatch
    fi
}

# Function to extract revision details from error message
extract_revision_details() {
    local app_name=$1
    local message
    
    message=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json | jq -r '.status.operationState.message // ""')
    
    # Extract the two different revisions from the error message
    local values_revision=$(echo "$message" | grep -oP '\$values references "[^"]*" which resolves to "\K[^"]*' || echo "unknown")
    local app_revision=$(echo "$message" | grep -oP 'application references "[^"]*" which resolves to "\K[^"]*' || echo "unknown")
    
    echo "    💥 Revision Conflict Details:"
    echo "       \$values source resolves to: ${values_revision:0:8}..."
    echo "       Application source resolves to: ${app_revision:0:8}..."
    
    # Try to extract retry count
    local retry_count=$(echo "$message" | grep -oP 'Retrying attempt #\K\d+' || echo "unknown")
    if [[ "$retry_count" != "unknown" ]]; then
        echo "       Retry attempts: #$retry_count"
    fi
}

# Function to get application sync status
get_app_sync_status() {
    local app_name=$1
    
    kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '{
        syncStatus: .status.sync.status,
        healthStatus: .status.health.status,
        operationPhase: .status.operationState.phase,
        repoURL: .spec.sources[0].repoURL,
        targetRevision: .spec.sources[0].targetRevision
    }'
}

# Function to check for multi-source applications
is_multi_source_app() {
    local app_name=$1
    local source_count
    
    source_count=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq '.spec.sources | length' 2>/dev/null || echo "0")
    
    if [[ "$source_count" -gt 1 ]]; then
        return 0  # Is multi-source
    else
        return 1  # Not multi-source
    fi
}

# Main detection logic
main() {
    check_dependencies
    
    echo "📋 Scanning ArgoCD Applications..."
    echo ""
    
    # Get all applications
    local apps
    apps=$(kubectl get applications -n "$NAMESPACE" -o json | jq -r '.items[].metadata.name' 2>/dev/null)
    
    if [[ -z "$apps" ]]; then
        echo "❌ No applications found in namespace '$NAMESPACE'"
        exit 1
    fi
    
    local total_apps=0
    local mismatch_apps=0
    local multi_source_apps=0
    
    for app in $apps; do
        total_apps=$((total_apps + 1))
        
        echo "🔍 Checking: $app"
        
        # Check if it's a multi-source application
        if is_multi_source_app "$app"; then
            multi_source_apps=$((multi_source_apps + 1))
            echo "    📦 Multi-source application detected"
        fi
        
        # Check for revision mismatch
        if detect_revision_mismatch "$app"; then
            mismatch_apps=$((mismatch_apps + 1))
            FOUND_ISSUES=1
            
            echo "    ❌ GIT REVISION MISMATCH DETECTED!"
            extract_revision_details "$app"
            
            # Get current sync status
            echo "    📊 Current Status:"
            get_app_sync_status "$app" | jq -r 'to_entries[] | "       \(.key): \(.value)"'
            
        else
            # Check if application has other sync issues
            local sync_status
            sync_status=$(kubectl get application "$app" -n "$NAMESPACE" -o json | jq -r '.status.sync.status // "Unknown"')
            local health_status
            health_status=$(kubectl get application "$app" -n "$NAMESPACE" -o json | jq -r '.status.health.status // "Unknown"')
            
            if [[ "$sync_status" != "Synced" ]] || [[ "$health_status" != "Healthy" ]]; then
                echo "    ⚠️  Sync Status: $sync_status, Health: $health_status"
            else
                echo "    ✅ Healthy"
            fi
        fi
        
        echo ""
    done
    
    # Summary
    echo "📊 DETECTION SUMMARY"
    echo "==================="
    echo "Total applications scanned: $total_apps"
    echo "Multi-source applications: $multi_source_apps"
    echo "Applications with revision mismatch: $mismatch_apps"
    echo ""
    
    if [[ $FOUND_ISSUES -eq 1 ]]; then
        echo "🚨 GIT REVISION MISMATCH ISSUES FOUND!"
        echo ""
        echo "💡 To fix these issues, run:"
        echo "   ./scripts/fix-git-revision-mismatch.sh"
        echo ""
        echo "🔧 Or fix individual applications:"
        echo "   ./scripts/fix-git-revision-mismatch.sh <app-name>"
        
        exit 1
    else
        echo "✅ No Git revision mismatch issues detected!"
        exit 0
    fi
}

# Help function
show_help() {
    echo "ArgoCD Git Revision Mismatch Detector"
    echo ""
    echo "Usage: $0 [OPTIONS] [NAMESPACE]"
    echo ""
    echo "OPTIONS:"
    echo "  -h, --help     Show this help message"
    echo ""
    echo "ARGUMENTS:"
    echo "  NAMESPACE      ArgoCD namespace (default: argocd)"
    echo ""
    echo "Examples:"
    echo "  $0                    # Scan applications in 'argocd' namespace"
    echo "  $0 argocd-system     # Scan applications in 'argocd-system' namespace"
    echo ""
    echo "This script detects Git revision mismatch issues that can occur when:"
    echo "- Multi-source applications reference the same Git repository"
    echo "- Git commits are pushed during active ArgoCD sync operations"
    echo "- ArgoCD cache becomes inconsistent between different sources"
}

# Parse command line arguments
case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    *)
        main "$@"
        ;;
esac
