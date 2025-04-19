#!/bin/bash

kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/devlake
kubectl wait --for=condition=ready pod -l devlakeComponent=lake -n devlake --timeout=600s
kubectl wait --for=condition=ready pod -l devlakeComponent=mysql -n devlake --timeout=600s

kubectl port-forward -n devlake svc/devlake-lake 9090:8080 >/dev/null 2>&1 &
pid=$!
trap '{
  kill $pid
}' EXIT

echo "waiting for port forward to be ready"
while ! nc -vz localhost 9090 >/dev/null 2>&1; do
  sleep 2
done


OS=$(uname -s)
STRINGS=("dotnet" "go" "java" "nextjs")
for str in "${STRINGS[@]}"; do
  key_conn_bp=$(./project-init.sh $str)
  key=$(echo key_conn_bp | cut -d'|' -f1)
  conn=$(echo key_conn_bp | cut -d'|' -f2)
  bp=$(echo key_conn_bp | cut -d'|' -f3)
  case "$OS" in
    "Darwin")
      ./generate-data-mac.sh http://localhost:9090 $key $conn
      ;;
    "Linux")
      ./generate-data-linux.sh http://localhost:9090 $key $conn
      ;;
    *)
      echo "Unsupported operating system: $OS"
      exit 1
      ;;
  esac
  curl -X POST localhost:9090/blueprints/$bp/trigger

done

