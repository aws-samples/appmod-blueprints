#!/bin/bash

# Robust ArgoCD utility functions

export CORE_APPS=(
    "external-secrets"
    "argocd"
    "gitlab"
)

export BOOTSTRAP_APPS=(
    "bootstrap"
    "cluster-addons"
    "clusters"
    "fleet-secrets"
)

# Infrastructure Verification Functions

# Verify cluster infrastructure health
verify_cluster_infrastructure() {
    local status=0
    
    print_info "Verifying cluster infrastructure..."
    
    # Check nodes
    local node_count=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    local ready_nodes=$(kubectl get nodes --no-headers 2>/dev/null | grep -c " Ready " || echo "0")
    
    if [ "$node_count" -eq 0 ]; then
        print_error "No nodes found in cluster"
        return 2
    elif [ "$ready_nodes" -lt "$node_count" ]; then
        print_warning "Nodes: $ready_nodes/$node_count ready"
        status=1
    else
        print_success "Nodes: $ready_nodes/$node_count ready"
    fi
    
    # Check node capacity
    local allocatable_pods=$(kubectl get nodes -o json 2>/dev/null | jq -r '[.items[].status.allocatable.pods | tonumber] | add' 2>/dev/null || echo "0")
    local current_pods=$(kubectl get pods -A --no-headers 2>/dev/null | wc -l)
    
    if [ "$allocatable_pods" -gt 0 ]; then
        local pod_usage=$((current_pods * 100 / allocatable_pods))
        if [ "$pod_usage" -gt 90 ]; then
            print_warning "Pod capacity: $current_pods/$allocatable_pods (${pod_usage}% - high utilization)"
            status=1
        else
            print_info "Pod capacity: $current_pods/$allocatable_pods (${pod_usage}%)"
        fi
    fi
    
    return $status
}

# Verify namespace exists and is active
verify_namespace_exists() {
    local namespace=$1
    
    if [ -z "$namespace" ]; then
        return 1
    fi
    
    local ns_status=$(kubectl get namespace "$namespace" -o jsonpath='{.status.phase}' 2>/dev/null)
    
    if [ -z "$ns_status" ]; then
        print_warning "Namespace $namespace does not exist"
        return 2
    elif [ "$ns_status" != "Active" ]; then
        print_warning "Namespace $namespace is in $ns_status phase"
        return 1
    fi
    
    return 0
}

# Verify operator health
verify_operator_health() {
    local operator=$1
    local namespace=$2
    local label_selector=$3
    
    if ! verify_namespace_exists "$namespace" 2>/dev/null; then
        print_warning "Operator $operator: namespace $namespace not found"
        return 2
    fi
    
    local pods=$(kubectl get pods -n "$namespace" -l "$label_selector" --no-headers 2>/dev/null || echo "")
    
    if [ -z "$pods" ]; then
        print_warning "Operator $operator: no pods found"
        return 2
    fi
    
    local total=$(echo "$pods" | wc -l)
    local running=$(echo "$pods" | grep -c "Running" 2>/dev/null || echo "0")
    local completed=$(echo "$pods" | grep -c "Completed" 2>/dev/null || echo "0")
    
    # Ensure numeric values
    running=$(echo "$running" | tr -d '[:space:]')
    completed=$(echo "$completed" | tr -d '[:space:]')
    total=$(echo "$total" | tr -d '[:space:]')
    
    local healthy=$((running + completed))
    
    if [ "$running" -eq 0 ] && [ "$completed" -eq 0 ]; then
        print_error "Operator $operator: 0/$total pods running or completed"
        return 2
    elif [ "$healthy" -lt "$total" ]; then
        local unhealthy=$((total - healthy))
        print_warning "Operator $operator: $running running, $completed completed, $unhealthy unhealthy"
        return 1
    else
        if [ "$completed" -gt 0 ]; then
            print_success "Operator $operator: $running running, $completed completed"
        else
            print_success "Operator $operator: $running/$total pods running"
        fi
    fi
    
    return 0
}

# Generate infrastructure report
get_infrastructure_report() {
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_info "Infrastructure Health Report"
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    verify_cluster_infrastructure || true
    local infra_status=$?
    
    echo ""
    print_info "Operator Health:"
    
    verify_operator_health "KubeVela" "vela-system" "app.kubernetes.io/name=vela-core" || true
    verify_operator_health "Crossplane" "crossplane-system" "app=crossplane" || true
    verify_operator_health "Argo Workflows" "argo" "app in (argo-server,workflow-controller)" || true
    verify_operator_health "Grafana Operator" "grafana-operator" "app.kubernetes.io/name=grafana-operator" || true
    
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    return 0
}

# Generate dependency report with root cause analysis
generate_dependency_report() {
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_info "Dependency Analysis Report"
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Get all apps with sync wave and status
    local apps_data=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | 
        {
            name: .metadata.name,
            wave: (.metadata.annotations."argocd.argoproj.io/sync-wave" // "0"),
            sync: (.status.sync.status // "Unknown"),
            health: (.status.health.status // "Unknown"),
            message: (.status.operationState.message // .status.conditions[]?.message // "")
        } | 
        "\(.wave)|\(.name)|\(.sync)|\(.health)|\(.message)"' 2>/dev/null)
    
    # Group by sync wave
    local waves=$(echo "$apps_data" | cut -d'|' -f1 | sort -n | uniq)
    
    for wave in $waves; do
        local wave_apps=$(echo "$apps_data" | grep "^${wave}|")
        local total=$(echo "$wave_apps" | wc -l)
        local healthy=$(echo "$wave_apps" | grep -c "|Synced|Healthy|" || echo "0")
        
        if [ "$healthy" -eq "$total" ]; then
            print_success "Sync Wave $wave: $healthy/$total healthy"
        else
            print_warning "Sync Wave $wave: $healthy/$total healthy"
            
            # Show unhealthy apps with categorized issues
            echo "$wave_apps" | while IFS='|' read -r w name sync health message; do
                if [ "$sync" != "Synced" ] || [ "$health" != "Healthy" ]; then
                    local issue_category="Unknown"
                    local root_cause=""
                    
                    # Categorize issue
                    if echo "$message" | grep -q "controller sync timeout"; then
                        issue_category="Sync Timeout"
                        root_cause="Application controller timeout (>15min)"
                    elif echo "$message" | grep -q "Too long: may not be more than 262144 bytes"; then
                        issue_category="CRD Annotation Size"
                        root_cause="CRD annotation exceeds 262KB limit"
                    elif echo "$message" | grep -q "cannot reference a different revision"; then
                        issue_category="Revision Conflict"
                        root_cause="Git revision mismatch"
                    elif echo "$message" | grep -q "waiting for healthy state.*Workflow"; then
                        issue_category="Workflow Dependency"
                        root_cause="Workflow not started or incomplete"
                    elif [ "$health" = "Degraded" ] && [ "$sync" = "Synced" ]; then
                        issue_category="Resource Degraded"
                        root_cause="Resources synced but not healthy"
                    elif [ "$health" = "Missing" ]; then
                        issue_category="Resources Missing"
                        root_cause="Expected resources not found"
                    fi
                    
                    print_error "  ├─ $name: $sync/$health"
                    print_info "  │  Category: $issue_category"
                    [ -n "$root_cause" ] && print_info "  │  Root Cause: $root_cause"
                fi
            done
        fi
    done
    
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Verify Keycloak secrets and trigger PostSync if needed
verify_keycloak_secrets() {
    local secret_name="${RESOURCE_PREFIX:-peeks}-hub/keycloak-clients"
    
    print_info "Checking Keycloak secrets..."
    
    # Check AWS Secrets Manager
    if aws secretsmanager describe-secret --secret-id "$secret_name" --region "${AWS_REGION:-us-west-2}" >/dev/null 2>&1; then
        print_success "Keycloak clients secret exists in AWS Secrets Manager"
        return 0
    fi
    
    print_warning "Keycloak clients secret not found: $secret_name"
    
    # Check if config job completed
    local job_status=$(kubectl get job config -n keycloak -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
    
    if [ "$job_status" = "True" ]; then
        print_warning "Config job completed but secret not found - may need manual investigation"
        return 1
    fi
    
    print_info "Triggering Keycloak sync to execute PostSync hooks..."
    
    # Force sync
    kubectl patch application keycloak-peeks-hub -n argocd --type json -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
    sleep 2
    kubectl patch application keycloak-peeks-hub -n argocd --type merge -p='{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
    
    # Wait for job
    local timeout=300
    local elapsed=0
    print_info "Waiting for Keycloak config job to complete (timeout: ${timeout}s)..."
    while [ $elapsed -lt $timeout ]; do
        job_status=$(kubectl get job config -n keycloak -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
        if [ "$job_status" = "True" ]; then
            print_success "Keycloak config job completed"
            sleep 5
            
            # Verify secret created
            if aws secretsmanager describe-secret --secret-id "$secret_name" --region "${AWS_REGION:-us-west-2}" >/dev/null 2>&1; then
                print_success "Keycloak clients secret created successfully"
                return 0
            else
                print_error "Secret still not found after job completion"
                return 1
            fi
        fi
        sleep 10
        elapsed=$((elapsed + 10))
    done
    
    print_error "Timeout waiting for Keycloak config job"
    return 1
}

# Refresh apps that depend on Keycloak secrets
refresh_keycloak_dependent_apps() {
    local dependent_apps="backstage argo-workflows jupyterhub devlake"
    
    print_info "Waiting for ExternalSecrets to sync..."
    
    # Wait for ExternalSecrets to sync (max 60 seconds)
    local timeout=60
    local elapsed=0
    local all_ready=false
    
    while [ $elapsed -lt $timeout ]; do
        all_ready=true
        
        for app in $dependent_apps; do
            # Check if ExternalSecret exists and is ready
            local es_status=$(kubectl get externalsecret -n "$app" -l "app.kubernetes.io/instance=${app}-peeks-hub" \
                -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
            
            if [ -n "$es_status" ]; then
                if echo "$es_status" | grep -q "False"; then
                    all_ready=false
                    break
                fi
            fi
        done
        
        if [ "$all_ready" = true ]; then
            print_success "All ExternalSecrets synced successfully"
            break
        fi
        
        sleep 5
        elapsed=$((elapsed + 5))
    done
    
    if [ "$all_ready" = false ]; then
        print_warning "Some ExternalSecrets still syncing after ${timeout}s, forcing refresh anyway"
    fi
    
    # Now refresh the applications
    print_info "Refreshing apps that depend on Keycloak secrets..."
    
    for app in $dependent_apps; do
        local app_name="${app}-peeks-hub"
        if kubectl get application "$app_name" -n argocd >/dev/null 2>&1; then
            print_info "  Refreshing $app_name..."
            kubectl annotate application "$app_name" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
            sleep 1
        fi
    done
    
    # Give apps a moment to start syncing
    sleep 5
    
    # Trigger sync for apps that are OutOfSync
    print_info "Triggering sync for OutOfSync dependent apps..."
    for app in $dependent_apps; do
        local app_name="${app}-peeks-hub"
        if kubectl get application "$app_name" -n argocd >/dev/null 2>&1; then
            local sync_status=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.sync.status}' 2>/dev/null)
            if [ "$sync_status" = "OutOfSync" ]; then
                print_info "  Syncing $app_name..."
                sync_argocd_app "$app_name" || true
            fi
        fi
    done
}

# Detect workflows with null phase (never started)
detect_null_phase_workflows() {
    local namespace=$1
    
    if ! verify_namespace_exists "$namespace" >/dev/null 2>&1; then
        return 1
    fi
    
    kubectl get workflows.argoproj.io -n "$namespace" -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase == null or .status.phase == "") | 
        "\(.metadata.name)|\(.metadata.creationTimestamp)"' 2>/dev/null
}

# Trigger workflow manually
trigger_workflow_manually() {
    local workflow_name=$1
    local namespace=$2
    
    print_info "Attempting to trigger workflow: $workflow_name in namespace: $namespace"
    
    # Check dependencies first
    print_info "  Checking workflow dependencies..."
    verify_kubevela_dependencies "$namespace"
    local dep_status=$?
    
    if [ $dep_status -eq 2 ]; then
        print_error "  Critical dependencies missing, cannot trigger workflow"
        return 1
    elif [ $dep_status -eq 1 ]; then
        print_warning "  Some dependencies not ready, workflow may fail"
    fi
    
    # Get workflow definition
    local workflow_def=$(kubectl get workflow "$workflow_name" -n "$namespace" -o json 2>/dev/null)
    
    if [ -z "$workflow_def" ]; then
        print_error "  Workflow $workflow_name not found"
        return 1
    fi
    
    # Check if workflow has actually started (has phase)
    local current_phase=$(echo "$workflow_def" | jq -r '.status.phase // "null"')
    
    if [ "$current_phase" != "null" ] && [ "$current_phase" != "" ]; then
        print_info "  Workflow already has phase: $current_phase, skipping trigger"
        return 0
    fi
    
    # Delete and recreate workflow to trigger it (workflows are immutable)
    print_info "  Deleting workflow to trigger recreation..."
    kubectl delete workflow "$workflow_name" -n "$namespace" --ignore-not-found=true 2>/dev/null
    
    sleep 2
    
    # Extract and recreate workflow
    echo "$workflow_def" | jq 'del(.status, .metadata.uid, .metadata.resourceVersion, .metadata.creationTimestamp, .metadata.generation, .metadata.managedFields)' | \
        kubectl apply -f - 2>/dev/null
    
    if [ $? -eq 0 ]; then
        print_success "  Workflow $workflow_name triggered successfully"
        return 0
    else
        print_error "  Failed to trigger workflow $workflow_name"
        return 1
    fi
}

# Verify KubeVela/Crossplane dependencies for an app
verify_kubevela_dependencies() {
    local namespace=$1
    local status=0
    
    print_info "Checking KubeVela/Crossplane dependencies for namespace: $namespace"
    
    # Check if namespace exists
    if ! verify_namespace_exists "$namespace" >/dev/null 2>&1; then
        print_warning "  Namespace $namespace does not exist"
        return 2
    fi
    
    # Check for KubeVela Applications
    local vela_apps=$(kubectl get applications.core.oam.dev -n "$namespace" --no-headers 2>/dev/null)
    
    if [ -n "$vela_apps" ]; then
        while read -r name rest; do
            local app_status=$(kubectl get application.core.oam.dev "$name" -n "$namespace" -o jsonpath='{.status.status}' 2>/dev/null)
            if [ "$app_status" = "running" ] || [ "$app_status" = "runningWorkflow" ]; then
                print_success "  KubeVela App $name: $app_status"
            else
                print_warning "  KubeVela App $name: ${app_status:-unknown}"
                status=1
            fi
        done <<< "$vela_apps"
    fi
    
    # Check for Crossplane-managed database secrets
    local db_secrets=$(kubectl get secrets -n crossplane-system --no-headers 2>/dev/null | grep -E "${namespace}.*connection" || echo "")
    
    if [ -n "$db_secrets" ]; then
        while read -r secret_name rest; do
            local has_endpoint=$(kubectl get secret "$secret_name" -n crossplane-system -o jsonpath='{.data.endpoint}' 2>/dev/null)
            local has_password=$(kubectl get secret "$secret_name" -n crossplane-system -o jsonpath='{.data.attribute\.master_password}' 2>/dev/null)
            
            if [ -n "$has_endpoint" ] && [ -n "$has_password" ]; then
                print_success "  Crossplane Secret $secret_name: ready (endpoint + password)"
            else
                print_warning "  Crossplane Secret $secret_name: incomplete"
                status=1
            fi
        done <<< "$db_secrets"
    else
        print_info "  No Crossplane database secrets found (may not be required)"
    fi
    
    return $status
}

# Detect applications with sync timeout pattern
detect_sync_timeout_pattern() {
    local timeout_threshold=${1:-900}  # 15 minutes default
    
    kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r --arg threshold "$timeout_threshold" --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.items[] | select(
            .status.operationState.phase == "Running" and
            ((.status.operationState.message // "") | contains("controller sync timeout")) and
            ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - ($threshold | tonumber))
        ) | 
        {
            name: .metadata.name,
            duration: (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime)),
            message: .status.operationState.message,
            resources: [.status.resources[] | select(.status == "OutOfSync") | .kind + "/" + .name] | join(", ")
        } | 
        "\(.name)|\(.duration)|\(.message)|\(.resources)"' 2>/dev/null
}

# Function to authenticate ArgoCD CLI
authenticate_argocd() {
    if command -v argocd >/dev/null 2>&1; then
        # For EKS Marina managed ArgoCD, use environment variables (no login needed)
        if [ -n "$ARGOCD_SERVER" ] && [ -n "$ARGOCD_AUTH_TOKEN" ]; then
            export ARGOCD_SERVER
            export ARGOCD_AUTH_TOKEN
            export ARGOCD_OPTS="${ARGOCD_OPTS:---grpc-web}"
            # Test if ArgoCD CLI is working
            if argocd cluster list >/dev/null 2>&1; then
                return 0
            fi
        fi
    fi
    return 1
}

# Function to terminate ArgoCD application operations
terminate_argocd_operation() {
    local app_name=$1
    
    # Check if there's actually an operation in progress
    local has_operation=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.status.operationState.phase}' 2>/dev/null)
    
    if [ -z "$has_operation" ] || [ "$has_operation" == "null" ]; then
        print_info "No operation in progress for $app_name, skipping termination"
        return 0
    fi
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to terminate operation for $app_name"
        if ! output=$(argocd app terminate-op "$app_name" 2>&1); then
            if echo "$output" | grep -q "Unable to terminate operation"; then
                print_info "No operation to terminate for $app_name"
            else
                print_warning "ArgoCD CLI terminate failed: $output, using direct kubectl approach"
                kubectl patch application.argoproj.io "$app_name" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
            fi
        fi
    else
        print_warning "ArgoCD CLI authentication failed, using direct kubectl approach"
        kubectl patch application.argoproj.io "$app_name" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
    fi
}

# Function to refresh ArgoCD application
refresh_argocd_app() {
    local app_name=$1
    local hard_refresh=${2:-true}
    
    local refresh_type="normal"
    [ "$hard_refresh" = "true" ] && refresh_type="hard"
    
    kubectl annotate application.argoproj.io "$app_name" -n argocd argocd.argoproj.io/refresh="$refresh_type" --overwrite 2>/dev/null || true
}

# Function to sync ArgoCD application in background (non-blocking)
sync_argocd_app_in_background() {
    local app_name=$1
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to sync $app_name (background)"
        argocd app sync "$app_name" &
    else
        print_warning "ArgoCD CLI authentication failed, using kubectl approach (background)"
        kubectl patch application.argoproj.io "$app_name" -n argocd --type='merge' -p='{"operation":{"sync":{}}}' &
    fi
}

# Function to check and trigger Keycloak PostSync hook
check_keycloak_postsync_hook() {
    local app_name=$1
    
    # Only check keycloak apps
    if [[ ! "$app_name" == *"keycloak"* ]]; then
        return 0
    fi
    
    # Check if config job exists and completed
    local job_status=$(kubectl get job config -n keycloak -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
    
    if [ "$job_status" = "True" ]; then
        print_info "Keycloak config job already completed"
        return 0
    fi
    
    # Check if keycloak-clients secret exists in AWS Secrets Manager
    local secret_name="${RESOURCE_PREFIX:-peeks}-hub/keycloak-clients"
    local secret_exists=$(aws secretsmanager describe-secret --secret-id "$secret_name" --region ${AWS_REGION:-us-west-2} --query 'Name' --output text 2>/dev/null || echo "")
    
    if [ -n "$secret_exists" ] && [ "$secret_exists" != "None" ]; then
        print_info "Keycloak secrets already exist in AWS Secrets Manager"
        return 0
    fi
    
    print_warning "Keycloak PostSync hook not executed, triggering sync..."
    
    # Clear any existing operation
    kubectl patch application "$app_name" -n argocd --type json -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
    sleep 2
    
    # Trigger fresh sync to execute PostSync hooks
    kubectl patch application "$app_name" -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
    
    # Wait for job to complete
    print_info "Waiting for Keycloak config job to complete..."
    local timeout=300
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        job_status=$(kubectl get job config -n keycloak -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null || echo "")
        if [ "$job_status" = "True" ]; then
            print_success "Keycloak config job completed successfully"
            return 0
        fi
        sleep 10
        elapsed=$((elapsed + 10))
    done
    
    print_warning "Timeout waiting for Keycloak config job"
    return 1
}

# Function to sync ArgoCD application
sync_argocd_app() {
    local app_name=$1
    local force_flag=""
    
    # Check if app is already healthy and synced - skip if so
    local app_status=$(kubectl get application "$app_name" -n argocd -o json 2>/dev/null)
    if [ -n "$app_status" ]; then
        local health=$(echo "$app_status" | jq -r '.status.health.status // "Unknown"')
        local sync=$(echo "$app_status" | jq -r '.status.sync.status // "Unknown"')
        local operation_phase=$(echo "$app_status" | jq -r '.status.operationState.phase // "None"')
        
        # Check for revision mismatch errors in operation state
        local operation_message=$(echo "$app_status" | jq -r '.status.operationState.message // ""')
        local revision_mismatch=false
        if [[ "$operation_message" == *"cannot reference a different revision"* ]] || [[ "$operation_message" == *"ComparisonError"* ]]; then
            print_info "Detected revision mismatch in $app_name, applying complete fix..."
            terminate_argocd_operation "$app_name"
            sleep 2
            refresh_argocd_app "$app_name" "true"
            sleep 5
            revision_mismatch=true
        fi
        
        # Skip if already healthy and synced with no running operations (unless we just fixed revision mismatch)
        if [ "$health" = "Healthy" ] && [ "$sync" = "Synced" ] && [ "$operation_phase" != "Running" ] && [ "$revision_mismatch" = false ]; then
            print_info "App $app_name already healthy and synced, skipping sync"
            
            # Check Keycloak PostSync hook even if app is synced
            check_keycloak_postsync_hook "$app_name"
            return 0
        fi
        
        # Skip if currently syncing (unless we just fixed revision mismatch)
        if [ "$operation_phase" = "Running" ] && [ "$revision_mismatch" = false ]; then
            print_info "App $app_name is currently syncing, skipping"
            return 0
        fi
        
        print_info "App $app_name needs sync (health: $health, sync: $sync, operation: $operation_phase)"
    fi
    
    # Force sync for keycloak to ensure PostSync hooks execute
    if [[ "$app_name" == *"keycloak"* ]]; then
        force_flag="--force"
        print_info "Using force sync for $app_name to execute PostSync hooks"
    fi
    
    # Try ArgoCD CLI first if available and authenticated
    if authenticate_argocd; then
        print_info "Using ArgoCD CLI to sync $app_name"
        argocd app sync "$app_name" $force_flag --timeout 200 || {
            print_warning "ArgoCD CLI sync failed, falling back to kubectl"
            kubectl patch application "$app_name" -n argocd --type merge -p '{"operation":{"sync":{}}}' 2>/dev/null || true
        }
    else
        print_warning "ArgoCD CLI authentication failed, using kubectl"
        kubectl patch application "$app_name" -n argocd --type merge -p '{"operation":{"sync":{}}}' 2>/dev/null || true
    fi
    
    # Check Keycloak PostSync hook after sync
    check_keycloak_postsync_hook "$app_name"
}

# Handle stuck operations (terminate if running > 3 mins)
handle_stuck_operations() {
    # Get stuck operations using both methods for better detection
    local stuck_apps_jq=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.items[] | select(.status.operationState?.phase == "Running" and (.status.operationState.startedAt | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 180)) | .metadata.name' 2>/dev/null || echo "")
    
    # Also check with simpler method for very old operations
    local stuck_apps_simple=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.operationState.phase}{" "}{.status.operationState.startedAt}{"\n"}{end}' 2>/dev/null | \
        awk -v now=$(date +%s) '$2=="Running" && (now - mktime(gensub(/[-T:Z]/, " ", "g", $3))) > 180 {print $1}')
    
    # Combine both results
    local all_stuck_apps=$(echo -e "$stuck_apps_jq\n$stuck_apps_simple" | sort -u | grep -v '^$')
    
    if [ -n "$all_stuck_apps" ]; then
        echo "$all_stuck_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_warning "Terminating stuck operation for $app (running > 3 minutes)"
                terminate_argocd_operation "$app"
                sleep 2
                refresh_argocd_app "$app"
            fi
        done
    fi
}

# Recover from CRD annotation size issues and missing namespaces
recover_crd_and_namespace_issues() {
    local app_name=$1
    
    # Get application details
    local app_json=$(kubectl get application "$app_name" -n argocd -o json 2>/dev/null)
    if [ -z "$app_json" ]; then
        return 0
    fi
    
    # Check for CRD annotation size errors
    local operation_message=$(echo "$app_json" | jq -r '.status.operationState.message // ""')
    if [[ "$operation_message" == *"metadata.annotations: Too long: may not be more than 262144 bytes"* ]]; then
        print_warning "Detected CRD annotation size issue in $app_name"
        
        # Extract CRD names from error message
        local crds=$(echo "$operation_message" | grep -oP 'CustomResourceDefinition\.apiextensions\.k8s\.io "\K[^"]+' | sort -u)
        
        if [ -n "$crds" ]; then
            echo "$crds" | while read -r crd; do
                if [ -n "$crd" ]; then
                    print_info "Cleaning oversized annotations from CRD: $crd"
                    kubectl get crd "$crd" -o json 2>/dev/null | \
                        jq 'del(.metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"])' | \
                        kubectl replace -f - 2>/dev/null || true
                fi
            done
            
            # Clear failed operation state and trigger resync
            kubectl patch application "$app_name" -n argocd --type=json -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
            sleep 2
            sync_argocd_app "$app_name"
        fi
    fi
    
    # Check for missing namespace errors
    if [[ "$operation_message" == *"namespaces"*"not found"* ]]; then
        # Extract namespace from error or app spec
        local target_namespace=$(echo "$app_json" | jq -r '.spec.destination.namespace // ""')
        
        if [ -n "$target_namespace" ] && [ "$target_namespace" != "null" ]; then
            if ! kubectl get namespace "$target_namespace" >/dev/null 2>&1; then
                print_warning "Creating missing namespace: $target_namespace"
                kubectl create namespace "$target_namespace" 2>/dev/null || true
                sleep 2
                
                # Clear failed operation state and trigger resync
                kubectl patch application "$app_name" -n argocd --type=json -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
                sleep 2
                sync_argocd_app "$app_name"
            fi
        fi
    fi
}

# Verify critical resources actually exist in cluster
verify_critical_resources() {
    local app_name=$1
    
    # Only check platform-manifests-bootstrap apps
    if [[ ! "$app_name" == *"platform-manifests-bootstrap"* ]]; then
        return 0  # Skip other apps
    fi
    
    # Get expected NodePool resources from app status
    local expected_nodepools=$(kubectl get application "$app_name" -n argocd -o json 2>/dev/null | \
        jq -r '.status.resources[]? | select(.kind == "NodePool") | .name' 2>/dev/null || echo "")
    
    if [ -z "$expected_nodepools" ]; then
        return 0  # No NodePools expected
    fi
    
    # Get cluster context from app destination
    local cluster_context=$(kubectl get application "$app_name" -n argocd -o jsonpath='{.spec.destination.name}' 2>/dev/null)
    
    if [ -z "$cluster_context" ]; then
        return 0  # Can't determine cluster
    fi
    
    # Check if NodePools actually exist in target cluster
    local missing_nodepools=""
    while read -r nodepool; do
        if [ -n "$nodepool" ]; then
            if ! kubectl get nodepool "$nodepool" --context "$cluster_context" >/dev/null 2>&1; then
                missing_nodepools="$missing_nodepools $nodepool"
            fi
        fi
    done <<< "$expected_nodepools"
    
    # If NodePools are missing, force recreation
    if [ -n "$missing_nodepools" ]; then
        print_warning "Critical resources missing for $app_name:$missing_nodepools"
        print_info "Forcing hard refresh and sync to recreate missing resources..."
        
        # Clear operation state
        kubectl patch application "$app_name" -n argocd --type='json' -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
        kubectl patch application "$app_name" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
        
        # Force hard refresh
        kubectl annotate application "$app_name" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
        sleep 5
        
        # Trigger sync with force flag
        kubectl patch application "$app_name" -n argocd --type merge -p='{"operation":{"initiatedBy":{"username":"admin"},"sync":{"syncStrategy":{"hook":{},"apply":{"force":true}},"prune":true}}}' 2>/dev/null || true
        
        return 1  # Signal that we fixed something
    fi
    
    return 0  # Everything is fine
}

# Handle sync issues (revision conflicts and OutOfSync applications)
handle_sync_issues() {
    # Get apps with revision conflicts OR OutOfSync/Missing status (often related issues)
    local problem_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(
            (.status.conditions[]? | select(.type == "ComparisonError" and (.message | contains("cannot reference a different revision")))) or
            (.status.sync.status == "OutOfSync" and .status.health.status == "Missing")
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$problem_apps" ]; then
        echo "$problem_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Fixing revision/sync issues for $app"
                terminate_argocd_operation "$app"
                sleep 2
                # Force hard refresh for OutOfSync/Missing apps
                refresh_argocd_app "$app" "true"
                sleep 3
                sync_argocd_app "$app"
                sleep 2
            fi
        done
    fi
    
    # Handle Degraded applications (Synced but Degraded health)
    local degraded_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.sync.status == "Synced" and .status.health.status == "Degraded") | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$degraded_apps" ]; then
        echo "$degraded_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Refreshing degraded application: $app"
                refresh_argocd_app "$app" "true"
                sleep 2
                sync_argocd_app "$app"
                sleep 2
            fi
        done
    fi
    
    # Check for CRD and namespace issues in failed apps
    local failed_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.operationState.phase == "Failed") | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$failed_apps" ]; then
        echo "$failed_apps" | while read -r app; do
            if [ -n "$app" ]; then
                recover_crd_and_namespace_issues "$app"
            fi
        done
    fi
    
    # Handle OutOfSync/Healthy apps (just need refresh and sync)
    local outofsync_healthy=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.sync.status == "OutOfSync" and .status.health.status == "Healthy") | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$outofsync_healthy" ]; then
        echo "$outofsync_healthy" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Syncing OutOfSync/Healthy application: $app"
                
                # Verify critical resources actually exist before syncing
                if ! verify_critical_resources "$app"; then
                    print_warning "Critical resources missing for $app, forced recreation initiated"
                    sleep 5
                    continue  # Skip normal sync, we already triggered force sync
                fi
                
                refresh_argocd_app "$app"
                sleep 1
                sync_argocd_app "$app"
            fi
        done
    fi
    
    # Handle any apps stuck in operations or Progressing state for too long
    local stuck_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '.items[] | select(
            ((.status.operationState.phase == "Running") or (.status.health.status == "Progressing")) and 
            ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$stuck_apps" ]; then
        echo "$stuck_apps" | while read -r app; do
            if [ -n "$app" ]; then
                print_info "Refreshing stuck application: $app"
                terminate_argocd_operation "$app"
                sleep 1
                refresh_argocd_app "$app" "true"
                sleep 2
                sync_argocd_app "$app" || true
                sleep 1
            fi
        done
    fi
}

# Wait for ArgoCD applications health (60min default timeout)
wait_for_argocd_apps_health() {
    local timeout=${1:-3600}
    local check_interval=${2:-30}
    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))
    
    print_info "Waiting for ArgoCD applications to become healthy (timeout: ${timeout}s)..."
    
    while [ $(date +%s) -lt $end_time ]; do
        # Check if ArgoCD namespace exists
        if ! kubectl get namespace argocd >/dev/null 2>&1; then
            print_warning "ArgoCD namespace not found, waiting..."
            sleep $check_interval
            continue
        fi
        
        # Check if ArgoCD server is responding with comprehensive pod check
        local argocd_server_ready=0
        local argocd_pods_running=0
        
        # Check deployment ready replicas
        argocd_server_ready=$(kubectl get deployment -n argocd argocd-server -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        [ -z "$argocd_server_ready" ] && argocd_server_ready="0"
        
        # Also check actual pod status
        argocd_pods_running=$(kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server --no-headers 2>/dev/null | grep -c "1/1.*Running" || echo "0")
        
        if [ "$argocd_server_ready" -eq 0 ] || [ "$argocd_pods_running" -eq 0 ]; then
            print_warning "ArgoCD server not ready (deployment: $argocd_server_ready, running pods: $argocd_pods_running), waiting..."
            sleep $check_interval
            continue
        fi
        
        # Check if ArgoCD domain is available (recalculate each time with improved error handling)
        local domain_name=""
        local domain_available=false
        
        # Try to get domain from secret first
        domain_name=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null || echo "")
        
        # If not found in secret or empty, try CloudFront with timeout
        if [ -z "$domain_name" ] || [ "$domain_name" = "null" ] || [ "$domain_name" = "" ]; then
            domain_name=$(timeout 30 aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null || echo "")
        fi
        
        # Validate domain name
        if [ -n "$domain_name" ] && [ "$domain_name" != "None" ] && [ "$domain_name" != "null" ] && [ "$domain_name" != "" ]; then
            domain_available=true
            print_info "ArgoCD domain found: $domain_name"
        else
            print_warning "ArgoCD domain not available yet, waiting..."
            sleep $check_interval
            continue
        fi
        
        # Check if applications exist
        if ! kubectl get applications -n argocd >/dev/null 2>&1; then
            print_warning "No ArgoCD applications found yet, waiting..."
            sleep $check_interval
            continue
        fi
        
        local total_apps=0
        local healthy_apps=0
        local synced_apps=0
        local unhealthy_apps=()
        
        # Get application status with error handling and retries
        local app_status=""
        local retry_count=0
        while [ $retry_count -lt 3 ]; do
            if app_status=$(kubectl get applications -n argocd -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.health.status}{" "}{.status.sync.status}{"\n"}{end}' 2>/dev/null); then
                break
            else
                print_warning "Failed to get application status (attempt $((retry_count + 1))/3), retrying..."
                sleep 10
                retry_count=$((retry_count + 1))
            fi
        done
        
        if [ $retry_count -eq 3 ]; then
            print_warning "Could not get application status after 3 attempts, continuing..."
            sleep $check_interval
            continue
        fi

        while IFS=' ' read -r app health sync; do
            [ -z "$app" ] && continue
            total_apps=$((total_apps + 1))
            
            # Handle missing health/sync status
            [ -z "$health" ] && health="Unknown"
            [ -z "$sync" ] && sync="Unknown"
            
            if [ "$health" = "Healthy" ]; then
                healthy_apps=$((healthy_apps + 1))
            fi
            
            if [ "$sync" = "Synced" ]; then
                synced_apps=$((synced_apps + 1))
            fi
            
            # Track unhealthy apps for syncing
            if [ "$health" != "Healthy" ] || [ "$sync" = "OutOfSync" ]; then
                unhealthy_apps+=("$app")
            fi
        done <<< "$app_status"

        local health_pct=0
        local sync_pct=0
        if [ $total_apps -gt 0 ]; then
            health_pct=$((healthy_apps * 100 / total_apps))
            sync_pct=$((synced_apps * 100 / total_apps))
        fi

        print_info "ArgoCD status: $healthy_apps/$total_apps healthy ($health_pct%), $synced_apps/$total_apps synced ($sync_pct%)"
        
        # Handle issues before checking success criteria
        handle_stuck_operations
        sleep 2
        handle_sync_issues
        
        # More lenient success criteria - accept 70% healthy and 60% synced
        if [ $total_apps -gt 0 ] && [ $health_pct -ge 70 ] && [ $sync_pct -ge 60 ]; then
            print_success "ArgoCD applications sufficiently healthy ($health_pct% healthy, $sync_pct% synced)"
            return 0
        fi
        
        # Show problematic apps for debugging
        if [ ${#unhealthy_apps[@]} -gt 0 ] && [ $(($(date +%s) - start_time)) -gt 300 ]; then
            print_warning "Problematic apps: ${unhealthy_apps[*]}"
        fi
        
        sleep $check_interval
    done
    
    print_error "Timeout waiting for ArgoCD applications health"
    return 1
}

# Dependency-aware ArgoCD app synchronization
wait_for_argocd_apps_with_dependencies() {
    print_info "Starting dependency-aware ArgoCD app synchronization..."
    
    # Phase 1: Wait for hub cluster core infrastructure (sync waves 0-30)
    kubectl config use-context "${RESOURCE_PREFIX}-hub"
    wait_for_sync_wave_completion "hub" 30
    
    # Phase 2: Verify hub Crossplane providers are healthy
    wait_for_hub_crossplane_ready
    
    # Phase 3: Wait for spoke clusters basic infrastructure (waves 0-20)
    for cluster_name in "${CLUSTER_NAMES[@]}"; do
        if [[ "$cluster_name" != *"hub"* ]]; then
            kubectl config use-context "$cluster_name"
            wait_for_sync_wave_completion "$cluster_name" 20
        fi
    done
    
    # Phase 4: Wait for spoke Crossplane providers (wave 25-30)
    for cluster_name in "${CLUSTER_NAMES[@]}"; do
        if [[ "$cluster_name" != *"hub"* ]]; then
            kubectl config use-context "$cluster_name"
            wait_for_sync_wave_completion "$cluster_name" 30
        fi
    done
    
    # Phase 5: Final health check for all remaining apps
    kubectl config use-context "${RESOURCE_PREFIX}-hub"
    wait_for_remaining_apps_health
}

# Recover from stuck workflows
recover_stuck_workflows() {
    local namespace=$1
    local max_age_minutes=${2:-15}
    local workflows_deleted=false
    
    # Find workflows stuck in Running phase for more than max_age_minutes
    local stuck_workflows=$(kubectl get workflows -n "$namespace" -o json 2>/dev/null | \
        jq -r --arg max_age "$max_age_minutes" \
        '.items[] | select(
            .status.phase == "Running" and
            (now - (.status.startedAt | fromdateiso8601)) > (($max_age | tonumber) * 60)
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$stuck_workflows" ]; then
        echo "$stuck_workflows" | while read -r workflow; do
            if [ -n "$workflow" ]; then
                print_warning "[$namespace] Deleting stuck workflow: $workflow (running > ${max_age_minutes}min)"
                kubectl delete workflow "$workflow" -n "$namespace" --ignore-not-found=true 2>/dev/null || true
                workflows_deleted=true
            fi
        done
    fi
    
    # Find workflows in Error or Failed phase
    local failed_workflows=$(kubectl get workflows -n "$namespace" -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase == "Error" or .status.phase == "Failed") | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$failed_workflows" ]; then
        echo "$failed_workflows" | while read -r workflow; do
            if [ -n "$workflow" ]; then
                print_warning "[$namespace] Deleting failed workflow: $workflow (phase: Error/Failed)"
                kubectl delete workflow "$workflow" -n "$namespace" --ignore-not-found=true 2>/dev/null || true
                workflows_deleted=true
            fi
        done
    fi
    
    # If workflows were deleted, trigger sync of applications that manage them
    if [ "$workflows_deleted" = true ]; then
        print_info "[$namespace] Workflows deleted, triggering application sync to recreate them"
        
        # Find applications that target this namespace
        local apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r --arg ns "$namespace" \
            '.items[] | select(.spec.destination.namespace == $ns) | .metadata.name' 2>/dev/null || echo "")
        
        if [ -n "$apps" ]; then
            echo "$apps" | while read -r app; do
                if [ -n "$app" ]; then
                    print_info "[$namespace] Syncing application: $app"
                    kubectl patch application "$app" -n argocd --type json -p='[{"op": "remove", "path": "/operation"}]' 2>/dev/null || true
                    sleep 1
                    kubectl patch application "$app" -n argocd --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
                fi
            done
        fi
        return 0
    fi
    
    return 1
}

wait_for_sync_wave_completion() {
    local cluster=$1
    local max_wave=$2
    local timeout=2700  # 45 minutes per phase
    
    print_info "[$cluster] Waiting for sync waves 0-$max_wave to complete..."
    
    local start_time=$(date +%s)
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        local pending_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r --arg max_wave "$max_wave" \
            '.items[] | select(
                ((.metadata.annotations."argocd.argoproj.io/sync-wave" // "0") | tonumber) <= ($max_wave | tonumber) and
                ((.status.sync.status != "Synced" or .status.health.status != "Healthy") and
                 (.status.operationState.phase // "None") != "Running")
            ) | .metadata.name' 2>/dev/null)
        
        # Filter out best effort apps from blocking
        local blocking_apps=""
        for app in $pending_apps; do
            local is_best_effort=false
            for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                if [[ "$app" == "$best_effort_app" ]]; then
                    is_best_effort=true
                    print_info "[$cluster] Syncing best effort app: $app (non-blocking)"
                    sync_argocd_app_in_background "$app"
                    break
                fi
            done
            if [[ "$is_best_effort" == false ]]; then
                blocking_apps="$blocking_apps $app"
            fi
        done
        
        if [ -z "$blocking_apps" ]; then
            print_success "[$cluster] Sync waves 0-$max_wave completed (ignoring best effort apps)"
            return 0
        fi
        
        # Check for stuck Argo Workflows and recover
        recover_stuck_workflows "devlake" 15 || true
        
        # Check for stuck apps and recover (both stuck operations and stuck Progressing)
        local stuck_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r --arg now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '.items[] | select(
                ((.status.operationState.phase == "Running") or (.status.health.status == "Progressing")) and 
                ((.status.operationState.startedAt // .metadata.creationTimestamp) | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) < (($now | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime) - 300)
            ) | .metadata.name' 2>/dev/null || echo "")
        
        if [ -n "$stuck_apps" ]; then
            echo "$stuck_apps" | while read -r app; do
                if [ -n "$app" ]; then
                    print_info "[$cluster] Recovering stuck app: $app"
                    terminate_argocd_operation "$app"
                    sleep 1
                    refresh_argocd_app "$app" "true"
                    sleep 2
                    sync_argocd_app "$app" || true
                    sleep 1
                fi
            done
        fi
        
        # Try to sync remaining problematic apps (only if they need it)
        for app in $blocking_apps; do
            if [ -n "$app" ]; then
                # Check if app actually needs sync
                local app_status=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
                    jq -r '{sync: .status.sync.status, health: .status.health.status}')
                local sync_status=$(echo "$app_status" | jq -r '.sync')
                local health_status=$(echo "$app_status" | jq -r '.health')
                
                if [[ "$sync_status" != "Synced" ]] || [[ "$health_status" != "Healthy" ]]; then
                    print_info "[$cluster] Syncing blocking app: $app"
                    sync_argocd_app "$app" || true
                else
                    print_info "[$cluster] App $app already healthy and synced, skipping"
                fi
            fi
        done
        
        print_info "[$cluster] Waiting for: $blocking_apps"
        sleep 30
    done
    
    print_warning "[$cluster] Timeout waiting for sync waves 0-$max_wave"
    return 1
}

wait_for_hub_crossplane_ready() {
    print_info "[hub] Verifying Crossplane providers are healthy..."
    
    local timeout=600  # 10 minutes
    local start_time=$(date +%s)
    
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        local unhealthy_providers=$(kubectl get providers -n crossplane-system --no-headers 2>/dev/null | \
            grep -v "True.*True" | wc -l)
        
        if [ "$unhealthy_providers" -eq 0 ]; then
            print_success "[hub] All Crossplane providers are healthy"
            return 0
        fi
        
        print_info "[hub] $unhealthy_providers Crossplane providers still unhealthy"
        sleep 30
    done
    
    print_warning "[hub] Timeout waiting for Crossplane providers"
    return 1
}

wait_for_remaining_apps_health() {
    print_info "Final cleanup: syncing remaining unhealthy applications..."
    
    # Get apps that are not healthy (excluding best effort apps)
    local unhealthy_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(
            .status.health.status != "Healthy"
        ) | .metadata.name' 2>/dev/null)
    
    if [ -n "$unhealthy_apps" ]; then
        print_info "Found unhealthy apps, attempting final sync..."
        echo "$unhealthy_apps" | while read -r app; do
            if [ -n "$app" ]; then
                local is_best_effort=false
                for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                    if [[ "$app" == "$best_effort_app" ]]; then
                        is_best_effort=true
                        break
                    fi
                done
                
                if [[ "$is_best_effort" == false ]]; then
                    print_info "Final sync attempt for unhealthy app: $app"
                    sync_argocd_app "$app" || true
                    sleep 10
                fi
            fi
        done
        
        print_info "Waiting for final sync operations to complete..."
        sleep 60
    fi
    
    print_success "Final cleanup completed"
    return 0
}

show_final_status() {
    print_info "Waiting for any ongoing sync operations to complete..."
    
    # First, immediately handle any apps with ComparisonError
    local comparison_error_apps=$(kubectl get applications -n argocd -o json 2>/dev/null | \
        jq -r '.items[] | select(
            (.status.operationState.phase == "Running") and
            ((.status.operationState.message // "") | contains("ComparisonError") or contains("cannot reference a different revision"))
        ) | .metadata.name' 2>/dev/null || echo "")
    
    if [ -n "$comparison_error_apps" ]; then
        print_warning "Found apps with ComparisonError that will never recover, terminating immediately..."
        echo "$comparison_error_apps" | while read -r app; do
            if [ -n "$app" ]; then
                # Check if it's a best effort app
                local is_best_effort=false
                for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                    if [[ "$app" == "$best_effort_app" ]]; then
                        is_best_effort=true
                        break
                    fi
                done
                
                print_warning "Terminating ComparisonError operation for $app"
                
                # Check if this is a revision conflict
                revision_conflict=$(kubectl get application "$app" -n argocd -o json 2>/dev/null | \
                    jq -r '.status.operationState.message // "" | contains("cannot reference a different revision")')
                
                if [ "$revision_conflict" = "true" ]; then
                    # Force revision alignment
                    kubectl patch application "$app" -n argocd --type='merge' -p='{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' 2>/dev/null || true
                    # Clear operation state
                    kubectl patch application "$app" -n argocd --type='json' -p='[{"op": "remove", "path": "/status/operationState"}]' 2>/dev/null || true
                    # Force refresh
                    kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
                    sleep 2
                else
                    terminate_argocd_operation "$app"
                    sleep 10
                    refresh_argocd_app "$app" "true"
                    sleep 10
                fi
                
                if [[ "$is_best_effort" == true ]]; then
                    sync_argocd_app_in_background "$app"
                else
                    sync_argocd_app "$app"
                fi
            fi
        done
        sleep 15  # Give time for sync operations to start properly
    fi
    
    # Wait for any running sync operations to finish
    local max_wait=300  # 5 minutes
    local wait_time=0
    
    while [ $wait_time -lt $max_wait ]; do
        local running_syncs=$(kubectl get applications -n argocd -o json 2>/dev/null | \
            jq -r '.items[] | select(.status.operationState.phase == "Running") | .metadata.name' 2>/dev/null || echo "")
        
        # Filter out best effort apps from blocking wait
        local blocking_running_syncs=""
        for app in $running_syncs; do
            local is_best_effort=false
            for best_effort_app in "${BEST_EFFORT_APPS[@]}"; do
                if [[ "$app" == "$best_effort_app" ]]; then
                    is_best_effort=true
                    break
                fi
            done
            if [[ "$is_best_effort" == false ]]; then
                blocking_running_syncs="$blocking_running_syncs $app"
            fi
        done
        
        if [ -z "$blocking_running_syncs" ]; then
            print_info "All blocking sync operations completed"
            break
        fi
        
        print_info "Waiting for sync operations: $(echo $blocking_running_syncs | tr '\n' ' ')"
        sleep 10
        wait_time=$((wait_time + 10))
    done
    
    if [ $wait_time -ge $max_wait ]; then
        print_warning "Timeout waiting for sync operations, showing current status..."
    fi
    
    print_info "Final ArgoCD Applications Status:"
    echo "----------------------------------------"
    
    if kubectl get applications -n argocd >/dev/null 2>&1; then
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
    else
        print_error "Cannot access ArgoCD applications"
    fi
    
    echo "----------------------------------------"
}

# Function to force sync all ArgoCD applications
force_sync_all_apps() {
    print_info "Force syncing all ArgoCD applications..."
    
    if ! kubectl get applications -n argocd >/dev/null 2>&1; then
        print_warning "No ArgoCD applications found"
        return 1
    fi
    
    kubectl get applications -n argocd -o name 2>/dev/null | while read app; do
        app_name=$(basename "$app")
        print_info "Force syncing $app_name..."
        terminate_argocd_operation "$app_name"
        sleep 1
        refresh_argocd_app "$app_name" "true"
        sleep 1
        sync_argocd_app "$app_name"
    done
    
    print_success "Completed force sync of all applications"
}

delete_argocd_appsets() {
    if kubectl get crd applicationsets.argoproj.io >/dev/null 2>&1; then
        kubectl get applicationsets.argoproj.io --all-namespaces --no-headers 2>/dev/null | while read -r namespace name _; do
            kubectl delete applicationsets.argoproj.io "$name" -n "$namespace" --cascade=orphan 2>/dev/null || true
        done
        return 0
    fi
    log "No ArgoCD ApplicationSets found..."
}

delete_argocd_apps() {
    local partial_names_str="$1"
    local action="${2:-delete}"  # delete or ignore
    local patch_required="${3:-false}"  # whether to patch finalizers
    
    local all_apps=$(kubectl get applications.argoproj.io --all-namespaces --no-headers 2>/dev/null)
    
    if [[ -z "$all_apps" ]]; then
        log "No ArgoCD Applications found..."
        return 0
    fi
    
    # Collect apps to delete
    local apps_to_delete=()
    
    while read -r namespace name _; do
        local should_process=false
        
        # Check if app matches any partial name (convert string to words)
        for partial in $partial_names_str; do
            if [[ -n "$partial" && "$name" == *"$partial"* ]]; then
                should_process=true
                break
            fi
        done
        
        # Process based on action
        if [[ "$action" == "ignore" && "$should_process" == "true" ]]; then
            continue
        elif [[ "$action" == "delete" && "$should_process" == "false" ]]; then
            continue
        fi
        
        apps_to_delete+=("$namespace:$name")
    done <<< "$all_apps"
    
    # Phase 1: Initiate deletion for all apps in parallel
    log "Initiating deletion of ${#apps_to_delete[@]} applications..."
    for app in "${apps_to_delete[@]}"; do
        local namespace="${app%%:*}"
        local name="${app##*:}"
        
        # Remove finalizers if required
        if [[ "$patch_required" == "true" ]]; then
            kubectl patch application.argoproj.io "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
        fi
        
        terminate_argocd_operation "$name" # Terminate any ongoing operation
        kubectl delete application.argoproj.io "$name" -n "$namespace" --wait=false 2>/dev/null || true
    done
    
    # Phase 2: Wait for deletions with reduced timeout
    local delete_timeout=15  # 15 seconds - apps that can delete will do so quickly
    local delete_start=$(date +%s)
    
    log "Waiting for applications to delete (timeout: ${delete_timeout}s)..."
    while true; do
        local remaining_apps=()
        
        for app in "${apps_to_delete[@]}"; do
            local namespace="${app%%:*}"
            local name="${app##*:}"
            
            if kubectl get application.argoproj.io "$name" -n "$namespace" >/dev/null 2>&1; then
                remaining_apps+=("$app")
            fi
        done
        
        # If no apps remaining, we're done
        if [[ ${#remaining_apps[@]} -eq 0 ]]; then
            log "All applications deleted successfully"
            break
        fi
        
        # Check timeout
        local elapsed=$(($(date +%s) - delete_start))
        if [ $elapsed -ge $delete_timeout ]; then
            log "Timeout reached. Force deleting ${#remaining_apps[@]} stuck applications..."
            for app in "${remaining_apps[@]}"; do
                local namespace="${app%%:*}"
                local name="${app##*:}"
                
                log "Force deleting: $name"
                kubectl patch application.argoproj.io "$name" -n "$namespace" --type='merge' -p='{"metadata":{"finalizers":null}}' 2>/dev/null || true
                kubectl delete application.argoproj.io "$name" -n "$namespace" --force --grace-period=0 2>/dev/null || true
            done
            break
        fi
        
        sleep 2
        apps_to_delete=("${remaining_apps[@]}")
    done
}
