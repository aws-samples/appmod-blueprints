#!/bin/bash

# Setup script for Kro Backstage plugin RBAC configuration
# This script applies the RBAC configuration and creates necessary service accounts

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKSTAGE_NAMESPACE="backstage"
SERVICE_ACCOUNT_NAME="backstage-kro-service-account"
RBAC_FILE="k8s-rbac/backstage-kro-rbac.yaml"

echo -e "${YELLOW}Setting up Kro Backstage Plugin RBAC Configuration${NC}"
echo "=================================================="

# Check if kubectl is available
if ! command -v kubectl >/dev/null 2>&1; then
    echo -e "${RED}❌ kubectl is not installed${NC}"
    exit 1
fi

# Check if RBAC file exists
if [ ! -f "$RBAC_FILE" ]; then
    echo -e "${RED}❌ RBAC file not found: $RBAC_FILE${NC}"
    echo "Please run this script from the backstage directory"
    exit 1
fi

# Check cluster connectivity
echo -e "\n${YELLOW}1. Checking cluster connectivity...${NC}"
if kubectl cluster-info >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Cluster is accessible${NC}"
    CURRENT_CONTEXT=$(kubectl config current-context)
    echo "Current context: $CURRENT_CONTEXT"
else
    echo -e "${RED}❌ Cannot connect to cluster${NC}"
    exit 1
fi

# Create backstage namespace if it doesn't exist
echo -e "\n${YELLOW}2. Setting up backstage namespace...${NC}"
if kubectl get namespace "$BACKSTAGE_NAMESPACE" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Backstage namespace already exists${NC}"
else
    echo "Creating backstage namespace..."
    kubectl create namespace "$BACKSTAGE_NAMESPACE"
    echo -e "${GREEN}✅ Created backstage namespace${NC}"
fi

# Apply RBAC configuration
echo -e "\n${YELLOW}3. Applying RBAC configuration...${NC}"
if kubectl apply -f "$RBAC_FILE"; then
    echo -e "${GREEN}✅ RBAC configuration applied successfully${NC}"
else
    echo -e "${RED}❌ Failed to apply RBAC configuration${NC}"
    exit 1
fi

# Wait for service account to be created
echo -e "\n${YELLOW}4. Waiting for service account to be ready...${NC}"
kubectl wait --for=condition=Ready serviceaccount/"$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" --timeout=30s || true

# Check if service account was created
if kubectl get serviceaccount "$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Service account created successfully${NC}"
else
    echo -e "${RED}❌ Service account was not created${NC}"
    exit 1
fi

# Create a long-lived token for the service account (Kubernetes 1.24+)
echo -e "\n${YELLOW}5. Creating service account token...${NC}"

# Check Kubernetes version to determine token creation method
K8S_VERSION=$(kubectl version --client -o json | jq -r '.clientVersion.major + "." + .clientVersion.minor' 2>/dev/null || echo "1.24")

# Create token secret for older Kubernetes versions or create token directly for newer versions
TOKEN_SECRET_NAME="${SERVICE_ACCOUNT_NAME}-token"

# Try to create a token secret first (for compatibility)
cat <<EOF | kubectl apply -f - || true
apiVersion: v1
kind: Secret
metadata:
  name: ${TOKEN_SECRET_NAME}
  namespace: ${BACKSTAGE_NAMESPACE}
  annotations:
    kubernetes.io/service-account.name: ${SERVICE_ACCOUNT_NAME}
type: kubernetes.io/service-account-token
EOF

# Wait a moment for the token to be populated
sleep 5

# Try to get token from secret first
TOKEN=$(kubectl get secret "$TOKEN_SECRET_NAME" -n "$BACKSTAGE_NAMESPACE" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

# If no token from secret, create one directly (Kubernetes 1.24+)
if [ -z "$TOKEN" ]; then
    echo "Creating token directly (Kubernetes 1.24+ method)..."
    TOKEN=$(kubectl create token "$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" --duration=8760h 2>/dev/null || echo "")
fi

if [ -n "$TOKEN" ]; then
    echo -e "${GREEN}✅ Service account token created successfully${NC}"
    
    # Save token to a file for reference
    echo "$TOKEN" > "${SERVICE_ACCOUNT_NAME}-token.txt"
    echo "Token saved to: ${SERVICE_ACCOUNT_NAME}-token.txt"
    
    # Show first and last few characters for verification
    TOKEN_PREVIEW="${TOKEN:0:20}...${TOKEN: -20}"
    echo "Token preview: $TOKEN_PREVIEW"
else
    echo -e "${RED}❌ Failed to create service account token${NC}"
    echo "You may need to create the token manually:"
    echo "kubectl create token $SERVICE_ACCOUNT_NAME -n $BACKSTAGE_NAMESPACE --duration=8760h"
fi

# Test permissions
echo -e "\n${YELLOW}6. Testing service account permissions...${NC}"

# Test ResourceGraphDefinition access
if kubectl auth can-i get resourcegraphdefinitions --as=system:serviceaccount:$BACKSTAGE_NAMESPACE:$SERVICE_ACCOUNT_NAME >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Service account can access ResourceGraphDefinitions${NC}"
else
    echo -e "${RED}❌ Service account cannot access ResourceGraphDefinitions${NC}"
fi

# Test basic Kubernetes resource access
if kubectl auth can-i get pods --as=system:serviceaccount:$BACKSTAGE_NAMESPACE:$SERVICE_ACCOUNT_NAME >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Service account can access Pods${NC}"
else
    echo -e "${RED}❌ Service account cannot access Pods${NC}"
fi

# Test Kro instance access
echo "Testing access to Kro instances..."
for rgd in $(kubectl get resourcegraphdefinitions --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -3); do
    kind=$(echo "$rgd" | cut -d'.' -f1)
    kind_proper=$(echo "$kind" | sed 's/./\U&/')
    
    if kubectl auth can-i get "$kind_proper" --as=system:serviceaccount:$BACKSTAGE_NAMESPACE:$SERVICE_ACCOUNT_NAME >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Service account can access $kind_proper instances${NC}"
    else
        echo -e "${YELLOW}⚠️  Service account cannot access $kind_proper instances${NC}"
    fi
done

# Get cluster information for configuration
echo -e "\n${YELLOW}7. Cluster configuration information...${NC}"

CLUSTER_URL=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[0].name}')
CA_DATA=$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

echo "Cluster URL: $CLUSTER_URL"
echo "Cluster Name: $CLUSTER_NAME"

# Create environment configuration file
echo -e "\n${YELLOW}8. Creating environment configuration...${NC}"

cat > backstage-kro-env.sh <<EOF
#!/bin/bash
# Environment variables for Backstage Kro plugin configuration
# Source this file or add these variables to your environment

export K8S_CLUSTER_URL="$CLUSTER_URL"
export K8S_CLUSTER_NAME="$CLUSTER_NAME"
export K8S_SERVICE_ACCOUNT_TOKEN="$TOKEN"
export K8S_CLUSTER_CA_DATA="$CA_DATA"

echo "Backstage Kro environment variables set:"
echo "K8S_CLUSTER_URL=\$K8S_CLUSTER_URL"
echo "K8S_CLUSTER_NAME=\$K8S_CLUSTER_NAME"
echo "K8S_SERVICE_ACCOUNT_TOKEN=<token-set>"
echo "K8S_CLUSTER_CA_DATA=<ca-data-set>"
EOF

chmod +x backstage-kro-env.sh
echo -e "${GREEN}✅ Environment configuration saved to: backstage-kro-env.sh${NC}"

echo -e "\n${GREEN}✅ RBAC setup completed successfully!${NC}"
echo -e "\nNext steps:"
echo "1. Source the environment configuration: source backstage-kro-env.sh"
echo "2. Update your app-config.yaml with the environment variables"
echo "3. Restart Backstage to pick up the new configuration"
echo "4. Verify Kro resources appear in the Backstage catalog"

# Show summary
echo -e "\n${YELLOW}Summary:${NC}"
echo "- Service Account: $SERVICE_ACCOUNT_NAME (namespace: $BACKSTAGE_NAMESPACE)"
echo "- ClusterRole: backstage-kro-reader"
echo "- Token file: ${SERVICE_ACCOUNT_NAME}-token.txt"
echo "- Environment file: backstage-kro-env.sh"