export DOMAIN_NAME=$1

kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/keycloak
kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak --timeout=30s
echo "Creating keycloak client for Jupyterhub"

ADMIN_PASSWORD=$(kubectl get secret -n keycloak keycloak-config -o go-template='{{index .data "KEYCLOAK_ADMIN_PASSWORD" | base64decode}}')

kubectl port-forward -n keycloak svc/keycloak 8080:8080 >/dev/null 2>&1 &
pid=$!
trap '{
  rm config-payloads/*-to-be-applied.json || true
  kill $pid
}' EXIT
echo "waiting for port forward to be ready"
while ! nc -vz localhost 8080 >/dev/null 2>&1; do
  sleep 2
done

KEYCLOAK_TOKEN=$(curl -sS --fail-with-body -X POST -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=modernengg-admin" \
  --data-urlencode "password=${ADMIN_PASSWORD}" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=admin-cli" \
  localhost:8080/keycloak/realms/master/protocol/openid-connect/token | jq -e -r '.access_token')

envsubst <config-payloads/client-payload.json >config-payloads/client-payload-to-be-applied.json

curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X POST --data @config-payloads/client-payload-to-be-applied.json \
  localhost:8080/keycloak/admin/realms/modernengg/clients

export CLIENT_ID=$(curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X GET localhost:8080/keycloak/admin/realms/modernengg/clients | jq -e -r '.[] | select(.clientId == "jupyterhub") | .id')

export CLIENT_SECRET=$(curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X GET localhost:8080/keycloak/admin/realms/modernengg/clients/${CLIENT_ID} | jq -e -r '.secret')

CLIENT_SCOPE_GROUPS_ID=$(curl -sS -H "Content-Type: application/json" -H "Authorization: bearer ${KEYCLOAK_TOKEN}" -X GET localhost:8080/keycloak/admin/realms/modernengg/client-scopes | jq -e -r '.[] | select(.name == "groups") | .id')

curl -sS -H "Content-Type: application/json" -H "Authorization: bearer ${KEYCLOAK_TOKEN}" -X PUT localhost:8080/keycloak/admin/realms/modernengg/clients/${CLIENT_ID}/default-client-scopes/${CLIENT_SCOPE_GROUPS_ID}

echo 'storing client secrets to jupyterhub namespace'
envsubst <secret-env-var.yaml | kubectl apply -f -
