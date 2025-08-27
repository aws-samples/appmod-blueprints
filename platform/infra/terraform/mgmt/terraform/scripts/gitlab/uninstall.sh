#!/bin/bash
set -e

DEPLOY_YAML="./gitlab-deploy.yaml"
SVC_YAML="./gitlab-lb-service.yaml"
kubectl delete -f ${DEPLOY_YAML} --namespace gitlab >/dev/null 2>&1 || true
kubectl delete -f ${SVC_YAML} --namespace gitlab >/dev/null 2>&1 || true
