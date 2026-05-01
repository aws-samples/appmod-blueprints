#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/../terraform"
MANIFESTS_DIR="${SCRIPT_DIR}/../manifests"

echo "==> Checking required variables..."
if [ ! -f "${TERRAFORM_DIR}/terraform.tfvars" ]; then
  echo "ERROR: terraform/terraform.tfvars not found."
  echo "Copy the example and fill in your values:"
  echo "  cp terraform/terraform.tfvars.example terraform/terraform.tfvars"
  exit 1
fi

GITOPS_REPO_URL=$(grep 'gitops_repo_url' "${TERRAFORM_DIR}/terraform.tfvars" | sed 's/.*= *"\(.*\)"/\1/')
if [ -z "${GITOPS_REPO_URL}" ]; then
  echo "ERROR: gitops_repo_url not set in terraform.tfvars"
  exit 1
fi

echo "==> Initializing Terraform..."
terraform -chdir="${TERRAFORM_DIR}" init -upgrade

echo "==> Applying infrastructure (EKS, VPC, IAM, ArgoCD, Bedrock Guardrail, Karpenter)..."
terraform -chdir="${TERRAFORM_DIR}" apply -auto-approve

echo "==> Updating kubeconfig..."
CLUSTER_NAME=$(terraform -chdir="${TERRAFORM_DIR}" output -raw cluster_name)
REGION=$(aws configure get region 2>/dev/null || echo "us-west-2")
aws eks update-kubeconfig --region "${REGION}" --name "${CLUSTER_NAME}"

echo "==> Waiting for cluster nodes to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

echo "==> Setting GitOps repo URL in ArgoCD app manifests..."
sed -i '' "s|GITOPS_REPO_URL_PLACEHOLDER|${GITOPS_REPO_URL}|g" "${SCRIPT_DIR}/../gitops/apps/"*.yaml
git -C "${SCRIPT_DIR}/.." add gitops/
git -C "${SCRIPT_DIR}/.." diff --cached --quiet || git -C "${SCRIPT_DIR}/.." commit -m "chore: set ArgoCD repo URL"
git -C "${SCRIPT_DIR}/.." push

echo ""
echo "==> Deploy complete! ArgoCD will now sync all workloads from your Git repo."
echo ""
echo "  ArgoCD:  kubectl port-forward -n argocd svc/argo-cd-argocd-server 8080:443"
echo "  Grafana: kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
echo "  Apps:    kubectl get applications -n argocd"
echo ""
echo "==> REQUIRED: Create Slack tokens secret for the sandbox agent"
echo "    Get tokens from https://api.slack.com/apps then run:"
echo ""
echo "    kubectl create secret generic slack-tokens \\"
echo "      -n openclaw \\"
echo "      --from-literal=bot-token=\"xoxb-YOUR-BOT-TOKEN\" \\"
echo "      --from-literal=app-token=\"xapp-YOUR-APP-TOKEN\" \\"
echo "      --from-literal=signing-secret=\"YOUR-SIGNING-SECRET\""
echo ""
echo "==> Then deploy the Slack sandbox:"
echo "    kubectl apply -f ${MANIFESTS_DIR}/sandbox-slack.yaml"
echo ""
echo "LiteLLM API key:"
terraform -chdir="${TERRAFORM_DIR}" output -raw litellm_api_key
echo ""
echo "Bedrock Guardrail ID:"
terraform -chdir="${TERRAFORM_DIR}" output -raw bedrock_guardrail_id
echo ""
