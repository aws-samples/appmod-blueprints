#!/bin/bash

# Validation script for CI/CD Pipeline Template Output Links and Catalog Registration
# This script validates that the template has proper output links and catalog registration

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/template-cicd-pipeline.yaml"
CATALOG_FILE="$SCRIPT_DIR/skeleton/catalog-info.yaml"

echo "🔍 Validating CI/CD Pipeline Template Output Links and Catalog Registration..."

# Check if template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "❌ ERROR: Template file not found: $TEMPLATE_FILE"
    exit 1
fi

# Check if catalog-info.yaml exists
if [ ! -f "$CATALOG_FILE" ]; then
    echo "❌ ERROR: Catalog info file not found: $CATALOG_FILE"
    exit 1
fi

echo "✅ Template files found"

# Validate output links section exists
if ! grep -q "output:" "$TEMPLATE_FILE"; then
    echo "❌ ERROR: Template missing output section"
    exit 1
fi

echo "✅ Output section found"

# Validate required output links
required_links=(
    "Open in catalog"
    "Kro CI/CD Pipeline Instance"
    "Argo Workflows - Provisioning"
    "Argo Workflows - CI/CD Pipeline"
    "Argo Workflows - Cache Warmup"
    "ArgoCD CI/CD Pipeline Application"
    "ECR Main Repository"
    "ECR Cache Repository"
    "IAM Role"
    "IAM Policy"
    "EKS Pod Identity Association"
    "EKS Cluster"
    "GitLab Repository"
    "Kubernetes Namespace"
)

echo "🔗 Validating output links..."

for link in "${required_links[@]}"; do
    if grep -q "title: $link" "$TEMPLATE_FILE"; then
        echo "  ✅ Found: $link"
    else
        echo "  ❌ Missing: $link"
        exit 1
    fi
done

# Validate URL patterns for key links
echo "🌐 Validating URL patterns..."

# Check Argo Workflows URLs
if grep -q "/argo-workflows/workflow-templates/" "$TEMPLATE_FILE"; then
    echo "  ✅ Argo Workflows URL pattern correct"
else
    echo "  ❌ Argo Workflows URL pattern incorrect"
    exit 1
fi

# Check ArgoCD URLs
if grep -q "/argocd/applications/argocd/" "$TEMPLATE_FILE"; then
    echo "  ✅ ArgoCD URL pattern correct"
else
    echo "  ❌ ArgoCD URL pattern incorrect"
    exit 1
fi

# Check ECR URLs
if grep -q "console.aws.amazon.com/ecr/repositories/private/" "$TEMPLATE_FILE"; then
    echo "  ✅ ECR URL pattern correct"
else
    echo "  ❌ ECR URL pattern incorrect"
    exit 1
fi

# Check IAM URLs
if grep -q "console.aws.amazon.com/iam/home" "$TEMPLATE_FILE"; then
    echo "  ✅ IAM URL pattern correct"
else
    echo "  ❌ IAM URL pattern incorrect"
    exit 1
fi

# Check EKS URLs
if grep -q "console.aws.amazon.com/eks/home" "$TEMPLATE_FILE"; then
    echo "  ✅ EKS URL pattern correct"
else
    echo "  ❌ EKS URL pattern incorrect"
    exit 1
fi

echo "📋 Validating catalog registration..."

# Validate catalog-info.yaml structure
if grep -q "kind: Component" "$CATALOG_FILE"; then
    echo "  ✅ Component kind found"
else
    echo "  ❌ Component kind missing"
    exit 1
fi

# Check for Kro-specific annotations
if grep -q "kro.run/resource-group" "$CATALOG_FILE"; then
    echo "  ✅ Kro resource group annotation found"
else
    echo "  ❌ Kro resource group annotation missing"
    exit 1
fi

# Check for AWS resource annotations
if grep -q "aws.amazon.com/ecr-main-repository" "$CATALOG_FILE"; then
    echo "  ✅ AWS ECR annotation found"
else
    echo "  ❌ AWS ECR annotation missing"
    exit 1
fi

# Check for Argo Workflows annotations
if grep -q "argo-workflows.cnoe.io/namespace" "$CATALOG_FILE"; then
    echo "  ✅ Argo Workflows annotation found"
else
    echo "  ❌ Argo Workflows annotation missing"
    exit 1
fi

# Check for proper labels
if grep -q "app.kubernetes.io/managed-by: kro" "$CATALOG_FILE"; then
    echo "  ✅ Kro managed-by label found"
else
    echo "  ❌ Kro managed-by label missing"
    exit 1
fi

# Validate text output section
echo "📝 Validating text output..."

if grep -q "Kro-based CI/CD Pipeline Configuration" "$TEMPLATE_FILE"; then
    echo "  ✅ Descriptive text output found"
else
    echo "  ❌ Descriptive text output missing"
    exit 1
fi

# Check for comprehensive information in text output
text_sections=(
    "Pipeline Overview"
    "AWS Resources"
    "Kubernetes Resources"
    "Argo Workflows Templates"
    "Build & Deployment Configuration"
    "GitLab Integration"
    "ArgoCD Applications"
    "Security Features"
    "Monitoring & Observability"
    "Next Steps"
)

for section in "${text_sections[@]}"; do
    if grep -q "$section" "$TEMPLATE_FILE"; then
        echo "  ✅ Found text section: $section"
    else
        echo "  ❌ Missing text section: $section"
        exit 1
    fi
done

# Validate parameter usage in URLs
echo "🔧 Validating parameter substitution..."

# Check that parameters are properly used in URLs
if grep -q '\${{ parameters\.appname }}' "$TEMPLATE_FILE"; then
    echo "  ✅ Application name parameter used in URLs"
else
    echo "  ❌ Application name parameter not used in URLs"
    exit 1
fi

if grep -q '\${{ parameters\.aws_region }}' "$TEMPLATE_FILE"; then
    echo "  ✅ AWS region parameter used in URLs"
else
    echo "  ❌ AWS region parameter not used in URLs"
    exit 1
fi

if grep -q '\${{ parameters\.cluster_name }}' "$TEMPLATE_FILE"; then
    echo "  ✅ Cluster name parameter used in URLs"
else
    echo "  ❌ Cluster name parameter not used in URLs"
    exit 1
fi

# Validate system entity references
if grep -q "steps\['fetchSystem'\]\.output\.entity\.spec\.hostname" "$TEMPLATE_FILE"; then
    echo "  ✅ System hostname reference found"
else
    echo "  ❌ System hostname reference missing"
    exit 1
fi

if grep -q "steps\['fetchSystem'\]\.output\.entity\.spec\.aws_account_id" "$TEMPLATE_FILE"; then
    echo "  ✅ AWS account ID reference found"
else
    echo "  ❌ AWS account ID reference missing"
    exit 1
fi

echo ""
echo "🎉 All validations passed!"
echo ""
echo "✅ Template output links are properly configured"
echo "✅ Catalog registration is properly structured"
echo "✅ URL patterns are correct for all tools"
echo "✅ Parameter substitution is working"
echo "✅ System entity references are correct"
echo "✅ Comprehensive information is provided"
echo ""
echo "The CI/CD Pipeline template is ready for use with proper output links and catalog registration!"