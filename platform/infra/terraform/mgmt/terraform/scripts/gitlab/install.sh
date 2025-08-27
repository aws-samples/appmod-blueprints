#!/bin/bash
set -e
GITLAB_DIR="."
INSTALL_YAML="./gitlab-deploy.yaml"
GITLAB_PASSWD="Changeme!2345"

# Create Service with LB before gitlab install
kubectl apply -n gitlab -f gitlab-lb-service.yaml

# Wait for load balancer ingress hostname to be available
echo "Waiting for load balancer ingress hostname..."
TIMEOUT=300  # 5 minutes in seconds
ELAPSED=0
while true; do
    DOMAIN_NAME=$(kubectl get service gitlab -n gitlab -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    if [[ -n "$DOMAIN_NAME" ]]; then
        echo "Load balancer hostname available: $DOMAIN_NAME"
        export GITLAB_DOMAIN_NAME=${DOMAIN_NAME}
        break
    fi
    
    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        echo "Timeout: Load balancer hostname not assigned after 5 minutes"
        exit 1
    fi
    
    echo "Waiting for load balancer hostname to be assigned... (${ELAPSED}s elapsed)"
    sleep 10
    ELAPSED=$((ELAPSED + 10))
done

sed  "s/GITLAB_DOMAIN_NAME/${DOMAIN_NAME}/g" gitlab-deploy.yaml.tpl > ${INSTALL_YAML}
sed -i.bak "s/GITLAB_PASSWORD/${GITLAB_PASSWD}/g" ${INSTALL_YAML}

kubectl apply -n gitlab -f ${INSTALL_YAML}