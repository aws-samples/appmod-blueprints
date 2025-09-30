#!/bin/bash

# Validation script to ensure the Backstage template is properly simplified
# This script checks that the template only creates the Kro instance and doesn't include setup workflows

set -e

TEMPLATE_FILE="template-cicd-pipeline.yaml"

echo "Validating Backstage template simplification..."

# Check that the template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "ERROR: Template file $TEMPLATE_FILE not found"
    exit 1
fi

# Count the number of kube:apply actions
KUBE_APPLY_COUNT=$(grep -c "action: kube:apply" "$TEMPLATE_FILE" || echo "0")

echo "Number of kube:apply actions found: $KUBE_APPLY_COUNT"

# Should only have 1 kube:apply action (for the Kro instance)
if [ "$KUBE_APPLY_COUNT" -ne 1 ]; then
    echo "ERROR: Expected exactly 1 kube:apply action, found $KUBE_APPLY_COUNT"
    echo "The template should only create the Kro CICDPipeline instance"
    exit 1
fi

# Check that the single kube:apply creates a CICDPipeline
if ! grep -A 10 "action: kube:apply" "$TEMPLATE_FILE" | grep -q "kind: CICDPipeline"; then
    echo "ERROR: The kube:apply action should create a CICDPipeline resource"
    exit 1
fi

# Check that there are no Workflow resources in the template
if grep -q "kind: Workflow" "$TEMPLATE_FILE"; then
    echo "ERROR: Template should not contain Workflow resources - these should be in the Kro RGD"
    exit 1
fi

# Check that there are no workflow templates defined in the template
if grep -q "templates:" "$TEMPLATE_FILE"; then
    echo "ERROR: Template should not contain workflow templates - these should be in the Kro RGD"
    exit 1
fi

# Check that ECR secret creation is not in the template
if grep -q "create-ecr-secret" "$TEMPLATE_FILE"; then
    echo "ERROR: ECR secret creation should be handled by Kro RGD, not in the template"
    exit 1
fi

# Check that GitLab webhook creation is not in the template
if grep -q "create-gitlab-webhook" "$TEMPLATE_FILE"; then
    echo "ERROR: GitLab webhook creation should be handled by Kro RGD, not in the template"
    exit 1
fi

# Check that cache warmup is not in the template
if grep -q "warmup-build-cache" "$TEMPLATE_FILE"; then
    echo "ERROR: Cache warmup should be handled by Kro RGD, not in the template"
    exit 1
fi

# Verify the template has the expected structure
EXPECTED_STEPS=(
    "fetchSystem"
    "fetch-base"
    "publish"
    "apply-kro-instance"
    "create-argocd-app"
    "register"
)

echo ""
echo "Checking template steps structure..."

for step in "${EXPECTED_STEPS[@]}"; do
    if grep -q "id: $step" "$TEMPLATE_FILE"; then
        echo "✅ Step '$step' found"
    else
        echo "❌ Step '$step' missing"
        exit 1
    fi
done

# Check that there are no unexpected workflow-related steps
UNEXPECTED_STEPS=(
    "apply-workflow-execution"
    "setup-ecr-credentials"
    "setup-gitlab-webhook"
    "warmup-cache"
)

echo ""
echo "Checking for unexpected workflow steps..."

for step in "${UNEXPECTED_STEPS[@]}"; do
    if grep -q "id: $step" "$TEMPLATE_FILE"; then
        echo "❌ Unexpected step '$step' found - should be in Kro RGD"
        exit 1
    else
        echo "✅ Step '$step' correctly not present"
    fi
done

echo ""
echo "🎉 Template simplification validation passed!"
echo ""
echo "Summary:"
echo "- Template contains exactly 1 kube:apply action"
echo "- kube:apply creates only CICDPipeline resource"
echo "- No Workflow resources in template"
echo "- No workflow templates in template"
echo "- Setup tasks moved to Kro RGD"
echo "- All expected steps present"
echo "- No unexpected workflow steps"
echo ""
echo "The template is now properly simplified and delegates all setup work to the Kro RGD."