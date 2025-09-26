#!/bin/bash

# Validation script for template parameter handling and validation
# This script validates that the template properly handles parameters and validation

set -e

TEMPLATE_FILE="template-cicd-pipeline.yaml"

echo "Validating template parameter handling and validation..."

# Check if template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "ERROR: Template file $TEMPLATE_FILE not found"
    exit 1
fi

echo "✓ Template file found"

# Validate parameter structure
echo "Checking parameter structure..."

# Check for proper parameter sections
PARAMETER_SECTIONS=$(yq '.spec.parameters | length' "$TEMPLATE_FILE")
if [ "$PARAMETER_SECTIONS" -ne 3 ]; then
    echo "ERROR: Expected 3 parameter sections (Application, AWS, Paths), found $PARAMETER_SECTIONS"
    exit 1
fi

echo "✓ Found $PARAMETER_SECTIONS parameter sections"

# Check required parameters
REQUIRED_PARAMS=$(yq '.spec.parameters[0].required[]' "$TEMPLATE_FILE")
if [ "$REQUIRED_PARAMS" != "appname" ]; then
    echo "ERROR: Expected 'appname' as required parameter, found: $REQUIRED_PARAMS"
    exit 1
fi

echo "✓ Required parameters correctly defined"

# Check parameter validation patterns
echo "Checking parameter validation patterns..."

# Check appname pattern
APPNAME_PATTERN=$(yq '.spec.parameters[0].properties.appname.pattern' "$TEMPLATE_FILE")
if [ -z "$APPNAME_PATTERN" ]; then
    echo "ERROR: appname parameter missing validation pattern"
    exit 1
fi

echo "✓ appname validation pattern found: $APPNAME_PATTERN"

# Check dockerfile_path pattern
DOCKERFILE_PATTERN=$(yq '.spec.parameters[2].properties.dockerfile_path.pattern' "$TEMPLATE_FILE")
if [ -z "$DOCKERFILE_PATTERN" ]; then
    echo "ERROR: dockerfile_path parameter missing validation pattern"
    exit 1
fi

# Verify the pattern is correct
EXPECTED_DOCKERFILE_PATTERN='^\.(/[a-zA-Z0-9_-]+)*/?$'
if [ "$DOCKERFILE_PATTERN" != "$EXPECTED_DOCKERFILE_PATTERN" ]; then
    echo "ERROR: dockerfile_path pattern incorrect. Expected: $EXPECTED_DOCKERFILE_PATTERN, Found: $DOCKERFILE_PATTERN"
    exit 1
fi

echo "✓ dockerfile_path validation pattern found: $DOCKERFILE_PATTERN"

# Check deployment_path pattern
DEPLOYMENT_PATTERN=$(yq '.spec.parameters[2].properties.deployment_path.pattern' "$TEMPLATE_FILE")
if [ -z "$DEPLOYMENT_PATTERN" ]; then
    echo "ERROR: deployment_path parameter missing validation pattern"
    exit 1
fi

echo "✓ deployment_path validation pattern found: $DEPLOYMENT_PATTERN"

# Check default values
echo "Checking default values..."

# Check aws_region default
AWS_REGION_DEFAULT=$(yq '.spec.parameters[1].properties.aws_region.default' "$TEMPLATE_FILE")
if [ "$AWS_REGION_DEFAULT" != "us-west-2" ]; then
    echo "ERROR: aws_region default should be 'us-west-2', found: $AWS_REGION_DEFAULT"
    exit 1
fi

echo "✓ aws_region default value: $AWS_REGION_DEFAULT"

# Check cluster_name default
CLUSTER_DEFAULT=$(yq '.spec.parameters[1].properties.cluster_name.default' "$TEMPLATE_FILE")
if [ "$CLUSTER_DEFAULT" != "modern-engineering" ]; then
    echo "ERROR: cluster_name default should be 'modern-engineering', found: $CLUSTER_DEFAULT"
    exit 1
fi

echo "✓ cluster_name default value: $CLUSTER_DEFAULT"

# Check dockerfile_path default
DOCKERFILE_DEFAULT=$(yq '.spec.parameters[2].properties.dockerfile_path.default' "$TEMPLATE_FILE")
if [ "$DOCKERFILE_DEFAULT" != "." ]; then
    echo "ERROR: dockerfile_path default should be '.', found: $DOCKERFILE_DEFAULT"
    exit 1
fi

echo "✓ dockerfile_path default value: $DOCKERFILE_DEFAULT"

# Check deployment_path default
DEPLOYMENT_DEFAULT=$(yq '.spec.parameters[2].properties.deployment_path.default' "$TEMPLATE_FILE")
if [ "$DEPLOYMENT_DEFAULT" != "./deployment" ]; then
    echo "ERROR: deployment_path default should be './deployment', found: $DEPLOYMENT_DEFAULT"
    exit 1
fi

echo "✓ deployment_path default value: $DEPLOYMENT_DEFAULT"

# Check parameter validation step
echo "Checking parameter validation step..."

VALIDATION_STEP=$(yq '.spec.steps[] | select(.id == "validate-parameters")' "$TEMPLATE_FILE")
if [ -z "$VALIDATION_STEP" ]; then
    echo "ERROR: Parameter validation step not found"
    exit 1
fi

echo "✓ Parameter validation step found"

# Check Kro instance validation step
KIRO_VALIDATION_STEP=$(yq '.spec.steps[] | select(.id == "validate-kro-instance")' "$TEMPLATE_FILE")
if [ -z "$KIRO_VALIDATION_STEP" ]; then
    echo "ERROR: Kro instance validation step not found"
    exit 1
fi

echo "✓ Kro instance validation step found"

# Check parameter templating in Kro manifest
echo "Checking parameter templating in Kro manifest..."

# Check that all required parameters are templated
KIRO_MANIFEST=$(yq '.spec.steps[] | select(.id == "apply-kro-instance") | .input.manifest' "$TEMPLATE_FILE")

# Check for parameter references
if ! echo "$KIRO_MANIFEST" | grep -q '\${{ parameters\.appname }}'; then
    echo "ERROR: appname parameter not properly templated in Kro manifest"
    exit 1
fi

if ! echo "$KIRO_MANIFEST" | grep -q '\${{ parameters\.aws_region }}'; then
    echo "ERROR: aws_region parameter not properly templated in Kro manifest"
    exit 1
fi

if ! echo "$KIRO_MANIFEST" | grep -q '\${{ parameters\.cluster_name }}'; then
    echo "ERROR: cluster_name parameter not properly templated in Kro manifest"
    exit 1
fi

# Check for default value handling
if ! echo "$KIRO_MANIFEST" | grep -q 'parameters\.dockerfile_path | default'; then
    echo "ERROR: dockerfile_path default handling not found in Kro manifest"
    exit 1
fi

if ! echo "$KIRO_MANIFEST" | grep -q 'parameters\.deployment_path | default'; then
    echo "ERROR: deployment_path default handling not found in Kro manifest"
    exit 1
fi

echo "✓ All parameters properly templated in Kro manifest"

# Check output links parameter usage
echo "Checking output links parameter usage..."

OUTPUT_LINKS=$(yq '.spec.output.links' "$TEMPLATE_FILE")

if ! echo "$OUTPUT_LINKS" | grep -q '\${{ parameters\.appname }}'; then
    echo "ERROR: appname parameter not used in output links"
    exit 1
fi

if ! echo "$OUTPUT_LINKS" | grep -q '\${{ parameters\.aws_region }}'; then
    echo "ERROR: aws_region parameter not used in output links"
    exit 1
fi

if ! echo "$OUTPUT_LINKS" | grep -q '\${{ parameters\.cluster_name }}'; then
    echo "ERROR: cluster_name parameter not used in output links"
    exit 1
fi

echo "✓ Parameters properly used in output links"

# Check UI help text
echo "Checking UI help text..."

UI_HELP_COUNT=$(grep -c "ui:help" "$TEMPLATE_FILE" || true)
if [ "$UI_HELP_COUNT" -lt 4 ]; then
    echo "ERROR: Expected at least 4 ui:help entries, found $UI_HELP_COUNT"
    exit 1
fi

echo "✓ UI help text found for parameters ($UI_HELP_COUNT entries)"

# Check enum values for aws_region
AWS_REGION_ENUM=$(yq '.spec.parameters[1].properties.aws_region.enum | length' "$TEMPLATE_FILE")
if [ "$AWS_REGION_ENUM" -lt 5 ]; then
    echo "ERROR: Expected at least 5 AWS regions in enum, found $AWS_REGION_ENUM"
    exit 1
fi

echo "✓ AWS region enum values properly defined"

echo ""
echo "✅ All parameter validation checks passed!"
echo ""
echo "Summary:"
echo "- Template has 3 properly structured parameter sections"
echo "- Required parameters correctly defined (appname)"
echo "- Validation patterns implemented for critical parameters"
echo "- Default values properly set for optional parameters"
echo "- Parameter validation steps included in workflow"
echo "- All parameters properly templated in Kro manifest"
echo "- Default value handling implemented with fallbacks"
echo "- Output links properly reference parameters"
echo "- UI help text provided for user guidance"
echo "- AWS region enum provides valid options"
echo ""
echo "The template now properly handles parameter validation and templating according to requirements 7.2 and 7.4"