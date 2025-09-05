ADMIN_PASSWORD=$(kubectl get secret -n keycloak keycloak-config -o go-template='{{index .data "KEYCLOAK_ADMIN_PASSWORD" | base64decode}}')
kubectl port-forward -n keycloak svc/keycloak 8080:8080 >/dev/null 2>&1 &
pid=$!
trap '{
kill $pid
}' EXIT

echo "waiting for port forward to be ready"
while ! nc -vz localhost 8080 >/dev/null 2>&1; do
  sleep 2
done

echo 'deleting Keycloak client'
KEYCLOAK_TOKEN=$(curl -sS --fail-with-body -X POST -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=modernengg-admin" \
  --data-urlencode "password=${ADMIN_PASSWORD}" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=admin-cli" \
  localhost:8080/keycloak/realms/master/protocol/openid-connect/token | jq -e -r '.access_token')

CLIENT_ID=$(curl -sS -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X GET localhost:8080/keycloak/admin/realms/modernengg/clients | jq -e -r '.[] | select(.clientId == "jupyterhub") | .id')

curl -sS --fail-with-body -H "Content-Type: application/json" \
  -H "Authorization: bearer ${KEYCLOAK_TOKEN}" \
  -X DELETE localhost:8080/keycloak/admin/realms/modernengg/clients/${CLIENT_ID}
