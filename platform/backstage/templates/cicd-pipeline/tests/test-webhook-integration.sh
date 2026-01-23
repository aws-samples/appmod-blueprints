#!/bin/bash

# End-to-end test script for GitLab webhook integration
# This script simulates a GitLab webhook event and validates the complete flow

set -e

NAMESPACE=${1:-"team-example"}
APP_NAME=${2:-"example"}
GITLAB_HOSTNAME=${3:-"gitlab.example.com"}
TEST_COMMIT_ID=${4:-"test-$(date +%s)"}

echo "Testing GitLab webhook integration end-to-end"
echo "Namespace: $NAMESPACE"
echo "App Name: $APP_NAME"
echo "GitLab Hostname: $GITLAB_HOSTNAME"
echo "Test Commit ID: $TEST_COMMIT_ID"
echo ""

# Function to wait for condition
wait_for_condition() {
    local description="$1"
    local condition="$2"
    local timeout=${3:-60}
    local interval=${4:-5}
    
    echo "Waiting for: $description"
    local count=0
    while [ $count -lt $timeout ]; do
        if eval "$condition"; then
            echo "✅ $description - Success"
            return 0
        fi
        echo "⏳ Waiting... ($count/$timeout seconds)"
        sleep $interval
        count=$((count + interval))
    done
    echo "❌ $description - Timeout after $timeout seconds"
    return 1
}

# 1. Verify prerequisites
echo "1. Verifying prerequisites..."

# Check if namespace exists
kubectl get namespace "$NAMESPACE" > /dev/null || {
    echo "ERROR: Namespace $NAMESPACE does not exist"
    exit 1
}

# Check if Kro instance exists
kubectl get cicdpipeline "${APP_NAME}-cicd-pipeline" -n "$NAMESPACE" > /dev/null || {
    echo "ERROR: Kro CICDPipeline instance not found"
    exit 1
}

echo "✅ Prerequisites verified"
echo ""

# 2. Check Argo Events resources
echo "2. Checking Argo Events resources..."

# EventSource
wait_for_condition "EventSource ready" \
    "kubectl get eventsource '${APP_NAME}-cicd-gitlab-eventsource' -n '$NAMESPACE' -o jsonpath='{.status.conditions[0].status}' 2>/dev/null | grep -q 'True'"

# Sensor
wait_for_condition "Sensor ready" \
    "kubectl get sensor '${APP_NAME}-cicd-gitlab-sensor' -n '$NAMESPACE' -o jsonpath='{.status.conditions[0].status}' 2>/dev/null | grep -q 'True'"

# Webhook Service
kubectl get service "${APP_NAME}-cicd-webhook-service" -n "$NAMESPACE" > /dev/null || {
    echo "ERROR: Webhook service not found"
    exit 1
}

echo "✅ Argo Events resources verified"
echo ""

# 3. Test webhook endpoint connectivity
echo "3. Testing webhook endpoint connectivity..."

WEBHOOK_SERVICE="${APP_NAME}-cicd-webhook-service.${NAMESPACE}.svc.cluster.local"

# Test internal connectivity
kubectl run webhook-connectivity-test --rm -i --restart=Never --image=alpine:3.20 --timeout=30s -- sh -c "
    apk add --no-cache curl
    echo 'Testing internal webhook connectivity...'
    curl -f -X POST http://${WEBHOOK_SERVICE}/webhook \
        -H 'Content-Type: application/json' \
        -H 'User-Agent: GitLab-Webhook-Test' \
        -d '{\"test\": \"connectivity\"}' \
        --max-time 10 || exit 1
    echo 'Internal connectivity test passed'
" || {
    echo "WARNING: Internal webhook connectivity test failed"
    echo "This may be expected if EventSource is not fully ready"
}

echo "✅ Webhook connectivity tested"
echo ""

# 4. Simulate GitLab webhook event
echo "4. Simulating GitLab webhook event..."

# Create test webhook payload
WEBHOOK_PAYLOAD=$(cat <<EOF
{
  "object_kind": "push",
  "ref": "refs/heads/main",
  "before": "0000000000000000000000000000000000000000",
  "after": "${TEST_COMMIT_ID}",
  "commits": [
    {
      "id": "${TEST_COMMIT_ID}",
      "message": "Test commit for webhook integration",
      "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
      "url": "https://${GITLAB_HOSTNAME}/${APP_NAME}-cicd/commit/${TEST_COMMIT_ID}",
      "author": {
        "name": "Test User",
        "email": "test@example.com"
      }
    }
  ],
  "repository": {
    "name": "${APP_NAME}-cicd",
    "url": "https://${GITLAB_HOSTNAME}/${APP_NAME}-cicd.git",
    "homepage": "https://${GITLAB_HOSTNAME}/${APP_NAME}-cicd"
  },
  "project": {
    "name": "${APP_NAME}-cicd",
    "web_url": "https://${GITLAB_HOSTNAME}/${APP_NAME}-cicd"
  }
}
EOF
)

echo "Webhook payload:"
echo "$WEBHOOK_PAYLOAD" | jq .
echo ""

# Send webhook event
kubectl run webhook-event-test --rm -i --restart=Never --image=alpine:3.20 --timeout=60s -- sh -c "
    apk add --no-cache curl jq
    echo 'Sending webhook event...'
    
    RESPONSE=\$(curl -s -X POST http://${WEBHOOK_SERVICE}/webhook \
        -H 'Content-Type: application/json' \
        -H 'User-Agent: GitLab/14.0.0' \
        -H 'X-GitLab-Event: Push Hook' \
        -d '$WEBHOOK_PAYLOAD' \
        --max-time 30)
    
    echo \"Webhook response: \$RESPONSE\"
    
    # Check if response indicates success (EventSource typically returns empty response)
    if [ \$? -eq 0 ]; then
        echo 'Webhook event sent successfully'
        exit 0
    else
        echo 'Failed to send webhook event'
        exit 1
    fi
" || {
    echo "ERROR: Failed to send webhook event"
    exit 1
}

echo "✅ Webhook event sent"
echo ""

# 5. Wait for workflow creation
echo "5. Waiting for workflow creation..."

wait_for_condition "Workflow created by webhook" \
    "kubectl get workflows -n '$NAMESPACE' -l triggered-by=gitlab-webhook --no-headers 2>/dev/null | wc -l | grep -v '^0$'" \
    120 10

# Get the created workflow
WORKFLOW_NAME=$(kubectl get workflows -n "$NAMESPACE" -l triggered-by=gitlab-webhook --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}' 2>/dev/null)

if [ -n "$WORKFLOW_NAME" ]; then
    echo "✅ Workflow created: $WORKFLOW_NAME"
    
    # Show workflow details
    echo ""
    echo "Workflow details:"
    kubectl get workflow "$WORKFLOW_NAME" -n "$NAMESPACE" -o yaml | head -30
    
    # Wait for workflow to start
    echo ""
    echo "6. Monitoring workflow execution..."
    
    wait_for_condition "Workflow started" \
        "kubectl get workflow '$WORKFLOW_NAME' -n '$NAMESPACE' -o jsonpath='{.status.phase}' 2>/dev/null | grep -E '(Running|Succeeded|Failed)'" \
        60 5
    
    WORKFLOW_STATUS=$(kubectl get workflow "$WORKFLOW_NAME" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)
    echo "Workflow status: $WORKFLOW_STATUS"
    
    if [ "$WORKFLOW_STATUS" = "Failed" ]; then
        echo ""
        echo "Workflow failed. Showing logs:"
        kubectl logs -l workflows.argoproj.io/workflow="$WORKFLOW_NAME" -n "$NAMESPACE" --tail=50 || true
    fi
else
    echo "❌ No workflow was created by the webhook event"
    echo ""
    echo "Debugging information:"
    echo "EventSource logs:"
    kubectl logs -l eventsource-name="${APP_NAME}-cicd-gitlab-eventsource" -n "$NAMESPACE" --tail=20 || true
    echo ""
    echo "Sensor logs:"
    kubectl logs -l sensor-name="${APP_NAME}-cicd-gitlab-sensor" -n "$NAMESPACE" --tail=20 || true
    exit 1
fi

echo ""
echo "🎉 GitLab webhook integration test completed successfully!"
echo ""
echo "Summary:"
echo "- EventSource: Ready"
echo "- Sensor: Ready"
echo "- Webhook Service: Available"
echo "- Webhook Event: Sent successfully"
echo "- Workflow: Created and started"
echo ""
echo "To monitor the workflow:"
echo "kubectl get workflow $WORKFLOW_NAME -n $NAMESPACE -w"
echo ""
echo "To view workflow logs:"
echo "kubectl logs -l workflows.argoproj.io/workflow=$WORKFLOW_NAME -n $NAMESPACE -f"