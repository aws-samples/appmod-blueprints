SPOKE_CLUSTER_PREFIX=${SPOKE_CLUSTER_NAME_PREFIX:-peeks-spoke}
SPOKE_DEV_CLUSTER="${SPOKE_CLUSTER_PREFIX}-dev"
SPOKE_PROD_CLUSTER="${SPOKE_CLUSTER_PREFIX}-prod"

function deploy_prod (){
  # Deploy the production cluster

  # Create the production cluster
  mkdir $GITOPS_DIR/fleet/members/peeks-spoke-prod
  cp $WORKSHOP_DIR/gitops/solutions/module-platform/fleet/members/peeks-spoke-prod/values.yaml $GITOPS_DIR/fleet/members/peeks-spoke-prod/values.yaml
  git -C $GITOPS_DIR/fleet status
  git -C $GITOPS_DIR/fleet add .
  git -C $GITOPS_DIR/fleet commit -m "add production cluster fleet member"
  git -C $GITOPS_DIR/fleet push

  # Deploy the production addons
  mkdir $GITOPS_DIR/addons/clusters/peeks-spoke-prod
  cp -r $WORKSHOP_DIR/gitops/solutions/module-platform/addons/clusters/peeks-spoke-prod/* $GITOPS_DIR/addons/clusters/peeks-spoke-prod/
  git -C $GITOPS_DIR/addons status
  git -C $GITOPS_DIR/addons add .
  git -C $GITOPS_DIR/addons commit -m "add addons for production cluster"
  git -C $GITOPS_DIR/addons push

  # Deploy the production namespaces
  cp -r $WORKSHOP_DIR/gitops/solutions/module-platform/platform/teams/* $GITOPS_DIR/platform/teams/
  git -C $GITOPS_DIR/platform status
  git -C $GITOPS_DIR/platform add .
  git -C $GITOPS_DIR/platform commit -m "add production namespaces for teams"
  git -C $GITOPS_DIR/platform push

  # Deploy the production apps
  cp -r $WORKSHOP_DIR/gitops/solutions/module-platform/apps/* $GITOPS_DIR/apps/
  git -C $GITOPS_DIR/apps status
  git -C $GITOPS_DIR/apps add .
  git -C $GITOPS_DIR/apps commit -m "add production kustomize files for apps"
  git -C $GITOPS_DIR/apps push
}

function app_url_dev (){
  wait-for-lb $(kubectl --context $SPOKE_DEV_CLUSTER get svc -n ui ui-nlb -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
}
function app_url_prod (){
  wait-for-lb $(kubectl --context $SPOKE_PROD_CLUSTER get svc -n ui ui-nlb -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
}

function apps_fix_kyverno_insights(){
  apps_fix_kyverno_insights_dev
  apps_fix_kyverno_insights_prod
}

function kyverno_policy_reporter_ui_dev_on(){
  nohup kubectl --context $SPOKE_DEV_CLUSTER port-forward -n kyverno svc/policy-reporter-ui 8085:8080 > /dev/null 2>&1 &
  echo $IDE_URL/proxy/8085/#/
}

function kyverno_policy_reporter_ui_prod_on(){
  nohup kubectl --context $SPOKE_PROD_CLUSTER port-forward -n kyverno svc/policy-reporter-ui 8086:8080 > /dev/null 2>&1 &
  echo $IDE_URL/proxy/8086/#/
}

function kyverno_policy_reporter_ui_off(){
  pkill -f "kubectl.*port-forward.*policy-reporter-ui"
}

function apps_fix_kyverno_insights_dev (){
  # Fix Kyverno Insights

  #dev
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/backend/catalog/dev/kustomization.yaml $GITOPS_DIR/apps/backend/catalog/dev/kustomization.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/backend/catalog/dev/deployment.yaml $GITOPS_DIR/apps/backend/catalog/dev/deployment.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/assets/dev/kustomization.yaml $GITOPS_DIR/apps/frontend/assets/dev/kustomization.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/assets/dev/deployment.yaml $GITOPS_DIR/apps/frontend/assets/dev/deployment.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/ui/dev/kustomization.yaml $GITOPS_DIR/apps/frontend/ui/dev/kustomization.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/ui/dev/deployment.yaml $GITOPS_DIR/apps/frontend/ui/dev/deployment.yaml

  git -C $GITOPS_DIR/apps status
  git -C $GITOPS_DIR/apps diff | cat
  git -C $GITOPS_DIR/apps add .
  git -C $GITOPS_DIR/apps commit -m "Fix Kyverno in catalog for Staging"
  git -C $GITOPS_DIR/apps push

}

function apps_fix_kyverno_prod_dev (){
  # Fix Kyverno Insights

  #dev
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/backend/catalog/prod/kustomization.yaml $GITOPS_DIR/apps/backend/catalog/prod/kustomization.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/backend/catalog/prod/deployment.yaml $GITOPS_DIR/apps/backend/catalog/prod/deployment.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/assets/prod/kustomization.yaml $GITOPS_DIR/apps/frontend/assets/prod/kustomization.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/assets/prod/deployment.yaml $GITOPS_DIR/apps/frontend/assets/prod/deployment.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/ui/prod/kustomization.yaml $GITOPS_DIR/apps/frontend/ui/prod/kustomization.yaml
  cp $WORKSHOP_DIR/gitops/solutions/module-kyverno/apps/frontend/ui/prod/deployment.yaml $GITOPS_DIR/apps/frontend/ui/prod/deployment.yaml

  git -C $GITOPS_DIR/apps status
  git -C $GITOPS_DIR/apps diff | cat
  git -C $GITOPS_DIR/apps add .
  git -C $GITOPS_DIR/apps commit -m "Fix Kyverno in catalog for Prod"
  git -C $GITOPS_DIR/apps push

}

function apps_default_kyverno_insights (){
  # restore default deployment

  # Create the production cluster
  mkdir $GITOPS_DIR/fleet/members/peeks-spoke-prod
  cp $WORKSHOP_DIR/gitops/apps/backend/catalog/base/deployment.yaml $GITOPS_DIR/apps/backend/catalog/base/deployment.yaml
  cp $WORKSHOP_DIR/gitops/apps/frontend/ui/base/deployment.yaml $GITOPS_DIR/apps/frontend/ui/base/deployment.yaml
  cp $WORKSHOP_DIR/gitops/apps/frontend/assets/base/deployment.yaml $GITOPS_DIR/apps/frontend/assets/base/deployment.yaml
  git -C $GITOPS_DIR/apps status
  git -C $GITOPS_DIR/apps diff | cat
  git -C $GITOPS_DIR/apps add .
  git -C $GITOPS_DIR/apps commit -m "Revert Fix Kyverno in catalog"
  git -C $GITOPS_DIR/apps push

}

function custom_domain() {
  (
    set -e
    #set -x

    # Check if both parameters are provided
    if [ -z "$1" ] || [ -z "$2" ]; then
        echo "Error: Both environment and domain parameters are required"
        echo "Usage: custom_domain <environment> <domain-name>"
        echo "Environment must be either 'dev' or 'prod'"
        return 1
    fi

    local ENVIRONMENT="$1"
    local DOMAIN_NAME="$2"

    # Validate environment parameter
    if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
        echo "Error: Environment must be either 'dev' or 'prod'"
        return 1
    fi

    # Check if the hosted zone exists in Route53
    if ! aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN_NAME." --max-items 1 | grep -q "\"Name\": \"$DOMAIN_NAME.\""; then
        echo "Error: No Route53 hosted zone found for domain: $DOMAIN_NAME"
        echo "Please ensure the domain exists as a public hosted zone in Route53"
        return 1
    fi

    echo "Updating EKS Spoke cluster to use domain $DOMAIN_NAME... this can take couple of minutes..."
    cp "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/terraform/spokes/custom_domain.tf" "$WORKSHOP_DIR/terraform/spokes/custom_domain.tf"
    export TF_VAR_hosted_zone_name="$DOMAIN_NAME"
    $WORKSHOP_DIR/terraform/spokes/deploy.sh "$ENVIRONMENT"
   
    echo "EKS Spoke cluster successfully deployed..."

    echo "Configuring External-DNS addon"

    echo "Creating platform ApplicationSet for ArgoCD Ingress and Configure Domain Name in frontend ingress"
    cp "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/gitops/platform/bootstrap/workloads/platform-apps.yaml" "$GITOPS_DIR/platform/bootstrap/workloads/platform-apps.yaml"
    cp "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/gitops/platform/bootstrap/workloads/web-store-frontend-appset.yaml" "$GITOPS_DIR/platform/bootstrap/workloads/web-store-frontend-appset.yaml"

    if [[ -n "$(git -C "$GITOPS_DIR/platform" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/platform" status
        git -C "$GITOPS_DIR/platform" diff | cat
        git -C "$GITOPS_DIR/platform" add .
        git -C "$GITOPS_DIR/platform" commit -m "Adding domain name for frontend"
        git -C "$GITOPS_DIR/platform" push
    else
        echo "No changes to commit in platform repository"
    fi

    echo "Adding ingress kustomization"
    cp "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/gitops/apps/frontend/ui/$ENVIRONMENT/ingress.yaml" "$GITOPS_DIR/apps/frontend/ui/$ENVIRONMENT/ingress.yaml"
    cp "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/gitops/apps/frontend/ui/$ENVIRONMENT/kustomization.yaml" "$GITOPS_DIR/apps/frontend/ui/$ENVIRONMENT/kustomization.yaml"
    cp -r "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/gitops/apps/platform" "$GITOPS_DIR/apps/"
    if [[ -n "$(git -C "$GITOPS_DIR/apps" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/apps" status
        git -C "$GITOPS_DIR/apps" diff | cat
        git -C "$GITOPS_DIR/apps" add .
        git -C "$GITOPS_DIR/apps" commit -m "Adding ingress & kustomization"
        git -C "$GITOPS_DIR/apps" push
    else
        echo "No changes to commit in apps repository"
    fi

    echo "Activating External DNS addon patch in ingress"
    cp "$WORKSHOP_DIR/gitops/solutions/module-custom-domain/gitops/addons/clusters/peeks-spoke-$ENVIRONMENT/addons/gitops-bridge/values.yaml" \
       "$GITOPS_DIR/addons/clusters/peeks-spoke-$ENVIRONMENT/addons/gitops-bridge/values.yaml"
    if [[ -n "$(git -C "$GITOPS_DIR/addons" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/addons" status
        git -C "$GITOPS_DIR/addons" diff | cat
        git -C "$GITOPS_DIR/addons" add .
        git -C "$GITOPS_DIR/addons" commit -m "Activating External DNS addon patch in ingress"
        git -C "$GITOPS_DIR/addons" push
    else
        echo "No changes to commit in addons repository"
    fi

    echo "Removing Argocd Proxy configuration"
    sed -i '/^[[:space:]]*params:/,+1 s/^/#/' $GITOPS_DIR/addons/environments/dev/addons/argocd/values.yaml
    if [[ -n "$(git -C "$GITOPS_DIR/addons" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/addons" status
        git -C "$GITOPS_DIR/addons" diff | cat
        git -C "$GITOPS_DIR/addons" add .
        git -C "$GITOPS_DIR/addons" commit -m "Remove Argo CD proxy configuration"
        git -C "$GITOPS_DIR/addons" push
    else
        echo "No changes to commit in addons repository"
    fi

  )
}

function custom_domain_delete() {
  (
    set -e
    #set -x

    # Check if both parameters are provided
    if [ -z "$1" ] || [ -z "$2" ]; then
        echo "Error: Both environment and domain parameters are required"
        echo "Usage: custom_domain <environment> <domain-name>"
        echo "Environment must be either 'dev' or 'prod'"
        return 1
    fi

    local ENVIRONMENT="$1"
    local DOMAIN_NAME="$2"

    # Validate environment parameter
    if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
        echo "Error: Environment must be either 'dev' or 'prod'"
        return 1
    fi

    # Check if the hosted zone exists in Route53
    if ! aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN_NAME." --max-items 1 | grep -q "\"Name\": \"$DOMAIN_NAME.\""; then
        echo "Error: No Route53 hosted zone found for domain: $DOMAIN_NAME"
        echo "Please ensure the domain exists as a public hosted zone in Route53"
        return 1
    fi

    echo "Removing External-DNS addon configuration"

    echo "Restore initial configuration removing platform ApplicationSet for ArgoCD Ingress and Configure Domain Name in frontend ingress"
    rm "$GITOPS_DIR/platform/bootstrap/workloads/platform-apps.yaml" || true
    cp "$WORKSHOP_DIR/gitops/platform/bootstrap/workloads/web-store-frontend-appset.yaml" "$GITOPS_DIR/platform/bootstrap/workloads/web-store-frontend-appset.yaml"

    if [[ -n "$(git -C "$GITOPS_DIR/platform" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/platform" status
        git -C "$GITOPS_DIR/platform" diff | cat
        git -C "$GITOPS_DIR/platform" add .
        git -C "$GITOPS_DIR/platform" commit -m "Deleting domain name for frontend"
        git -C "$GITOPS_DIR/platform" push
    else
        echo "No changes to commit in platform repository"
    fi

    echo "Cleanup ingress kustomization"
    rm "$GITOPS_DIR/apps/frontend/ui/$ENVIRONMENT/ingress.yaml" || true
    cp "$WORKSHOP_DIR/gitops/apps/frontend/ui/$ENVIRONMENT/kustomization.yaml" "$GITOPS_DIR/apps/frontend/ui/$ENVIRONMENT/kustomization.yaml"
    rm -rf "$GITOPS_DIR/apps/platform" || true
    if [[ -n "$(git -C "$GITOPS_DIR/apps" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/apps" status
        git -C "$GITOPS_DIR/apps" diff | cat
        git -C "$GITOPS_DIR/apps" add .
        git -C "$GITOPS_DIR/apps" commit -m "Deleting ingress & kustomization"
        git -C "$GITOPS_DIR/apps" push
    else
        echo "No changes to commit in apps repository"
    fi

    echo "Removing External DNS addon patch in ingress"
    sed -i 's/external_dns:\n    enabled: true # Activate external-dns for custom domain name/external_dns:\n    enabled: false # Activate external-dns for custom domain name/' "$GITOPS_DIR/addons/clusters/peeks-spoke-$ENVIRONMENT/addons/gitops-bridge/values.yaml"
    if [[ -n "$(git -C "$GITOPS_DIR/addons" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/addons" status
        git -C "$GITOPS_DIR/addons" diff | cat
        git -C "$GITOPS_DIR/addons" add .
        git -C "$GITOPS_DIR/addons" commit -m "Removing External DNS addon patch in ingress"
        git -C "$GITOPS_DIR/addons" push
    else
        echo "No changes to commit in addons repository"
    fi

    echo "Removing Argocd Proxy configuration"
    sed -i '/^[[:space:]]*#[[:space:]]*params:/,+1 s/^[[:space:]]*#//' $GITOPS_DIR/addons/environments/dev/addons/argocd/values.yaml
    if [[ -n "$(git -C "$GITOPS_DIR/addons" status --porcelain)" ]]; then
        git -C "$GITOPS_DIR/addons" status
        git -C "$GITOPS_DIR/addons" diff | cat
        git -C "$GITOPS_DIR/addons" add .
        git -C "$GITOPS_DIR/addons" commit -m "Remove Argo CD proxy configuration"
        git -C "$GITOPS_DIR/addons" push
    else
        echo "No changes to commit in addons repository"
    fi

    echo "Removing the ability for EKS Spoke cluster to use domain $DOMAIN_NAME... this can take couple of minutes..."
    rm "$WORKSHOP_DIR/terraform/spokes/custom_domain.tf" || true
    export TF_VAR_hosted_zone_name="$DOMAIN_NAME"
    $WORKSHOP_DIR/terraform/spokes/deploy.sh "$ENVIRONMENT"
    echo "EKS Spoke cluster custom domain successfully removed..."

  )
}

function validation_locust_ui(){
  nohup kubectl --context $SPOKE_DEV_CLUSTER port-forward -n default service/eks-loadtest-locust 8089:8089 > /dev/null 2>&1 &
  echo $IDE_URL/proxy/8089/
}