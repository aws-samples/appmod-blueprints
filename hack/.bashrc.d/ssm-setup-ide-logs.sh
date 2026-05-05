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
    
    kubectl config use-context peeks-hub > /dev/null 2>&1
    
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

    # If token retrieval failed, try configuring IDC-Keycloak federation first
    if [[ -z "$token" || "$token" == "Failed to retrieve token" ]]; then
        echo "Token retrieval failed. Checking IDC-Keycloak federation..." >&2

        local idc_instance_arn idc_instance_id domain_name keycloak_admin_password
        idc_instance_arn=$(aws sso-admin list-instances --query 'Instances[0].InstanceArn' --output text 2>/dev/null || echo "None")
        if [[ -n "$idc_instance_arn" && "$idc_instance_arn" != "None" ]]; then
            idc_instance_id=$(echo "$idc_instance_arn" | grep -oP '[0-9a-f]{16}$' || echo "")
            [[ -z "$idc_instance_id" ]] && idc_instance_id=$(echo "$idc_instance_arn" | awk -F'/' '{print $NF}' | sed 's/^ssoins-//')
        fi

        domain_name=$(kubectl get secret ${RESOURCE_PREFIX:-peeks}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null || echo "")
        [[ -z "$domain_name" || "$domain_name" == "null" ]] && \
            domain_name=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text 2>/dev/null || echo "")

        keycloak_admin_password=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.KC_BOOTSTRAP_ADMIN_PASSWORD}' 2>/dev/null | base64 -d || echo "")

        if [[ -n "$idc_instance_id" && -n "$domain_name" && "$domain_name" != "None" && -n "$keycloak_admin_password" ]]; then
            echo "Running IDC-Keycloak federation setup..." >&2
            python3 "$script_dir/configure_identity_center.py" \
                --region "${AWS_REGION:-us-west-2}" \
                --instance-id "$idc_instance_id" \
                --keycloak-dns "$domain_name" \
                --keycloak-admin-password="$keycloak_admin_password" 2>&1 | tail -5 >&2

            echo "Retrying token retrieval..." >&2
            token=$(python3 "$script_dir/argocd_token_automation.py" \
                --url "$server_url" \
                --username "user1" \
                --password "${IDE_PASSWORD}" \
                --output token 2>/tmp/argocd-token-debug.log)
        else
            echo "ERROR: Cannot configure IDC federation (missing: instance_id=$idc_instance_id, domain=$domain_name, kc_password=$([ -n "$keycloak_admin_password" ] && echo set || echo missing))" >&2
        fi
    fi

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
