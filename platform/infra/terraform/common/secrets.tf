# AWS Secrets Manager resources for the platform

# Platform Configuration
resource "aws_secretsmanager_secret" "cluster_config" {
  name                    = "${var.resource_prefix}-${local.cluster_name}/config"
  description             = "Platform Configuration"
  recovery_window_in_days = 0

  tags = {
    Purpose     = "Platform Configuration"
  }
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "cluster_config" {
  secret_id     = aws_secretsmanager_secret.cluster_config.id
  secret_string = jsonencode({
    repo = var.repo
    labels = local.addons
    annotations = local.addons_metadata
  })
}

# Platform Configuration
resource "aws_secretsmanager_secret" "git_secret" {
  name                    = "${var.resource_prefix}-${local.cluster_name}/git-secrets"
  description             = "Platform Secrets"
  recovery_window_in_days = 0

  tags = {
    Purpose     = "Platform Secrets"
  }
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "git_secret" {
  secret_id     = aws_secretsmanager_secret.git_secret.id
  secret_string = jsonencode({
    ide_password = var.ide_password
    git_token = local.gitlab_token
  })
}

# # Keycloak Admin Password
# resource "aws_secretsmanager_secret" "keycloak_admin_password" {
#   name                    = "${var.resource_prefix}-keycloak-admin-password"
#   description             = "Keycloak admin password"
#   recovery_window_in_days = 0
  
#   tags = {
#     Application = "Keycloak"
#     Environment = "Platform"
#     ManagedBy   = "Terraform"
#     Purpose     = "Admin Authentication"
#   }
# }

# # Keycloak admin password uses the consistent workshop password (ide_password)

# resource "aws_secretsmanager_secret_version" "keycloak_admin_password" {
#   secret_id     = aws_secretsmanager_secret.keycloak_admin_password.id
#   secret_string = jsonencode({
#     password = var.ide_password
#   })
# }

# # Keycloak Database Password
# resource "aws_secretsmanager_secret" "keycloak_db_password" {
#   name                    = "${var.resource_prefix}-keycloak-db-password"
#   description             = "Keycloak database password"
#   recovery_window_in_days = 0
  
#   tags = {
#     Application = "Keycloak"
#     Environment = "Platform"
#     ManagedBy   = "Terraform"
#     Purpose     = "Database Authentication"
#   }
# }

# resource "random_password" "keycloak_db_password" {
#   length  = 32
#   special = true
#   override_special = "!#$%&*()-_=+[]{}<>:?"
# }

# resource "aws_secretsmanager_secret_version" "keycloak_db_password" {
#   secret_id     = aws_secretsmanager_secret.keycloak_db_password.id
#   secret_string = jsonencode({
#     password = random_password.keycloak_db_password.result
#   })
# }

# # Keycloak User Password (for workshop users)
# resource "aws_secretsmanager_secret" "keycloak_user_password" {
#   name                    = "${var.resource_prefix}-keycloak-user-password"
#   description             = "Keycloak user password for workshop participants"
#   recovery_window_in_days = 0
  
#   tags = {
#     Application = "Keycloak"
#     Environment = "Platform"
#     ManagedBy   = "Terraform"
#     Purpose     = "User Authentication"
#   }
# }

# resource "random_password" "keycloak_user_password" {
#   length  = 16
#   special = false  # User-friendly password for workshop participants
# }

# resource "aws_secretsmanager_secret_version" "keycloak_user_password" {
#   secret_id     = aws_secretsmanager_secret.keycloak_user_password.id
#   secret_string = jsonencode({
#     password = random_password.keycloak_user_password.result
#   })
# }
