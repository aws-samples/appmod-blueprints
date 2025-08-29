#!/bin/bash
set -e -o pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
MODERN_ROOT=${REPO_ROOT}/platform/infra/terraform/mgmt/terraform/

kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/keycloak
kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak  --timeout=30s
echo "Creating keycloak client for Argo Workflows"

ADMIN_PASSWORD=$(kubectl get secret -n keycloak keycloak-config -o go-template='{{index .data "KEYCLOAK_ADMIN_PASSWORD" | base64decode}}')
kubectl port-forward -n keycloak svc/keycloak 8090:8080 > /dev/null 2>&1 &
pid=$!
trap '{
  rm config-payloads/*-to-be-applied.json || true
  kill $pid
}' EXIT
echo "waiting for port forward to be ready"
while ! nc -vz localhost 8090 > /dev/null 2>&1 ; do
    sleep 2
done

KEYCLOAK_TOKEN=$(curl -sS  --fail-with-body -X POST -H "Content-Type: application/x-www-form-urlencoded" \
--data-urlencode "username=modernengg-admin" \
--data-urlencode "password=${ADMIN_PASSWORD}" \
--data-urlencode "grant_type=password" \
--data-urlencode "client_id=admin-cli" \
localhost:8090/keycloak/realms/master/protocol/openid-connect/token | jq -e -r '.access_token')

envsubst < ${MODERN_ROOT}/scripts/argo-workflows/config-payloads/client-payload.json > ${MODERN_ROOT}/scripts/argo-workflows/config-payloads/client-payload-to-be-applied.json

curl -sS -H "Content-Type: application/json" \
-H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
-X POST --data @${MODERN_ROOT}/scripts/argo-workflows/config-payloads/client-payload-to-be-applied.json \
localhost:8090/keycloak/admin/realms/modernengg/clients

CLIENT_ID=$(curl -sS -H "Content-Type: application/json" \
-H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
-X GET localhost:8090/keycloak/admin/realms/modernengg/clients | jq -e -r  '.[] | select(.clientId == "argo-workflows") | .id')

export CLIENT_SECRET=$(curl -sS -H "Content-Type: application/json" \
-H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
-X GET localhost:8090/keycloak/admin/realms/modernengg/clients/${CLIENT_ID} | jq -e -r '.secret')

CLIENT_SCOPE_GROUPS_ID=$(curl -sS -H "Content-Type: application/json" -H "Authorization: bearer ${KEYCLOAK_TOKEN}" -X GET  localhost:8090/keycloak/admin/realms/modernengg/client-scopes | jq -e -r  '.[] | select(.name == "groups") | .id')

curl -sS -H "Content-Type: application/json" -H "Authorization: bearer ${KEYCLOAK_TOKEN}" -X PUT  localhost:8090/keycloak/admin/realms/modernengg/clients/${CLIENT_ID}/default-client-scopes/${CLIENT_SCOPE_GROUPS_ID}

echo 'storing client secrets to argo namespace'

envsubst < ${MODERN_ROOT}/scripts/argo-workflows/secret-sso.yaml | kubectl apply -f -

# If TLS secret is available in /private, use it. Could be empty...
if ls ${MODERN_ROOT}/private/argo-workflows-tls-backup-* 1> /dev/null 2>&1; then
    TLS_FILE=$(ls -t ${MODERN_ROOT}/private/argo-workflows-tls-backup-* | head -n1)
    kubectl apply -f ${TLS_FILE}
fi
