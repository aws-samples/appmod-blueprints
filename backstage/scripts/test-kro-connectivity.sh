#!/bin/bash

# Test script for Kro Backstage plugin Kubernetes connectivity
# This script verifies that:
# 1. Kubernetes clusters are accessible
# 2. Kro controller is installed and running
# 3. RBAC permissions are properly configured
# 4. ResourceGroups can be discovered

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKSTAGE_NAMESPACE="backstage"
SERVICE_ACCOUNT_NAME="backstage-kro-service-account"

echo -e "${YELLOW}Testing Kro Backstage Plugin Kubernetes Connectivity${NC}"
echo "=================================================="

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo -e "\n${YELLOW}1. Checking prerequisites...${NC}"

if ! command_exists kubectl; then
    echo -e "${RED}❌ kubectl is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✅ kubectl is available${NC}"

if ! command_exists aws; then
    echo -e "${RED}❌ AWS CLI is not installed${NC}"
    exit 1
fi
echo -e "${GREEN}✅ AWS CLI is available${NC}"

# Check kubeconfig
if [ ! -f "$KUBECONFIG" ]; then
    echo -e "${RED}❌ KUBECONFIG file not found: $KUBECONFIG${NC}"
    exit 1
fi
echo -e "${GREEN}✅ KUBECONFIG file found: $KUBECONFIG${NC}"

# Test cluster connectivity
echo -e "\n${YELLOW}2. Testing cluster connectivity...${NC}"

# Get current context
CURRENT_CONTEXT=$(kubectl config current-context)
echo "Current context: $CURRENT_CONTEXT"

# Test basic connectivity
if kubectl cluster-info >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Cluster is accessible${NC}"
else
    echo -e "${RED}❌ Cannot connect to cluster${NC}"
    exit 1
fi

# Check if Kro CRDs are installed
echo -e "\n${YELLOW}3. Checking Kro installation...${NC}"

if kubectl get crd resourcegraphdefinitions.kro.run >/dev/null 2>&1; then
    echo -e "${GREEN}✅ ResourceGraphDefinition CRD is installed${NC}"
else
    echo -e "${RED}❌ ResourceGraphDefinition CRD is not installed${NC}"
    echo "Please install Kro controller first"
    exit 1
fi

# Check for any Kro-related CRDs
KRO_CRDS=$(kubectl get crd | grep kro.run | wc -l)
if [ "$KRO_CRDS" -gt 0 ]; then
    echo -e "${GREEN}✅ Found $KRO_CRDS Kro CRD(s)${NC}"
    kubectl get crd | grep kro.run
else
    echo -e "${RED}❌ No Kro CRDs found${NC}"
    exit 1
fi

# Check Kro controller pods
echo -e "\n${YELLOW}4. Checking Kro controller status...${NC}"

KRO_PODS=$(kubectl get pods -A -l app.kubernetes.io/name=kro --no-headers 2>/dev/null | wc -l)
if [ "$KRO_PODS" -gt 0 ]; then
    echo -e "${GREEN}✅ Kro controller pods are running${NC}"
    kubectl get pods -A -l app.kubernetes.io/name=kro
else
    echo -e "${YELLOW}⚠️  No Kro controller pods found${NC}"
    echo "Checking for alternative Kro installations..."
    
    # Check for Kro in kro-system namespace
    if kubectl get namespace kro-system >/dev/null 2>&1; then
        KRO_SYSTEM_PODS=$(kubectl get pods -n kro-system --no-headers 2>/dev/null | wc -l)
        if [ "$KRO_SYSTEM_PODS" -gt 0 ]; then
            echo -e "${GREEN}✅ Kro controller found in kro-system namespace${NC}"
            kubectl get pods -n kro-system
        fi
    fi
fi

# Test ResourceGraphDefinition discovery
echo -e "\n${YELLOW}5. Testing Kro resource discovery...${NC}"

RESOURCE_GRAPH_DEFS=$(kubectl get resourcegraphdefinitions -A --no-headers 2>/dev/null | wc -l)
if [ "$RESOURCE_GRAPH_DEFS" -gt 0 ]; then
    echo -e "${GREEN}✅ Found $RESOURCE_GRAPH_DEFS ResourceGraphDefinition(s)${NC}"
    echo "Sample ResourceGraphDefinitions:"
    kubectl get resourcegraphdefinitions -A --no-headers | head -5
else
    echo -e "${YELLOW}⚠️  No ResourceGraphDefinitions found${NC}"
fi

# Test for any Kro instances (the actual resources created from ResourceGraphDefinitions)
echo "Checking for Kro instances..."
for rgd in $(kubectl get resourcegraphdefinitions --no-headers -o custom-columns=":metadata.name" 2>/dev/null); do
    # Extract the kind from the RGD name (e.g., cicdpipeline.kro.run -> CICDPipeline)
    kind=$(echo "$rgd" | cut -d'.' -f1)
    # Convert to proper case (first letter uppercase)
    kind_proper=$(echo "$kind" | sed 's/./\U&/')
    
    # Try to find instances of this kind
    instances=$(kubectl get "$kind_proper" -A --no-headers 2>/dev/null | wc -l || echo "0")
    if [ "$instances" -gt 0 ]; then
        echo -e "${GREEN}✅ Found $instances instance(s) of $kind_proper${NC}"
    fi
done

# Check RBAC configuration
echo -e "\n${YELLOW}6. Checking RBAC configuration...${NC}"

# Check if backstage namespace exists
if kubectl get namespace "$BACKSTAGE_NAMESPACE" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Backstage namespace exists${NC}"
else
    echo -e "${YELLOW}⚠️  Backstage namespace does not exist${NC}"
    echo "Creating backstage namespace..."
    kubectl create namespace "$BACKSTAGE_NAMESPACE"
    echo -e "${GREEN}✅ Created backstage namespace${NC}"
fi

# Check if service account exists
if kubectl get serviceaccount "$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Backstage service account exists${NC}"
else
    echo -e "${YELLOW}⚠️  Backstage service account does not exist${NC}"
    echo "Please apply the RBAC configuration: kubectl apply -f k8s-rbac/backstage-kro-rbac.yaml"
fi

# Check ClusterRole
if kubectl get clusterrole backstage-kro-reader >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Backstage ClusterRole exists${NC}"
else
    echo -e "${YELLOW}⚠️  Backstage ClusterRole does not exist${NC}"
    echo "Please apply the RBAC configuration: kubectl apply -f k8s-rbac/backstage-kro-rbac.yaml"
fi

# Test permissions with service account (if it exists)
if kubectl get serviceaccount "$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" >/dev/null 2>&1; then
    echo -e "\n${YELLOW}7. Testing service account permissions...${NC}"
    
    # Test ResourceGraphDefinition access
    if kubectl auth can-i get resourcegraphdefinitions --as=system:serviceaccount:$BACKSTAGE_NAMESPACE:$SERVICE_ACCOUNT_NAME >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Service account can access ResourceGraphDefinitions${NC}"
    else
        echo -e "${RED}❌ Service account cannot access ResourceGraphDefinitions${NC}"
    fi
    
    # Test access to Kro instances (check a few common ones)
    for rgd in $(kubectl get resourcegraphdefinitions --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -3); do
        kind=$(echo "$rgd" | cut -d'.' -f1)
        kind_proper=$(echo "$kind" | sed 's/./\U&/')
        
        if kubectl auth can-i get "$kind_proper" --as=system:serviceaccount:$BACKSTAGE_NAMESPACE:$SERVICE_ACCOUNT_NAME >/dev/null 2>&1; then
            echo -e "${GREEN}✅ Service account can access $kind_proper instances${NC}"
        else
            echo -e "${YELLOW}⚠️  Service account cannot access $kind_proper instances${NC}"
        fi
    done
    
    # Test basic Kubernetes resource access
    if kubectl auth can-i get pods --as=system:serviceaccount:$BACKSTAGE_NAMESPACE:$SERVICE_ACCOUNT_NAME >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Service account can access Pods${NC}"
    else
        echo -e "${RED}❌ Service account cannot access Pods${NC}"
    fi
fi

# Generate service account token for configuration
echo -e "\n${YELLOW}8. Service account token information...${NC}"

if kubectl get serviceaccount "$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" >/dev/null 2>&1; then
    # Check if token secret exists (for older Kubernetes versions)
    TOKEN_SECRET=$(kubectl get serviceaccount "$SERVICE_ACCOUNT_NAME" -n "$BACKSTAGE_NAMESPACE" -o jsonpath='{.secrets[0].name}' 2>/dev/null || echo "")
    
    if [ -n "$TOKEN_SECRET" ]; then
        echo "Token secret found: $TOKEN_SECRET"
        echo "To get the token for configuration:"
        echo "kubectl get secret $TOKEN_SECRET -n $BACKSTAGE_NAMESPACE -o jsonpath='{.data.token}' | base64 -d"
    else
        echo "No token secret found (Kubernetes 1.24+)"
        echo "Create a token manually:"
        echo "kubectl create token $SERVICE_ACCOUNT_NAME -n $BACKSTAGE_NAMESPACE --duration=8760h"
    fi
else
    echo "Service account not found. Please apply RBAC configuration first."
fi

# Environment variable suggestions
echo -e "\n${YELLOW}9. Environment variable configuration...${NC}"

CLUSTER_URL=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[0].name}')

echo "Suggested environment variables for app-config.yaml:"
echo "K8S_CLUSTER_URL=$CLUSTER_URL"
echo "K8S_CLUSTER_NAME=$CLUSTER_NAME"
echo "K8S_SERVICE_ACCOUNT_TOKEN=<token-from-step-8>"

# Get cluster CA data
CA_DATA=$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
if [ -n "$CA_DATA" ]; then
    echo "K8S_CLUSTER_CA_DATA=$CA_DATA"
fi

echo -e "\n${GREEN}✅ Connectivity test completed!${NC}"
echo -e "\nNext steps:"
echo "1. Apply RBAC configuration if not already done: kubectl apply -f k8s-rbac/backstage-kro-rbac.yaml"
echo "2. Set the environment variables shown above"
echo "3. Restart Backstage to pick up the new configuration"
echo "4. Verify ResourceGroups appear in the Backstage catalog"