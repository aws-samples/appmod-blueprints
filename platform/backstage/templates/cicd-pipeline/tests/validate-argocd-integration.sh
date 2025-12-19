#!/bin/bash

# Validation script to ensure ArgoCD integration is properly configured
# This script checks that ArgoCD applications are correctly set up for the new Kro-based structure

set -e

TEMPLATE_FILE="template-cicd-pipeline.yaml"
DEV_APP_FILE="skeleton/manifests/argo-app-dev.yaml"
PROD_APP_FILE="skeleton/manifests/argo-app-prod.yaml"

echo "Validating ArgoCD integration..."

# Check that the template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "ERROR: Template file $TEMPLATE_FILE not found"
    exit 1
fi

# Check that ArgoCD application files exist
if [ ! -f "$DEV_APP_FILE" ]; then
    echo "ERROR: Dev ArgoCD application file $DEV_APP_FILE not found"
    exit 1
fi

if [ ! -f "$PROD_APP_FILE" ]; then
    echo "ERROR: Prod ArgoCD application file $PROD_APP_FILE not found"
    exit 1
fi

echo "✅ All required files found"

# Check that the template has the ArgoCD creation step
if ! grep -q "id: create-argocd-app" "$TEMPLATE_FILE"; then
    echo "ERROR: Template missing create-argocd-app step"
    exit 1
fi

echo "✅ ArgoCD creation step found in template"

# Check that the ArgoCD step uses the correct action
if ! grep -A 5 "id: create-argocd-app" "$TEMPLATE_FILE" | grep -q "action: argocd:create-resources"; then
    echo "ERROR: ArgoCD step should use argocd:create-resources action"
    exit 1
fi

echo "✅ ArgoCD step uses correct action"

# Check that the ArgoCD step has proper configuration
ARGOCD_CONFIG_CHECKS=(
    "appName:"
    "namespace:"
    "argoInstance:"
    "projectName:"
    "repoUrl:"
    "path:"
    "syncPolicy:"
)

echo ""
echo "Checking ArgoCD step configuration..."

for check in "${ARGOCD_CONFIG_CHECKS[@]}"; do
    if grep -A 20 "id: create-argocd-app" "$TEMPLATE_FILE" | grep -q "$check"; then
        echo "✅ Configuration '$check' found"
    else
        echo "❌ Configuration '$check' missing"
        exit 1
    fi
done

# Check that ArgoCD applications use deployment path parameter
if ! grep -q "path: \${{values.deployment_path}}" "$DEV_APP_FILE"; then
    echo "ERROR: Dev ArgoCD application should use deployment_path parameter"
    exit 1
fi

if ! grep -q "path: \${{values.deployment_path}}" "$PROD_APP_FILE"; then
    echo "ERROR: Prod ArgoCD application should use deployment_path parameter"
    exit 1
fi

echo "✅ ArgoCD applications use deployment path parameter"

# Check that ArgoCD applications have proper labels and annotations
REQUIRED_LABELS=(
    "app.kubernetes.io/name:"
    "app.kubernetes.io/component:"
    "app.kubernetes.io/managed-by:"
    "backstage.io/template-name:"
)

REQUIRED_ANNOTATIONS=(
    "backstage.io/created-by:"
    "cicd.kro.run/application-name:"
    "cicd.kro.run/environment:"
)

echo ""
echo "Checking ArgoCD application metadata..."

for label in "${REQUIRED_LABELS[@]}"; do
    if grep -q "$label" "$DEV_APP_FILE" && grep -q "$label" "$PROD_APP_FILE"; then
        echo "✅ Label '$label' found in both applications"
    else
        echo "❌ Label '$label' missing from one or both applications"
        exit 1
    fi
done

for annotation in "${REQUIRED_ANNOTATIONS[@]}"; do
    if grep -q "$annotation" "$DEV_APP_FILE" && grep -q "$annotation" "$PROD_APP_FILE"; then
        echo "✅ Annotation '$annotation' found in both applications"
    else
        echo "❌ Annotation '$annotation' missing from one or both applications"
        exit 1
    fi
done

# Check that ArgoCD applications have proper sync policies
SYNC_POLICY_CHECKS=(
    "automated:"
    "prune: true"
    "selfHeal: true"
    "CreateNamespace=true"
    "ApplyOutOfSyncOnly=true"
    "retry:"
)

echo ""
echo "Checking ArgoCD sync policies..."

for check in "${SYNC_POLICY_CHECKS[@]}"; do
    if grep -q "$check" "$DEV_APP_FILE" && grep -q "$check" "$PROD_APP_FILE"; then
        echo "✅ Sync policy '$check' found in both applications"
    else
        echo "❌ Sync policy '$check' missing from one or both applications"
        exit 1
    fi
done

# Check that output links include ArgoCD applications
EXPECTED_LINKS=(
    "ArgoCD CI/CD Pipeline"
    "ArgoCD Dev Application"
    "ArgoCD Prod Application"
)

echo ""
echo "Checking output links..."

for link in "${EXPECTED_LINKS[@]}"; do
    if grep -q "title: $link" "$TEMPLATE_FILE"; then
        echo "✅ Output link '$link' found"
    else
        echo "❌ Output link '$link' missing"
        exit 1
    fi
done

# Check that text output includes ArgoCD information
if grep -q "ArgoCD Applications:" "$TEMPLATE_FILE"; then
    echo "✅ Text output includes ArgoCD information"
else
    echo "❌ Text output missing ArgoCD information"
    exit 1
fi

echo ""
echo "🎉 ArgoCD integration validation passed!"
echo ""
echo "Summary:"
echo "- Template has create-argocd-app step with correct action"
echo "- ArgoCD step has proper configuration"
echo "- ArgoCD applications use deployment path parameter"
echo "- ArgoCD applications have proper metadata (labels/annotations)"
echo "- ArgoCD applications have proper sync policies"
echo "- Output links include ArgoCD applications"
echo "- Text output includes ArgoCD information"
echo ""
echo "The ArgoCD integration is properly configured for the new Kro-based structure."