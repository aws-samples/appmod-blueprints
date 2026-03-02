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
    ~/environment/platform-on-eks-workshop/platform/infra/terraform/scripts/recover-argocd-apps.sh  
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
