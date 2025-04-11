#!/bin/bash

kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/devlake
kubectl wait --for=condition=ready pod -l devlakeComponent=lake -n devlake --timeout=60s
kubectl wait --for=condition=ready pod -l devlakeComponent=mysql -n devlake --timeout=60s

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
STRINGS=("dotnet" "go" "java" "nextjs" "")
for str in "${STRINGS[@]}"; do
./project-init.sh $str
  process_args "$MAC_SCRIPT" "$str"
done

case "$OS" in
  "Darwin")
    ./generate-data-mac.sh
    ;;
  "Linux")
    ./generate-data-linux.sh
    ;;
  *)
    echo "Unsupported operating system: $OS"
    exit 1
    ;;
esac
