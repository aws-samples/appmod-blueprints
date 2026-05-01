output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_version" {
  description = "Kubernetes version"
  value       = module.eks.cluster_version
}

output "kubeconfig_cmd" {
  description = "Command to update local kubeconfig"
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "litellm_endpoint" {
  description = "LiteLLM proxy endpoint (cluster-internal)"
  value       = "http://litellm.litellm.svc.cluster.local:4000"
}

output "litellm_api_key" {
  description = "LiteLLM API key for OpenClaw agents"
  value       = "sk-${random_password.litellm_api_key.result}"
  sensitive   = true
}

output "argocd_access_cmd" {
  description = "Port-forward command to access ArgoCD UI"
  value       = "kubectl port-forward -n argocd svc/argo-cd-argocd-server 8080:443"
}

output "argocd_initial_password_cmd" {
  description = "Retrieve initial ArgoCD admin password"
  value       = "kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
}

output "grafana_access_cmd" {
  description = "Port-forward command to access Grafana"
  value       = "kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "finance_ui_ecr_url" {
  description = "ECR repository URL for the finance-assistant UI image"
  value       = aws_ecr_repository.finance_ui.repository_url
}

output "finance_ui_host" {
  description = "Public hostname external-dns will create for the UI"
  value       = var.finance_ui_host
}

output "external_dns_role_arn" {
  description = "IAM role ARN for external-dns Pod Identity"
  value       = aws_iam_role.external_dns.arn
}

output "wildcard_cert_arn" {
  description = "Wildcard ACM certificate ARN (fed into Ingress via render script)"
  value       = var.wildcard_cert_arn
  sensitive   = true
}

output "finance_cognito_user_pool_arn" {
  description = "Cognito user pool ARN (plug into ALB auth annotation)"
  value       = aws_cognito_user_pool.finance.arn
}

output "finance_cognito_client_id" {
  description = "Cognito app client ID (plug into ALB auth annotation)"
  value       = aws_cognito_user_pool_client.finance.id
}

output "finance_cognito_domain" {
  description = "Cognito hosted UI domain prefix (plug into ALB auth annotation)"
  value       = aws_cognito_user_pool_domain.finance.domain
}

output "finance_cognito_user_pool_id" {
  description = "Cognito user pool ID (used by finance-ui)"
  value       = aws_cognito_user_pool.finance.id
}

output "route53_zone_id" {
  description = "Route53 hosted zone ID (for external-dns rendering)"
  value       = var.route53_zone_id
}

output "route53_zone_name" {
  description = "Route53 hosted zone name (for external-dns rendering)"
  value       = var.route53_zone_name
}

output "docker_ecr_login_cmd" {
  description = "Authenticate Docker to ECR before pushing the UI image"
  value       = "aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
}

output "gitops_next_step" {
  description = "After terraform apply: replace repo URL placeholder in gitops/apps/*.yaml then push"
  value       = "sed -i '' 's|GITOPS_REPO_URL_PLACEHOLDER|${var.gitops_repo_url}|g' gitops/apps/*.yaml && git add gitops/ && git commit -m 'chore: set ArgoCD repo URL' && git push"
}
