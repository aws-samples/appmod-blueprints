#!/bin/bash
#########################################################################
# Script: 6-tools-urls.sh
# Description: Displays URLs and credentials for all tools deployed in the
#              EKS cluster management environment with perfect table alignment
# Author: AWS
# Date: 2025-05-20
# Usage: ./6-tools-urls.sh
#########################################################################

# Source the colors script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
GIT_ROOT_PATH=$(git rev-parse --show-toplevel)
source "${GIT_ROOT_PATH}/platform/infra/terraform/scripts/utils.sh"

# Source environment variables
if [ -d /home/ec2-user/.bashrc.d ]; then
    for file in /home/ec2-user/.bashrc.d/*.sh; do
        if [ -f "$file" ]; then
            source "$file"
        fi
    done
fi

# Get CloudFront domain name
print_info "Retrieving CloudFront domain..."
DOMAIN_NAME=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null)
if [ -z "$DOMAIN_NAME" ]; then
    DOMAIN_NAME=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text)
fi

# Get GitLab URL
print_info "Retrieving GitLab URL..."
GITLAB_URL=https://$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, 'gitlab')].DomainName | [0]" --output text)

# Get Grafana URL
print_info "Retrieving Grafana URL..."
GRAFANA_WORKSPACE_ID=$(aws grafana list-workspaces --region $AWS_REGION --query "workspaces[?contains(name, '${RESOURCE_PREFIX:-peeks}')].id | [0]" --output text 2>/dev/null || echo "")
if [ -n "$GRAFANA_WORKSPACE_ID" ] && [ "$GRAFANA_WORKSPACE_ID" != "None" ] && [ "$GRAFANA_WORKSPACE_ID" != "null" ]; then
    GRAFANA_URL=$(aws grafana describe-workspace --workspace-id "$GRAFANA_WORKSPACE_ID" --region $AWS_REGION --query "workspace.endpoint" --output text 2>/dev/null || echo "")
    if [ -n "$GRAFANA_URL" ]; then
        GRAFANA_URL="https://$GRAFANA_URL"
    else
        GRAFANA_URL="Grafana workspace not accessible"
    fi
else
    GRAFANA_URL="Grafana workspace not found"
fi

# Define fixed column widths (increased URL column for Grafana)
TOOL_COL=14
URL_COL=65
CRED_COL=40

# Function to create a padded string of specified length
pad_string() {
    local str="$1"
    local len=$2
    printf "%-${len}s" "$str"
}

# Store URLs for display
ARGOCD_URL="https://$DOMAIN_NAME/argocd"
BACKSTAGE_URL="https://$DOMAIN_NAME/backstage"
KARGO_URL="https://$DOMAIN_NAME"
WORKFLOWS_URL="https://$DOMAIN_NAME/argo-workflows"
KEYCLOAK_ADMIN_URL="https://$DOMAIN_NAME/keycloak/admin/"
KEYCLOAK_PLATFORM_URL="https://$DOMAIN_NAME/keycloak/realms/platform/account/"
KEYCLOAK_PLATFORM_SHORT="https://$DOMAIN_NAME/keycloak/realms/platform/account/"
KEYCLOAK_ADMIN_PASSWORD=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.KC_BOOTSTRAP_ADMIN_PASSWORD}' 2>/dev/null | base64 -d || echo "")
GIT_HOSTNAME=$(echo $GITLAB_URL | sed 's|https://||')
USER_PASSWORD=$IDE_PASSWORD

# Print header
print_header "EKS Cluster Management Tools"

# Print table header with ASCII characters
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}| ${CYAN}$(pad_string "Tool" $TOOL_COL)${NC}${BOLD} | ${CYAN}$(pad_string "URL" $URL_COL)${NC}${BOLD} | ${CYAN}$(pad_string "Credentials / Password" $CRED_COL)${NC}${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"

# Print table rows with exact character counts
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "ArgoCD" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$ARGOCD_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "admin / $IDE_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Backstage" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$BACKSTAGE_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Kargo" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$KARGO_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Argo-Workflows" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$WORKFLOWS_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Keycloak Admin" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$KEYCLOAK_ADMIN_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "admin / $KEYCLOAK_ADMIN_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Gitlab" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$GITLAB_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1 / $IDE_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Grafana" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$GRAFANA_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1 / $IDE_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+-------------------------------------------------------------------+------------------------------------------+${NC}"

update_workshop_var "ARGOCDURL" "$ARGOCD_URL"
update_workshop_var "GIT_HOSTNAME" "$GIT_HOSTNAME"
update_workshop_var "BACKSTAGEURL" "$BACKSTAGE_URL"
update_workshop_var "KARGOURL" "$KARGO_URL"
update_workshop_var "ARGOWFURL" "$ARGOWFURL"
update_workshop_var "KEYCLOAKADMINURL" "$KEYCLOAK_ADMIN_URL"
update_workshop_var "GITLABURL" "$GITLAB_URL"
update_workshop_var "GRAFANAURL" "$GRAFANA_URL"
update_workshop_var "KEYCLOAKADMINPASSWORD" "$KEYCLOAK_ADMIN_PASSWORD"
update_workshop_var "USER_PASSWORD" "$USER_PASSWORD"