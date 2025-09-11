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
source "$SCRIPT_DIR/colors.sh"

# Switch to hub cluster context
print_step "Switching to ${RESOURCE_PREFIX}-hub-cluster context..."
kubectl config use-context ${RESOURCE_PREFIX}-hub-cluster 2>/dev/null || kubectx ${RESOURCE_PREFIX}-hub-cluster 2>/dev/null || echo "Warning: Could not switch context, using current context"

# Get CloudFront domain name
print_info "Retrieving CloudFront domain..."
DOMAIN_NAME=$(kubectl get secret ${RESOURCE_PREFIX}-hub-cluster -n argocd -o jsonpath='{.metadata.annotations.ingress_domain_name}' 2>/dev/null)
if [ -z "$DOMAIN_NAME" ]; then
    DOMAIN_NAME=$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'http-origin')].DomainName | [0]" --output text)
fi

# Get GitLab URL
print_info "Retrieving GitLab URL..."
GITLAB_URL=https://$(aws cloudfront list-distributions --query "DistributionList.Items[?contains(Origins.Items[0].Id, 'gitlab')].DomainName | [0]" --output text)

# Get credentials
print_info "Retrieving credentials..."
IDE_PASSWORD=$(kubectl get secret ide-password -n argocd -o jsonpath='{.data.password}' 2>/dev/null | base64 -d)
KEYCLOAK_ADMIN_PASSWORD=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.KC_BOOTSTRAP_ADMIN_PASSWORD}' 2>/dev/null | base64 -d)
if [ -z "$KEYCLOAK_ADMIN_PASSWORD" ]; then
    # Fallback: try to get from job logs
    KEYCLOAK_ADMIN_PASSWORD=$(kubectl logs -n keycloak job/config 2>/dev/null | grep "ADMIN_PASSWORD=" | head -1 | cut -d"'" -f2)
fi
USER_PASSWORD=$(kubectl get secret keycloak-config -n keycloak -o jsonpath='{.data.USER_PASSWORD}' 2>/dev/null | base64 -d)
if [ -z "$USER_PASSWORD" ]; then
    # Fallback: try to get from job logs
    USER_PASSWORD=$(kubectl logs -n keycloak job/config 2>/dev/null | grep "USER1_PASSWORD=" | head -1 | cut -d"=" -f2)
fi

# Define fixed column widths
TOOL_COL=14
URL_COL=55
CRED_COL=45

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

# Print header
print_header "EKS Cluster Management Tools"

# Print table header with ASCII characters
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
echo -e "${BOLD}| ${CYAN}$(pad_string "Tool" $TOOL_COL)${NC}${BOLD} | ${CYAN}$(pad_string "URL" $URL_COL)${NC}${BOLD} | ${CYAN}$(pad_string "Credentials / Password" $CRED_COL)${NC}${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"

# Print table rows with exact character counts
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "ArgoCD" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$ARGOCD_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "admin / $IDE_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Backstage" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$BACKSTAGE_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "SSO: user1 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Kargo" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$KARGO_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "SSO: user1 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Argo-Workflows" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$WORKFLOWS_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "SSO: user1 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Keycloak Admin" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$KEYCLOAK_ADMIN_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "admin / $KEYCLOAK_ADMIN_PASSWORD" $CRED_COL)${BOLD} |${NC}"
#echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
#echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Keycloak User" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$KEYCLOAK_PLATFORM_SHORT" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1,user2 / $USER_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"
echo -e "${BOLD}|${NC} ${GREEN}$(pad_string "Gitlab" $TOOL_COL)${NC}${BOLD} |${NC} ${YELLOW}$(pad_string "$GITLAB_URL" $URL_COL)${NC}${BOLD} |${NC} $(pad_string "user1 / $IDE_PASSWORD" $CRED_COL)${BOLD} |${NC}"
echo -e "${BOLD}+----------------+---------------------------------------------------------+-----------------------------------------------+${NC}"

# # Print full URLs for easy copy-paste
# print_header "Full URLs for copy-paste"
# print_info "ArgoCD: ${BOLD}$ARGOCD_URL${NC}"
# print_info "Backstage: ${BOLD}$BACKSTAGE_URL${NC}"
# print_info "Kargo: ${BOLD}$KARGO_URL${NC}"
# print_info "Argo-Workflows: ${BOLD}$WORKFLOWS_URL${NC}"
# print_info "Keycloak Admin: ${BOLD}$KEYCLOAK_ADMIN_URL${NC}"
# print_info "Keycloak Platform Realm: ${BOLD}$KEYCLOAK_PLATFORM_URL${NC}"
# print_info "GitLab: ${BOLD}$GITLAB_URL${NC}"

# # Print credentials
# print_header "Credentials"
# print_info "ArgoCD Admin Password: ${BOLD}$IDE_PASSWORD${NC}"
# print_info "GitLab Root Password: ${BOLD}$IDE_PASSWORD${NC} (main password)"
# print_info "Keycloak Admin (admin): ${BOLD}$KEYCLOAK_ADMIN_PASSWORD${NC}"
# print_info "Keycloak Users (user1/user2): ${BOLD}$USER_PASSWORD${NC}"

# # Print usage instructions
# print_header "Usage examples"
# print_info "ArgoCD CLI login: ${BOLD}argocd login --username admin --password $IDE_PASSWORD --grpc-web-root-path /argocd $DOMAIN_NAME${NC}"
# print_info "View applications: ${BOLD}argocd app list${NC}"
# print_info "Sync application: ${BOLD}argocd app sync <app-name>${NC}"
# print_info "Access Kargo: ${BOLD}curl --head -X GET $KARGO_URL${NC}"

# # Print authentication examples
# print_header "Authentication Examples"
# print_info "Test Keycloak user1 authentication:"
# print_info "${BOLD}curl -X POST https://$DOMAIN_NAME/keycloak/realms/platform/protocol/openid-connect/token \\${NC}"
# print_info "${BOLD}  -H \"Content-Type: application/x-www-form-urlencoded\" \\${NC}"
# print_info "${BOLD}  -d \"username=user1\" \\${NC}"
# print_info "${BOLD}  -d \"password=$USER_PASSWORD\" \\${NC}"
# print_info "${BOLD}  -d \"grant_type=password\" \\${NC}"
# print_info "${BOLD}  -d \"client_id=argo-workflows\" \\${NC}"
# print_info "${BOLD}  -d \"client_secret=orbAKJkIp0UbZVbrmMMiYdYzIlpLWHCD\"${NC}"