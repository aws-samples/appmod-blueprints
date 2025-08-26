
# This output is informational only and is not used by any other module
output "git_secrets_urls" {
  value       = local.git_secrets_urls
  description = "The URLs for the Git repositories"
}
output "git_secrets_names" {
  value       = local.git_secrets_names
  description = "The names of the AWS Secrets for the Git repositories"
}

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