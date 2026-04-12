ssm-setup-ide-logs() {
    local log_path=$(sudo find /var/lib/amazon/ssm -path "*/document/orchestration/*/awsrunShellScript/SetupIDE/stdout" 2>/dev/null | head -1)
    
    if [[ -n "$log_path" ]]; then
        sudo cat "$log_path"
    else
        echo "SetupIDE logs not found"
        return 1
    fi
}

argocd-sync() {
    local script_dir="/home/ec2-user/environment/platform-on-eks-workshop/platform/infra/terraform/scripts"
    
    # Source colors
    source "$script_dir/colors.sh"
    
    print_info "Running ArgoCD recovery..."
    bash "$script_dir/recover-argocd-apps.sh"
    
    echo ""
    print_info "Final ArgoCD Applications Status:"
    echo "----------------------------------------"
    kubectl get applications -n argocd -o json | jq -r '.items[] | "\(.metadata.name)|\(.status.sync.status // "Unknown")|\(.status.health.status // "Unknown")|\(.status.operationState.phase // "")|\(.status.operationState.message // .status.conditions[]?.message // "" | gsub("\n"; " "))"' | \
    while IFS='|' read -r name sync health operation message; do
        if [ "$health" = "Healthy" ] && { [ "$sync" = "Synced" ] || [ "$operation" = "Succeeded" ]; }; then
            print_success "$name: OK"
        else
            print_error "$name: KO - $sync/$health"
        fi
    done
    echo "----------------------------------------"
}

check-ray-build() {
    ~/environment/platform-on-eks-workshop/platform/infra/terraform/scripts/check-ray-build.sh
}

check-workshop-setup() {
    ~/environment/platform-on-eks-workshop/platform/infra/terraform/scripts/check-workshop-setup.sh
}

trigger-devlake() {
    local TEAM=${1:-rust}
    BP_ID=$(kubectl get configmap devlake-webhook-id -n team-$TEAM -o jsonpath='{.data.DEVLAKE_BP_ID}')
    kubectl port-forward svc/devlake-lake -n devlake 9090:8080 &
    PF_PID=$!
    sleep 2
    curl -X POST "http://localhost:9090/blueprints/$BP_ID/trigger" -H "Content-Type: application/json" -d '{"skipCollectors":false,"fullSync":false}'
    kill $PF_PID
}

argocd-refresh-token() {
    local script_dir="${WORKSPACE_PATH:-/home/ec2-user/environment}/${WORKING_REPO:-platform-on-eks-workshop}/platform/infra/terraform/scripts"
    local server_url
    server_url=$(aws eks describe-capability --cluster-name "${RESOURCE_PREFIX:-peeks}-hub" --capability-name argocd --query 'capability.configuration.argoCd.serverUrl' --output text 2>/dev/null)

    if [[ -z "$server_url" || "$server_url" == "None" ]]; then
        echo "ERROR: Could not get ArgoCD server URL" >&2
        return 1
    fi

    echo "Retrieving ArgoCD token via SSO (this may take ~30s)..." >&2
    local token
    token=$(python3 "$script_dir/argocd_token_automation.py" \
        --url "$server_url" \
        --username "user1" \
        --password "${IDE_PASSWORD}" \
        --output token 2>/tmp/argocd-token-debug.log)

    if [[ -z "$token" || "$token" == "Failed to retrieve token" ]]; then
        echo "ERROR: Failed to retrieve ArgoCD token. Debug log:" >&2
        cat /tmp/argocd-token-debug.log >&2
        return 1
    fi

    export ARGOCD_AUTH_TOKEN="$token"
    export ARGOCD_SERVER=$(echo "$server_url" | sed 's|https://||;s|/.*||')
    export ARGOCD_OPTS="--grpc-web"

    # Persist to platform.sh so new shells pick up the refreshed token
    local platform_sh="$HOME/.bashrc.d/platform.sh"
    if [[ -f "$platform_sh" ]]; then
        if grep -q "^export ARGOCD_AUTH_TOKEN=" "$platform_sh"; then
            sed -i "s|^export ARGOCD_AUTH_TOKEN=.*|export ARGOCD_AUTH_TOKEN=\"$token\"|" "$platform_sh"
        else
            echo "export ARGOCD_AUTH_TOKEN=\"$token\"" >> "$platform_sh"
        fi
        if grep -q "^export ARGOCD_SERVER=" "$platform_sh"; then
            sed -i "s|^export ARGOCD_SERVER=.*|export ARGOCD_SERVER=\"$ARGOCD_SERVER\"|" "$platform_sh"
        else
            echo "export ARGOCD_SERVER=\"$ARGOCD_SERVER\"" >> "$platform_sh"
        fi
        if grep -q "^export ARGOCD_OPTS=" "$platform_sh"; then
            sed -i "s|^export ARGOCD_OPTS=.*|export ARGOCD_OPTS=\"--grpc-web\"|" "$platform_sh"
        else
            echo "export ARGOCD_OPTS=\"--grpc-web\"" >> "$platform_sh"
        fi
    fi

    echo "ArgoCD token refreshed. Server: $ARGOCD_SERVER"
}
