#!/bin/bash
set -e -o pipefail

export USER1_PASSWORD=${1}
ADMIN_PASSWORD=${2}
REPO_ROOT=$(git rev-parse --show-toplevel)

echo "waiting for keycloak to be ready. may take a few minutes"
kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/keycloak --timeout=600s
kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak  --timeout=90s

sleep 5

# Configure keycloak. Might be better to just import
kubectl port-forward -n keycloak svc/keycloak 8080:8080 > /dev/null 2>&1 &
pid=$!

envsubst < config-payloads/user-password.json > config-payloads/user-password-to-be-applied.json

# ensure port-forward is killed
trap '{
    rm config-payloads/user-password-to-be-applied.json || true
    kill $pid
}' EXIT

echo "waiting for port forward to be ready"
while ! nc -vz localhost 8080 > /dev/null 2>&1 ; do
    sleep 2
done

# Default token expires in one minute. May need to extend. very ugly
KEYCLOAK_TOKEN=$(curl -sS  --fail-with-body -X POST -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=modernengg-admin" \
  --data-urlencode "password=${ADMIN_PASSWORD}" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=admin-cli" \
  localhost:8080/keycloak/realms/master/protocol/openid-connect/token | jq -e -r '.access_token')

echo "creating modernengg realm and groups"
curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/realm-payload.json \
  localhost:8080/keycloak/admin/realms

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/client-scope-groups-payload.json \
  localhost:8080/keycloak/admin/realms/modernengg/client-scopes

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/group-admin-payload.json \
  localhost:8080/keycloak/admin/realms/modernengg/groups

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/group-base-user-payload.json \
  localhost:8080/keycloak/admin/realms/modernengg/groups

# Create scope mapper
echo 'adding group claim to tokens'
CLIENT_SCOPE_GROUPS_ID=$(curl -sS -H "Content-Type: application/json" -H "Authorization: bearer ${KEYCLOAK_TOKEN}" -X GET  localhost:8080/keycloak/admin/realms/modernengg/client-scopes | jq -e -r  '.[] | select(.name == "groups") | .id')

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/group-mapper-payload.json \
  localhost:8080/keycloak/admin/realms/modernengg/client-scopes/${CLIENT_SCOPE_GROUPS_ID}/protocol-mappers/models

echo "creating test users"
curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/user-user1.json \
  localhost:8080/keycloak/admin/realms/modernengg/users

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/user-user2.json \
  localhost:8080/keycloak/admin/realms/modernengg/users

USER1ID=$(curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" 'localhost:8080/keycloak/admin/realms/modernengg/users?lastName=one' | jq -r '.[0].id')
USER2ID=$(curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" 'localhost:8080/keycloak/admin/realms/modernengg/users?lastName=two' | jq -r '.[0].id')

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X PUT --data @config-payloads/user-password-to-be-applied.json \
  localhost:8080/keycloak/admin/realms/modernengg/users/${USER1ID}/reset-password

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X PUT --data @config-payloads/user-password-to-be-applied.json \
  localhost:8080/keycloak/admin/realms/modernengg/users/${USER2ID}/reset-password

# If TLS secret is available in /private, use it. Could be empty...

if ls ${REPO_ROOT}/private/keycloak-tls-backup-* 1> /dev/null 2>&1; then
    TLS_FILE=$(ls -t ${REPO_ROOT}/private/keycloak-tls-backup-* | head -n1)
    kubectl apply -f ${TLS_FILE}
fi