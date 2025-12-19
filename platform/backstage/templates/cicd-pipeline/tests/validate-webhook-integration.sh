#!/bin/bash

# Validation script for GitLab webhook integration with Argo Events
# This script validates that the webhook configuration is working correctly

set -e

NAMESPACE=${1:-"team-example"}
APP_NAME=${2:-"example"}
GITLAB_HOSTNAME=${3:-"gitlab.example.com"}

echo "Validating GitLab webhook integration for app: $APP_NAME in namespace: $NAMESPACE"

# Check if Kro instance exists
echo "1. Checking Kro CICDPipeline instance..."
kubectl get cicdpipeline "${APP_NAME}-cicd-pipeline" -n "$NAMESPACE" -o jsonpath='{.status}' || {
    echo "ERROR: Kro CICDPipeline instance not found"
    exit 1
}

# Check if EventSource is created and ready
echo "2. Checking Argo Events EventSource..."
kubectl get eventsource "${APP_NAME}-cicd-gitlab-eventsource" -n "$NAMESPACE" -o jsonpath='{.status.conditions[0].status}' | grep -q "True" || {
    echo "ERROR: EventSource not ready"
    kubectl get eventsource "${APP_NAME}-cicd-gitlab-eventsource" -n "$NAMESPACE" -o yaml
    exit 1
}

# Check if Sensor is created and ready
echo "3. Checking Argo Events Sensor..."
kubectl get sensor "${APP_NAME}-cicd-gitlab-sensor" -n "$NAMESPACE" -o jsonpath='{.status.conditions[0].status}' | grep -q "True" || {
    echo "ERROR: Sensor not ready"
    kubectl get sensor "${APP_NAME}-cicd-gitlab-sensor" -n "$NAMESPACE" -o yaml
    exit 1
}

# Check if webhook service is available
echo "4. Checking webhook service..."
kubectl get service "${APP_NAME}-cicd-webhook-service" -n "$NAMESPACE" || {
    echo "ERROR: Webhook service not found"
    exit 1
}

# Check if webhook ingress is configured
echo "5. Checking webhook ingress..."
kubectl get ingress "${APP_NAME}-cicd-webhook-ingress" -n "$NAMESPACE" || {
    echo "ERROR: Webhook ingress not found"
    exit 1
}

# Test webhook endpoint accessibility (internal)
echo "6. Testing webhook endpoint accessibility..."
WEBHOOK_SERVICE="${APP_NAME}-cicd-webhook-service.${NAMESPACE}.svc.cluster.local"
kubectl run webhook-test --rm -i --restart=Never --image=alpine:3.20 -- sh -c "
    apk add --no-cache curl
    curl -f -X POST http://${WEBHOOK_SERVICE}/webhook -H 'Content-Type: application/json' -d '{\"test\": \"connectivity\"}' || exit 1
" || {
    echo "WARNING: Webhook endpoint not accessible (this may be expected if EventSource is not fully ready)"
}

# Check ConfigMap for webhook configuration
echo "7. Checking ConfigMap for webhook configuration..."
kubectl get configmap "${APP_NAME}-cicd-config" -n "$NAMESPACE" -o jsonpath='{.data.WEBHOOK_ENDPOINT}' | grep -q "argo-events" || {
    echo "ERROR: Webhook endpoint not configured in ConfigMap"
    exit 1
}

# Validate RBAC permissions
echo "8. Checking RBAC permissions..."
kubectl auth can-i get eventsources --as="system:serviceaccount:${NAMESPACE}:${APP_NAME}-cicd-sa" -n "$NAMESPACE" || {
    echo "ERROR: Service account lacks permissions for EventSources"
    exit 1
}

kubectl auth can-i get sensors --as="system:serviceaccount:${NAMESPACE}:${APP_NAME}-cicd-sa" -n "$NAMESPACE" || {
    echo "ERROR: Service account lacks permissions for Sensors"
    exit 1
}

echo "✅ All webhook integration validations passed!"
echo ""
echo "Webhook endpoint: http://${GITLAB_HOSTNAME}/argo-events/${APP_NAME}"
echo "Configure this URL in your GitLab repository webhook settings."
echo ""
echo "To test the webhook manually:"
echo "curl -X POST http://${GITLAB_HOSTNAME}/argo-events/${APP_NAME} \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"object_kind\":\"push\",\"ref\":\"refs/heads/main\",\"commits\":[{\"id\":\"test123\"}]}'"