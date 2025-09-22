#!/bin/bash

#############################################################################
# Register Terraform Spoke Clusters Script
#############################################################################
#
# DESCRIPTION:
#   This script creates fleet member directories and values.yaml files for
#   spoke clusters using the resource prefix and cluster names.
#
# USAGE:
#   ./3-register-terraform-spoke-clusters.sh <environment>
#   
#   Examples:
#   ./3-register-terraform-spoke-clusters.sh dev
#   ./3-register-terraform-spoke-clusters.sh prod
#
# PREREQUISITES:
#   - RESOURCE_PREFIX environment variable must be set
#   - Script should be run from the platform root directory
#
#############################################################################

set -e

# Source colors for output formatting
SCRIPT_DIR="$(dirname "$0")"
source "$SCRIPT_DIR/colors.sh"

# Function to print colored output
print_status() {
    local status=$1
    local message=$2
    case $status in
        "INFO")
            echo -e "${BLUE}[INFO]${NC} $message"
            ;;
        "SUCCESS")
            echo -e "${GREEN}[SUCCESS]${NC} $message"
            ;;
        "ERROR")
            echo -e "${RED}[ERROR]${NC} $message"
            ;;
        "WARN")
            echo -e "${YELLOW}[WARN]${NC} $message"
            ;;
    esac
}

# Check if environment parameter is provided
if [ $# -eq 0 ]; then
    print_status "ERROR" "Usage: $0 <environment>"
    print_status "INFO" "Example: $0 dev"
    print_status "INFO" "Example: $0 prod"
    exit 1
fi

ENVIRONMENT=$1

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod|staging)$ ]]; then
    print_status "ERROR" "Environment must be one of: dev, prod, staging"
    exit 1
fi

# Check required environment variables
if [ -z "$RESOURCE_PREFIX" ]; then
    print_status "ERROR" "RESOURCE_PREFIX environment variable is not set"
    exit 1
fi

# Configuration
FLEET_MEMBERS_DIR="/home/ec2-user/environment/platform-on-eks-workshop/gitops/fleet/members"
FLEET_DIR_NAME="fleet-spoke-${ENVIRONMENT}"
CLUSTER_NAME="${RESOURCE_PREFIX}-spoke-${ENVIRONMENT}"
HUB_CLUSTER_NAME="${RESOURCE_PREFIX}-hub-cluster"
# Secret name matches Terraform format: ${var.resource_prefix}-hub-cluster/${var.cluster_name_prefix}-${terraform.workspace}
CLUSTER_NAME_PREFIX="${RESOURCE_PREFIX}-spoke"
SECRET_NAME="${HUB_CLUSTER_NAME}/${CLUSTER_NAME_PREFIX}-${ENVIRONMENT}"

print_status "INFO" "Registering spoke cluster for environment: $ENVIRONMENT"
print_status "INFO" "Resource prefix: $RESOURCE_PREFIX"
print_status "INFO" "Cluster name: $CLUSTER_NAME"
print_status "INFO" "Hub cluster: $HUB_CLUSTER_NAME"

# Create fleet member directory
FLEET_MEMBER_DIR="$FLEET_MEMBERS_DIR/$FLEET_DIR_NAME"

if [ -d "$FLEET_MEMBER_DIR" ]; then
    print_status "WARN" "Directory already exists: $FLEET_MEMBER_DIR"
    print_status "INFO" "Updating existing configuration..."
else
    print_status "INFO" "Creating directory: $FLEET_MEMBER_DIR"
    mkdir -p "$FLEET_MEMBER_DIR"
fi

# Create values.yaml file
VALUES_FILE="$FLEET_MEMBER_DIR/values.yaml"

print_status "INFO" "Creating values.yaml file: $VALUES_FILE"

cat > "$VALUES_FILE" << EOF
externalSecret:
  enabled: true
  clusterName: ${CLUSTER_NAME}
  secretStoreRefKind: ClusterSecretStore
  secretStoreRefName: aws-secrets-manager
  secretManagerSecretName: ${SECRET_NAME}
  server: remote
  
  annotations:
    environment: ${ENVIRONMENT}
    tenant: tenant1
    
  labels:
    environment: ${ENVIRONMENT}
    tenant: tenant1
    fleet_member: ${ENVIRONMENT}
    #TODO I think this is not used here, but already stored in the secret
    enable_cert_manager: "true"
    enable_external_secrets: "true"
    enable_ingress_nginx: "true"
    enable_metrics_server: "true"
    enable_kyverno: "true"
    enable_ack_ec2: "true"
    enable_ack_eks: "true"
    enable_ack_iam: "true"
    enable_ack_s3: "true"
    enable_kubevela: "true"
EOF

print_status "SUCCESS" "Fleet member configuration created successfully!"
print_status "INFO" "Directory: $FLEET_MEMBER_DIR"
print_status "INFO" "Values file: $VALUES_FILE"
print_status "INFO" "Cluster: $CLUSTER_NAME"
print_status "INFO" "Secret: $SECRET_NAME"

# Show the created file content
print_status "INFO" "Generated configuration:"
echo "----------------------------------------"
cat "$VALUES_FILE"
echo "----------------------------------------"

# Commit the fleet member configuration to git
print_status "INFO" "Committing fleet member configuration to git..."
cd "$SCRIPT_DIR/.." || exit 1
git add "gitops/fleet/members/fleet-spoke-$ENVIRONMENT/"
if git commit -m "Add fleet member configuration for spoke $ENVIRONMENT cluster"; then
    print_status "SUCCESS" "Fleet member configuration committed successfully"
    if git push origin HEAD:main; then
        print_status "SUCCESS" "Fleet member configuration pushed to remote repository"
    else
        print_status "WARN" "Failed to push to remote repository, but local commit succeeded"
    fi
else
    print_status "WARN" "No changes to commit (configuration may already exist)"
fi

print_status "SUCCESS" "Spoke cluster $ENVIRONMENT registered successfully!"
