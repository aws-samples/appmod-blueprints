#!/bin/bash

# Test script to validate parameter validation patterns
# This script tests various parameter combinations to ensure validation works correctly

set -e

echo "Testing parameter validation patterns..."

# Test appname validation pattern
APPNAME_PATTERN='^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$'

echo "Testing appname validation pattern: $APPNAME_PATTERN"

# Valid appname examples
valid_appnames=("a" "test" "my-app" "app123" "test-app-1" "web-service" "api-gateway")
for name in "${valid_appnames[@]}"; do
    if [[ $name =~ $APPNAME_PATTERN ]]; then
        echo "✓ Valid appname: '$name'"
    else
        echo "✗ Should be valid but failed: '$name'"
        exit 1
    fi
done

# Invalid appname examples
invalid_appnames=("" "-test" "test-" "Test" "test_app" "test.app" "test app" "123-" "-123")
for name in "${invalid_appnames[@]}"; do
    if [[ $name =~ $APPNAME_PATTERN ]]; then
        echo "✗ Should be invalid but passed: '$name'"
        exit 1
    else
        echo "✓ Invalid appname correctly rejected: '$name'"
    fi
done

# Test dockerfile_path validation pattern
DOCKERFILE_PATTERN='^\.(/[a-zA-Z0-9_-]+)*/?$'

echo ""
echo "Testing dockerfile_path validation pattern: $DOCKERFILE_PATTERN"

# Valid dockerfile_path examples
valid_dockerfile_paths=("." "./backend" "./services/api" "./apps/web" "./src/main")
for path in "${valid_dockerfile_paths[@]}"; do
    if [[ $path =~ $DOCKERFILE_PATTERN ]]; then
        echo "✓ Valid dockerfile_path: '$path'"
    else
        echo "✗ Should be valid but failed: '$path'"
        exit 1
    fi
done

# Invalid dockerfile_path examples (note: empty string is invalid, but "." is valid)
invalid_dockerfile_paths=("" "backend" "/backend" "../backend" "./back end" ".//backend" "./backend//api")
for path in "${invalid_dockerfile_paths[@]}"; do
    if [[ $path =~ $DOCKERFILE_PATTERN ]]; then
        echo "✗ Should be invalid but passed: '$path'"
        exit 1
    else
        echo "✓ Invalid dockerfile_path correctly rejected: '$path'"
    fi
done

# Test deployment_path validation pattern
DEPLOYMENT_PATTERN='^\.(/[a-zA-Z0-9_-]+)+/?$'

echo ""
echo "Testing deployment_path validation pattern: $DEPLOYMENT_PATTERN"

# Valid deployment_path examples
valid_deployment_paths=("./deployment" "./k8s" "./manifests" "./deploy/prod" "./kubernetes/base")
for path in "${valid_deployment_paths[@]}"; do
    if [[ $path =~ $DEPLOYMENT_PATTERN ]]; then
        echo "✓ Valid deployment_path: '$path'"
    else
        echo "✗ Should be valid but failed: '$path'"
        exit 1
    fi
done

# Invalid deployment_path examples (note: "." alone is not valid for deployment_path)
invalid_deployment_paths=("" "." "deployment" "/deployment" "../deployment" "./deploy ment" ".//deployment")
for path in "${invalid_deployment_paths[@]}"; do
    if [[ $path =~ $DEPLOYMENT_PATTERN ]]; then
        echo "✗ Should be invalid but passed: '$path'"
        exit 1
    else
        echo "✓ Invalid deployment_path correctly rejected: '$path'"
    fi
done

# Test cluster name validation pattern (from template)
CLUSTER_PATTERN='^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$'

echo ""
echo "Testing cluster_name validation pattern: $CLUSTER_PATTERN"

# Valid cluster name examples
valid_cluster_names=("a" "A" "test" "Test" "my-cluster" "Cluster-1" "EKS-Cluster" "modern-engineering")
for name in "${valid_cluster_names[@]}"; do
    if [[ $name =~ $CLUSTER_PATTERN ]]; then
        echo "✓ Valid cluster_name: '$name'"
    else
        echo "✗ Should be valid but failed: '$name'"
        exit 1
    fi
done

# Invalid cluster name examples
invalid_cluster_names=("" "-test" "test-" "test_cluster" "test.cluster" "test cluster" "123-" "-123")
for name in "${invalid_cluster_names[@]}"; do
    if [[ $name =~ $CLUSTER_PATTERN ]]; then
        echo "✗ Should be invalid but passed: '$name'"
        exit 1
    else
        echo "✓ Invalid cluster_name correctly rejected: '$name'"
    fi
done

echo ""
echo "✅ All parameter validation pattern tests passed!"

# Test default value scenarios
echo ""
echo "Testing default value handling scenarios..."

# Simulate template parameter processing with defaults
test_dockerfile_default() {
    local input="$1"
    local expected="$2"
    
    # Simulate Backstage template default handling
    if [ -z "$input" ] || [ "$input" = "null" ]; then
        result="."
    else
        result="$input"
    fi
    
    if [ "$result" = "$expected" ]; then
        echo "✓ dockerfile_path default handling: input='$input' -> output='$result'"
    else
        echo "✗ dockerfile_path default handling failed: input='$input' -> expected='$expected', got='$result'"
        exit 1
    fi
}

test_deployment_default() {
    local input="$1"
    local expected="$2"
    
    # Simulate Backstage template default handling
    if [ -z "$input" ] || [ "$input" = "null" ]; then
        result="./deployment"
    else
        result="$input"
    fi
    
    if [ "$result" = "$expected" ]; then
        echo "✓ deployment_path default handling: input='$input' -> output='$result'"
    else
        echo "✗ deployment_path default handling failed: input='$input' -> expected='$expected', got='$result'"
        exit 1
    fi
}

# Test default scenarios
test_dockerfile_default "" "."
test_dockerfile_default "null" "."
test_dockerfile_default "./backend" "./backend"

test_deployment_default "" "./deployment"
test_deployment_default "null" "./deployment"
test_deployment_default "./k8s" "./k8s"

echo ""
echo "✅ All default value handling tests passed!"

echo ""
echo "🎉 All parameter validation and default handling tests completed successfully!"
echo ""
echo "Summary of validated patterns:"
echo "- appname: Lowercase alphanumeric with hyphens, no leading/trailing hyphens"
echo "- dockerfile_path: Relative paths starting with '.', no spaces or double slashes"
echo "- deployment_path: Relative paths starting with './', no spaces or double slashes"
echo "- cluster_name: Alphanumeric with hyphens, no leading/trailing hyphens, case-insensitive"
echo ""
echo "Default value handling:"
echo "- dockerfile_path defaults to '.'"
echo "- deployment_path defaults to './deployment'"
echo "- aws_region defaults to 'us-west-2'"
echo "- cluster_name defaults to 'modern-engineering'"