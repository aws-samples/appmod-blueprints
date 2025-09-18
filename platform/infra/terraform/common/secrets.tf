# Generate password and keys
resource "random_string" "password_key" {
  length           = 16
  override_special = "!-+"

  keepers = {
    expiresAt = local.password_expiry
  }
}
resource "random_password" "keycloak_postgres" {
  length            = 32
  override_special  = "/-+"
  min_special       = 5
  min_numeric       = 5

  keepers = {
    expiresAt = local.password_expiry
  }
}

resource "random_password" "keycloak_admin" {
  length            = 32
  override_special  = "/-+"
  min_special       = 5
  min_numeric       = 5

  keepers = {
    expiresAt = local.password_expiry
  }
}

# Store both hash and key in a single file to avoid regenerating on each run
locals {
  # Update password_expiry for password and key rotation
  password_expiry = "2025-12-31"

  # User Password and Key
  user_password_hash = bcrypt(var.ide_password)
  keycloak_admin_password = random_password.keycloak_admin.result
  keycloak_postgres_password = random_password.keycloak_postgres.result
  password_key = random_string.password_key.result
}

# AWS Secrets Manager resources for the platform

# Platform Configuration
resource "aws_secretsmanager_secret" "cluster_config" {
  for_each = var.clusters
  name                    = "${local.context_prefix}-${each.value.name}/config"
  description             = "Platform Configuration for cluster ${each.value.name}"
  recovery_window_in_days = 0

  tags = {
    Purpose     = "Platform Configuration for cluster ${each.value.name}"
  }
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "cluster_config" {
  for_each = var.clusters
  secret_id     = aws_secretsmanager_secret.cluster_config[each.key].id
  secret_string = jsonencode({
    repo = var.repo
    labels = local.addons[each.key]
    annotations = local.addons_metadata[each.key]
  })
}

# Platform Configuration
resource "aws_secretsmanager_secret" "git_secret" {
  for_each = var.clusters
  name                    = "${local.context_prefix}-${each.value.name}/secrets"
  description             = "Platform Secrets for cluster ${each.value.name}"
  recovery_window_in_days = 0

  tags = {
    Purpose     = "Platform Secrets for cluster ${each.value.name}"
  }
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "git_secret" {
  for_each = var.clusters
  secret_id     = aws_secretsmanager_secret.git_secret[each.key].id
  secret_string = jsonencode({
    keycloak = {
      admin_password = local.keycloak_admin_password
      postgres_password = local.keycloak_postgres_password
    }
    user_password = var.ide_password
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
