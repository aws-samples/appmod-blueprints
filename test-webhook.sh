#!/bin/bash

# Test script for GitLab webhook creation
# Based on the workflow code

# Configuration (update these values)
gitlab_hostname="d15rvat21gcp87.cloudfront.net"
gitlab_username="user1"
app_name="rust"
webhook_url="https://dcu3gsco485x8.cloudfront.net/argo-events/rust-cicd"

# Get GitLab token from Kubernetes secret
echo "Getting GitLab token from Kubernetes secret..."
gitlab_token=$(kubectl get secret gitlab-credentials -n team-rust -o jsonpath='{.data.GITLAB_TOKEN}' | base64 -d)

if [ -z "$gitlab_token" ]; then
    echo "ERROR: Could not get GitLab token from secret"
    exit 1
fi

# Construct API URL
api_url="https://$gitlab_hostname/api/v4/projects/$gitlab_username%2F$app_name/hooks"

echo "=== GitLab Webhook Test ==="
echo "GitLab Hostname: $gitlab_hostname"
echo "GitLab Username: $gitlab_username"
echo "App Name: $app_name"
echo "API URL: $api_url"
echo "Webhook URL: $webhook_url"
echo "GitLab Token: ${gitlab_token:0:10}..."
echo ""

# Test 1: Check if we can access the project
echo "=== Test 1: Check project access ==="
project_response=$(curl -k -X 'GET' "https://$gitlab_hostname/api/v4/projects/$gitlab_username%2F$app_name" \
  -H "accept: application/json" \
  -H "Authorization: Bearer $gitlab_token" \
  -w "HTTP_CODE:%{http_code}" 2>/dev/null)

project_http_code=$(echo "$project_response" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2)
project_body=$(echo "$project_response" | sed 's/HTTP_CODE:[0-9]*$//')

echo "Project HTTP Code: $project_http_code"
if [ "$project_http_code" = "200" ]; then
    echo "✅ Project access successful"
    echo "Project ID: $(echo "$project_body" | jq -r '.id' 2>/dev/null || echo 'N/A')"
else
    echo "❌ Project access failed"
    echo "Response: $project_body"
fi
echo ""

# Test 2: List existing webhooks
echo "=== Test 2: List existing webhooks ==="
existing_webhooks=$(curl -k -X 'GET' "$api_url" \
  -H "accept: application/json" \
  -H "Authorization: Bearer $gitlab_token" \
  -w "HTTP_CODE:%{http_code}" 2>/dev/null)

hooks_http_code=$(echo "$existing_webhooks" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2)
hooks_body=$(echo "$existing_webhooks" | sed 's/HTTP_CODE:[0-9]*$//')

echo "Webhooks HTTP Code: $hooks_http_code"
if [ "$hooks_http_code" = "200" ]; then
    echo "✅ Webhook list successful"
    echo "Existing webhooks: $hooks_body"
    webhook_exists=$(echo "$hooks_body" | jq -r --arg url "$webhook_url" '.[] | select(.url == $url) | .id' 2>/dev/null || echo "")
    if [ -n "$webhook_exists" ] && [ "$webhook_exists" != "null" ]; then
        echo "Found existing webhook with ID: $webhook_exists"
    else
        echo "No existing webhook found for URL: $webhook_url"
    fi
else
    echo "❌ Webhook list failed"
    echo "Response: $hooks_body"
fi
echo ""

# Test 3: Create webhook (only if none exists)
if [ -z "$webhook_exists" ] || [ "$webhook_exists" = "null" ]; then
    echo "=== Test 3: Create new webhook ==="
    webhook_response=$(curl -k -X 'POST' "$api_url" \
      -H "accept: application/json" \
      -H "Authorization: Bearer $gitlab_token" \
      -H "Content-Type: application/json" \
      -d '{
        "url": "'$webhook_url'",
        "push_events": true,
        "issues_events": false,
        "merge_requests_events": false,
        "tag_push_events": false,
        "note_events": false,
        "job_events": false,
        "pipeline_events": false,
        "wiki_page_events": false,
        "deployment_events": false,
        "releases_events": false,
        "subgroup_events": false,
        "enable_ssl_verification": false,
        "token": "",
        "push_events_branch_filter": "main"
      }' -w "HTTP_CODE:%{http_code}" 2>/dev/null)
    
    create_http_code=$(echo "$webhook_response" | grep -o "HTTP_CODE:[0-9]*" | cut -d: -f2)
    create_body=$(echo "$webhook_response" | sed 's/HTTP_CODE:[0-9]*$//')
    
    echo "Create HTTP Code: $create_http_code"
    if [ "$create_http_code" = "201" ]; then
        echo "✅ Webhook created successfully"
        webhook_id=$(echo "$create_body" | jq -r '.id' 2>/dev/null || echo 'N/A')
        echo "Webhook ID: $webhook_id"
    else
        echo "❌ Webhook creation failed"
        echo "Response: $create_body"
    fi
else
    echo "=== Test 3: Skipped (webhook already exists) ==="
fi

echo ""
echo "=== Test Complete ==="
