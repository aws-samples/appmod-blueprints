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