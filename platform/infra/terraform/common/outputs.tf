
# Removed unused git_secrets outputs

output "gitops_user_name" {
  value       = var.gitea_user
  description = "Name of the IAM user created for GitOps access"
}

output "aws_ssm_parameter_name" {
  value       = aws_ssm_parameter.argocd_hub_role.name
  description = "Name of the SSM parameter for the ArgoCD EKS role"
}
output "iam_argocd_role_arn" {
  value       = aws_iam_role.argocd_central.arn
  description = "ARN of the IAM role for ArgoCD EKS access"
}

# Backstage PostgreSQL password secret outputs
output "backstage_postgresql_secret_name" {
  description = "Name of the AWS Secrets Manager secret containing the PostgreSQL password"
  value       = aws_secretsmanager_secret.backstage_postgresql_password.name
}

output "backstage_postgresql_secret_arn" {
  description = "ARN of the AWS Secrets Manager secret containing the PostgreSQL password"
  value       = aws_secretsmanager_secret.backstage_postgresql_password.arn
}

# Keycloak secret outputs
output "keycloak_admin_password_secret_name" {
  description = "Name of the AWS Secrets Manager secret containing the Keycloak admin password"
  value       = aws_secretsmanager_secret.keycloak_admin_password.name
}

output "keycloak_admin_password_secret_arn" {
  description = "ARN of the AWS Secrets Manager secret containing the Keycloak admin password"
  value       = aws_secretsmanager_secret.keycloak_admin_password.arn
}

output "keycloak_db_password_secret_name" {
  description = "Name of the AWS Secrets Manager secret containing the Keycloak database password"
  value       = aws_secretsmanager_secret.keycloak_db_password.name
}

output "keycloak_db_password_secret_arn" {
  description = "ARN of the AWS Secrets Manager secret containing the Keycloak database password"
  value       = aws_secretsmanager_secret.keycloak_db_password.arn
}

output "keycloak_user_password_secret_name" {
  description = "Name of the AWS Secrets Manager secret containing the Keycloak user password"
  value       = aws_secretsmanager_secret.keycloak_user_password.name
}

output "keycloak_user_password_secret_arn" {
  description = "ARN of the AWS Secrets Manager secret containing the Keycloak user password"
  value       = aws_secretsmanager_secret.keycloak_user_password.arn
}

output "amp_workspace_id" {
  description = "Amazon Managed prometheus Workspace ID"
  value       = module.managed_service_prometheus.workspace_id
}

output "amg_workspace_id" {
  description = "Amazon Managed Grafana Workspace ID"
  value       = module.managed_grafana.workspace_id
}

output "grafana_workspace_endpoint" {
  description = "Amazon Managed Grafana Workspace endpoint"
  value       = module.managed_grafana.workspace_endpoint
}

output "grafana_workspace_iam_role_arn" {
  description = "Amazon Managed Grafana Workspace's IAM Role ARN"
  value       = module.managed_grafana.workspace_iam_role_arn
}

output "amp_endpoint_ssm_parameter" {
  description = "SSM parameter name for Amazon Managed Prometheus endpoint"
  value       = aws_ssm_parameter.amp_endpoint.name
}

output "amp_arn_ssm_parameter" {
  description = "SSM parameter name for Amazon Managed Prometheus ARN"
  value       = aws_ssm_parameter.amp_arn.name
}
