#!/bin/bash

# Key improvements based on log analysis:
# 1. Better argument validation
# 2. Skip if fleet member already exists
# 3. Validate cluster exists before registration
# 4. Better error handling

source "$(dirname "$0")/colors.sh"

# Validate arguments
if [[ $# -ne 1 ]]; then
    echo -e "${RED}[ERROR]${NC} Usage: $0 <environment>"
    echo "Examples: $0 dev, $0 prod"
    exit 1
fi

ENVIRONMENT="$1"

# Validate environment
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod|staging)$ ]]; then
    echo -e "${RED}[ERROR]${NC} Invalid environment: $ENVIRONMENT"
    echo "Valid environments: dev, prod, staging"
    exit 1
fi

# Check if cluster exists
CLUSTER_NAME="${SPOKE_CLUSTER_NAME_PREFIX:-peeks-workshop-spoke}-${ENVIRONMENT}"

check_cluster_exists() {
    local cluster="$1"
    echo -e "${BLUE}ℹ${NC} Checking if cluster $cluster exists..."
    
    if aws eks describe-cluster --name "$cluster" &>/dev/null; then
        echo -e "${GREEN}✓${NC} Cluster $cluster found"
        return 0
    else
        echo -e "${YELLOW}⚠${NC} Cluster $cluster not found, but continuing registration"
        return 0  # Don't fail, cluster might be created later
    fi
}

# Check if fleet member already registered
check_fleet_member_exists() {
    local env="$1"
    local fleet_dir="gitops/fleet/members/fleet-spoke-${env}"
    
    if [[ -f "$fleet_dir/values.yaml" ]]; then
        echo -e "${GREEN}✓${NC} Fleet member for $env already exists, skipping"
        return 0
    fi
    return 1
}

main() {
    echo -e "${BLUE}=== Registering Terraform Spoke Cluster: $ENVIRONMENT ===${NC}"
    
    # Check if already registered
    if check_fleet_member_exists "$ENVIRONMENT"; then
        exit 0
    fi
    
    # Validate cluster exists
    check_cluster_exists "$CLUSTER_NAME"
    
    # Create fleet member directory
    local fleet_dir="gitops/fleet/members/fleet-spoke-${ENVIRONMENT}"
    echo -e "${PURPLE}➤${NC} Creating fleet member directory: $fleet_dir"
    
    mkdir -p "$fleet_dir"
    
    # Create values.yaml with proper configuration
    cat > "$fleet_dir/values.yaml" << EOF
externalSecret:
  enabled: true
  clusterName: $CLUSTER_NAME
  secretStoreRefKind: ClusterSecretStore
  secretStoreRefName: aws-secrets-manager
  secretManagerSecretName: peeks-workshop-hub-cluster/$CLUSTER_NAME
  server: remote
  
  annotations:
    environment: $ENVIRONMENT
    tenant: tenant1
    
  labels:
    environment: $ENVIRONMENT
    tenant: tenant1
    fleet_member: $ENVIRONMENT
    enable_cert_manager: "true"
    enable_external_secrets: "true"
    enable_ingress_nginx: "true"
    enable_metrics_server: "true"
    enable_kyverno: "true"
    enable_ack_ec2: "true"
    enable_ack_eks: "true"
    enable_ack_iam: "true"
EOF
    
    echo -e "${GREEN}✓${NC} Fleet member registered for $ENVIRONMENT"
    echo -e "${BLUE}ℹ${NC} Cluster: $CLUSTER_NAME"
    echo -e "${BLUE}ℹ${NC} Fleet directory: $fleet_dir"
}

main "$@"
