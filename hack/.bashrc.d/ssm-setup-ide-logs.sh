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
