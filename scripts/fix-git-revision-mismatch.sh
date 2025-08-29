#!/bin/bash

# fix-git-revision-mismatch.sh
# UPDATED: Comprehensive fix based on proven successful approach
# Script to fix Git revision mismatch issues using the method that actually works
# Usage: ./fix-git-revision-mismatch.sh [app-name] [namespace]

set -e

APP_NAME=${1:-}
NAMESPACE=${2:-argocd}
DRY_RUN=${DRY_RUN:-false}

echo "🔧 ArgoCD Git Revision Mismatch Fixer (COMPREHENSIVE)"
echo "===================================================="
echo "Namespace: $NAMESPACE"
echo "Timestamp: $(date)"
echo ""
echo "⚠️  This script uses the PROVEN comprehensive approach:"
echo "   1. Delete and recreate stuck applications"
echo "   2. Restart ArgoCD repo server to clear Git cache"
echo "   3. Wait for stabilization (avoid Git commits!)"
echo "   4. Monitor for successful completion"
echo ""

# Function to check dependencies
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

# Function to detect revision mismatch
has_revision_mismatch() {
    local app_name=$1
    local status_message
    
    status_message=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.message // ""')
    
    if [[ "$status_message" == *"cannot reference a different revision of the same repository"* ]]; then
        return 0  # Has mismatch
    else
        return 1  # No mismatch
    fi
}

# Function to check if stuck in retry loop
is_stuck_in_retry_loop() {
    local app_name=$1
    local retry_count
    
    retry_count=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.retryCount // 0')
    
    if [[ "$retry_count" -gt 10 ]]; then
        return 0  # Stuck
    else
        return 1  # Not stuck
    fi
}

# Function to restart ArgoCD repo server
restart_repo_server() {
    echo "🔄 Restarting ArgoCD repo server to clear Git cache..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY RUN] Would restart ArgoCD repo server"
        return 0
    fi
    
    local repo_pods
    repo_pods=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=argocd-repo-server -o name 2>/dev/null)
    
    if [[ -z "$repo_pods" ]]; then
        echo "   ⚠️  No ArgoCD repo server pods found"
        return 1
    fi
    
    echo "   🗑️  Deleting repo server pods..."
    kubectl delete $repo_pods -n "$NAMESPACE"
    
    echo "   ⏳ Waiting for repo server to restart..."
    kubectl wait --for=condition=Ready pods -l app.kubernetes.io/name=argocd-repo-server -n "$NAMESPACE" --timeout=120s || {
        echo "   ⚠️  Timeout waiting for repo server, continuing anyway..."
    }
    
    echo "   ✅ ArgoCD repo server restart completed"
    return 0
}

# Function to comprehensive fix (the method that actually works)
comprehensive_fix() {
    local app_name=$1
    
    echo "🔧 COMPREHENSIVE FIX for: $app_name"
    echo "=================================="
    
    # Check if application exists
    if ! kubectl get application "$app_name" -n "$NAMESPACE" &>/dev/null; then
        echo "❌ Application '$app_name' not found in namespace '$NAMESPACE'"
        return 1
    fi
    
    # Show current status
    local has_mismatch=false
    local is_stuck=false
    
    if has_revision_mismatch "$app_name"; then
        has_mismatch=true
        echo "🚨 Git revision mismatch detected"
    fi
    
    if is_stuck_in_retry_loop "$app_name"; then
        is_stuck=true
        local retry_count
        retry_count=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json | jq -r '.status.operationState.retryCount // 0')
        echo "🔄 Application stuck in retry loop (attempt #$retry_count)"
    fi
    
    # Step 1: Backup application spec
    echo ""
    echo "📋 Step 1: Backing up application spec..."
    local backup_file="/tmp/${app_name}-backup-$(date +%s).yaml"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY RUN] Would backup to: $backup_file"
    else
        kubectl get application "$app_name" -n "$NAMESPACE" -o yaml > "$backup_file"
        echo "   ✅ Backed up to: $backup_file"
    fi
    
    # Step 2: Delete stuck application
    echo ""
    echo "🗑️  Step 2: Deleting stuck application..."
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY RUN] Would delete application $app_name"
    else
        kubectl delete application "$app_name" -n "$NAMESPACE"
        echo "   ✅ Application deleted"
    fi
    
    # Step 3: Restart repo server
    echo ""
    echo "🔄 Step 3: Restarting ArgoCD repo server..."
    restart_repo_server
    
    # Step 4: Wait for cleanup
    echo ""
    echo "⏳ Step 4: Waiting for cleanup..."
    if [[ "$DRY_RUN" != "true" ]]; then
        sleep 15
    else
        echo "   [DRY RUN] Would wait 15 seconds"
    fi
    
    # Step 5: Recreate application
    echo ""
    echo "🔨 Step 5: Recreating application..."
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY RUN] Would recreate from $backup_file"
    else
        kubectl apply -f "$backup_file"
        echo "   ✅ Application recreated"
    fi
    
    # Step 6: Wait for stabilization
    echo ""
    echo "⏳ Step 6: Waiting for stabilization..."
    echo "   ⚠️  CRITICAL: Do NOT make Git commits during this time!"
    if [[ "$DRY_RUN" != "true" ]]; then
        sleep 30
    else
        echo "   [DRY RUN] Would wait 30 seconds"
    fi
    
    # Step 7: Monitor progress
    echo ""
    echo "👀 Step 7: Monitoring progress..."
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY RUN] Would monitor application progress"
        return 0
    fi
    
    local max_wait=300  # 5 minutes
    local wait_time=0
    
    while [[ $wait_time -lt $max_wait ]]; do
        local phase
        phase=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.phase // "Unknown"')
        local message
        message=$(kubectl get application "$app_name" -n "$NAMESPACE" -o json 2>/dev/null | jq -r '.status.operationState.message // "No message"' | head -1)
        
        echo "   Monitor: Phase=$phase"
        
        # Check for revision mismatch
        if [[ "$message" == *"cannot reference a different revision"* ]]; then
            echo "   ⚠️  Still resolving revision mismatch (this is normal initially)"
            echo "   💡 IMPORTANT: Avoid Git commits until this resolves!"
        elif [[ "$message" == *"waiting for completion of hook"* ]]; then
            echo "   🎯 PostSync hook running - excellent progress!"
        fi
        
        case "$phase" in
            "Succeeded")
                echo "   ✅ Sync completed successfully!"
                return 0
                ;;
            "Failed")
                echo "   ❌ Sync failed: $message"
                return 1
                ;;
        esac
        
        sleep 30
        wait_time=$((wait_time + 30))
    done
    
    echo "   ⏰ Timeout, but application may still be progressing"
    return 1
}

# Function to fix all problematic applications
fix_all_apps() {
    echo "🔍 Scanning for applications with issues..."
    
    local apps_with_issues=()
    local apps
    apps=$(kubectl get applications -n "$NAMESPACE" -o json | jq -r '.items[].metadata.name' 2>/dev/null)
    
    if [[ -z "$apps" ]]; then
        echo "❌ No applications found in namespace '$NAMESPACE'"
        exit 1
    fi
    
    # Find problematic applications
    for app in $apps; do
        if has_revision_mismatch "$app" || is_stuck_in_retry_loop "$app"; then
            apps_with_issues+=("$app")
            echo "   🚨 Found issue in: $app"
        fi
    done
    
    if [[ ${#apps_with_issues[@]} -eq 0 ]]; then
        echo "✅ No applications with issues found!"
        exit 0
    fi
    
    echo ""
    echo "📋 Found ${#apps_with_issues[@]} application(s) with issues:"
    printf '   - %s\n' "${apps_with_issues[@]}"
    echo ""
    
    if [[ "$DRY_RUN" != "true" ]]; then
        echo "⚠️  WARNING: This will delete and recreate applications!"
        echo "⚠️  WARNING: Do NOT make Git commits during this process!"
        echo ""
        read -p "🤔 Proceed with comprehensive fix? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "❌ Operation cancelled"
            exit 0
        fi
    fi
    
    # Fix each application
    local fixed_count=0
    local failed_count=0
    
    for app in "${apps_with_issues[@]}"; do
        echo ""
        if comprehensive_fix "$app"; then
            fixed_count=$((fixed_count + 1))
            echo "   🎉 Successfully fixed $app"
        else
            failed_count=$((failed_count + 1))
            echo "   ⚠️  $app may need manual attention"
        fi
    done
    
    # Summary
    echo ""
    echo "📊 COMPREHENSIVE FIX SUMMARY"
    echo "============================"
    echo "Applications processed: ${#apps_with_issues[@]}"
    echo "Successfully fixed: $fixed_count"
    echo "Failed or need attention: $failed_count"
    echo ""
    echo "💡 KEY LESSON: Avoid Git commits during ArgoCD sync operations!"
    
    if [[ $failed_count -gt 0 ]]; then
        exit 1
    else
        echo "🎉 All applications fixed successfully!"
        exit 0
    fi
}

# Function to fix single application
fix_single_app() {
    local app_name=$1
    
    echo "🔍 Checking application: $app_name"
    
    if ! kubectl get application "$app_name" -n "$NAMESPACE" &>/dev/null; then
        echo "❌ Application '$app_name' not found in namespace '$NAMESPACE'"
        exit 1
    fi
    
    echo ""
    if comprehensive_fix "$app_name"; then
        echo ""
        echo "🎉 Comprehensive fix completed for $app_name"
        echo "💡 Remember: Avoid Git commits during ArgoCD operations!"
    else
        echo ""
        echo "❌ Fix may need more time or manual intervention"
        exit 1
    fi
}

# Help function
show_help() {
    echo "ArgoCD Git Revision Mismatch Fixer (COMPREHENSIVE)"
    echo ""
    echo "Uses the PROVEN method that actually works:"
    echo "1. Delete and recreate stuck applications"
    echo "2. Restart ArgoCD repo server (clear Git cache)"
    echo "3. Wait for stabilization (no Git commits!)"
    echo "4. Monitor for successful completion"
    echo ""
    echo "Usage: $0 [OPTIONS] [APP_NAME] [NAMESPACE]"
    echo ""
    echo "OPTIONS:"
    echo "  -h, --help     Show this help"
    echo "  --dry-run      Show what would be done"
    echo ""
    echo "Examples:"
    echo "  $0                           # Fix all problematic apps"
    echo "  $0 my-app                    # Fix specific app"
    echo "  $0 --dry-run                 # Dry-run mode"
    echo ""
    echo "⚠️  CRITICAL: Do NOT make Git commits while this runs!"
}

# Main function
main() {
    check_dependencies
    
    if [[ -n "$APP_NAME" ]]; then
        fix_single_app "$APP_NAME"
    else
        fix_all_apps
    fi
}

# Parse arguments
case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    --dry-run)
        DRY_RUN=true
        APP_NAME=${2:-}
        NAMESPACE=${3:-argocd}
        main
        ;;
    *)
        main "$@"
        ;;
esac
