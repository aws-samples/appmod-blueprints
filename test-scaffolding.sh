#!/bin/bash

# Backstage Scaffolding Simulation Script
# This script simulates what Backstage does when creating an S3 bucket template

set -e

# Configuration (same as Backstage environment)
GITLAB_HOST="d2jl8inhwf8wdv.cloudfront.net"
GITLAB_TOKEN="glpat-SIQhHhoNuFQk3lTni8VndW86MQp1OjIH.01.0w1y33w8j"
GITLAB_USER="user1"
BUCKET_NAME="test-bucket-script-$(date +%s)"
TEMP_DIR="/tmp/scaffolding-test-$$"

echo "🚀 Starting Backstage Scaffolding Simulation"
echo "📦 Bucket Name: $BUCKET_NAME"
echo "🌐 GitLab Host: $GITLAB_HOST"
echo "👤 GitLab User: $GITLAB_USER"
echo ""

# Step 1: Create temporary directory and generate files
echo "📁 Step 1: Creating template files..."
mkdir -p "$TEMP_DIR/manifests"

# Generate catalog-info.yaml
cat > "$TEMP_DIR/catalog-info.yaml" << EOF
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: $BUCKET_NAME
  description: S3 bucket configuration for $BUCKET_NAME
  annotations:
    backstage.io/kubernetes-id: $BUCKET_NAME
spec:
  type: service
  lifecycle: experimental
  owner: platform-team
EOF

# Generate S3 bucket manifest
cat > "$TEMP_DIR/manifests/oam-s3-bucket.yaml" << EOF
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: $BUCKET_NAME
  namespace: default
spec:
  components:
    - name: s3-bucket
      type: aws-s3-bucket
      properties:
        bucket: $BUCKET_NAME
        region: us-west-2
        acl: private
EOF

echo "✅ Template files generated"

# Step 2: Test GitLab API - Create Repository
echo ""
echo "🔧 Step 2: Testing GitLab API - Create Repository..."

# Get user ID first
echo "🔍 Getting GitLab user ID..."
USER_RESPONSE=$(curl -s -H "Private-Token: $GITLAB_TOKEN" \
  "https://$GITLAB_HOST/api/v4/users?username=$GITLAB_USER")

USER_ID=$(echo "$USER_RESPONSE" | jq -r '.[0].id // empty')

if [ -z "$USER_ID" ] || [ "$USER_ID" = "null" ]; then
  echo "❌ Failed to get user ID. Response: $USER_RESPONSE"
  exit 1
fi

echo "✅ User ID: $USER_ID"

# Create repository
echo "🏗️  Creating GitLab repository..."
CREATE_RESPONSE=$(curl -s -w "%{http_code}" -H "Private-Token: $GITLAB_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$BUCKET_NAME\",
    \"namespace_id\": $USER_ID,
    \"description\": \"S3 bucket configuration for $BUCKET_NAME\",
    \"visibility\": \"private\",
    \"initialize_with_readme\": true
  }" \
  "https://$GITLAB_HOST/api/v4/projects")

HTTP_CODE="${CREATE_RESPONSE: -3}"
RESPONSE_BODY="${CREATE_RESPONSE%???}"

echo "📊 HTTP Code: $HTTP_CODE"

if [ "$HTTP_CODE" = "201" ]; then
  echo "✅ Repository created successfully"
  REPO_URL=$(echo "$RESPONSE_BODY" | jq -r '.http_url_to_repo')
  echo "🔗 Repository URL: $REPO_URL"
else
  echo "❌ Failed to create repository. Response: $RESPONSE_BODY"
  exit 1
fi

# Step 3: Test Git Operations
echo ""
echo "🔧 Step 3: Testing Git Operations..."

cd "$TEMP_DIR"

# Clone the repository with authentication
echo "📥 Cloning repository with authentication..."
REPO_URL_WITH_AUTH="https://oauth2:$GITLAB_TOKEN@$GITLAB_HOST/$GITLAB_USER/$BUCKET_NAME.git"
git clone "$REPO_URL_WITH_AUTH" repo
cd repo

# Copy files
echo "📋 Copying template files..."
cp ../catalog-info.yaml .
cp -r ../manifests .

# Git operations
echo "📝 Adding files to git..."
git add .

echo "💾 Committing files..."
git commit -m "Add S3 bucket configuration from Backstage template"

echo "🚀 Pushing to GitLab..."
# Use timeout to avoid hanging
timeout 30s git push origin main || {
  echo "⚠️  Git push timed out after 30 seconds"
  echo "🔍 This simulates the Backstage timeout issue"
}

# Step 4: Verify repository contents
echo ""
echo "🔧 Step 4: Verifying repository contents via API..."
sleep 2  # Give GitLab time to process

FILES_RESPONSE=$(curl -s -H "Private-Token: $GITLAB_TOKEN" \
  "https://$GITLAB_HOST/api/v4/projects/$(echo "$RESPONSE_BODY" | jq -r '.id')/repository/tree")

echo "📁 Repository contents:"
echo "$FILES_RESPONSE" | jq -r '.[] | "  - \(.name) (\(.type))"'

# Cleanup
echo ""
echo "🧹 Cleaning up..."
cd /
rm -rf "$TEMP_DIR"

echo ""
echo "🎉 Scaffolding simulation completed!"
echo "📝 Summary:"
echo "  - Repository creation: ✅ Success"
echo "  - File generation: ✅ Success" 
echo "  - Git push: ⚠️  May timeout (this is the Backstage issue)"
echo ""
echo "🔗 Repository: https://$GITLAB_HOST/$GITLAB_USER/$BUCKET_NAME"
