# Generate password and keys
resource "random_string" "password_key" {
  length           = 16
  override_special = "!-+"

  keepers = {
    expiresAt = local.password_expiry
  }
}

# Keycloak Postgres password
resource "random_password" "keycloak_postgres" {
  length            = 32
  override_special  = "/-+"
  min_special       = 5
  min_numeric       = 5
}

# Backstage Postgres password
resource "random_password" "backstage_postgres" {
  length            = 32
  override_special  = "/-+"
  min_special       = 5
  min_numeric       = 5
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
  backstage_postgres_password = random_password.backstage_postgres.result
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


# Store cluster config in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "cluster_config" {
  for_each = var.clusters
  secret_id     = aws_secretsmanager_secret.cluster_config[each.key].id
  secret_string = jsonencode({
    metadata = local.addons_metadata[each.key]
    addons   = local.addons[each.key]
    server   = each.value.environment != "control-plane" ? data.aws_eks_cluster.clusters[each.key].endpoint : ""
    config = {
      tlsClientConfig = {
        insecure = false
        caData   = each.value.environment != "control-plane" ? data.aws_eks_cluster.clusters[each.key].certificate_authority[0].data : null
      }
      awsAuthConfig = each.value.environment != "control-plane" ? {
        clusterName = data.aws_eks_cluster.clusters[each.key].name
        roleARN     = aws_iam_role.spoke[each.key].arn
      } : null
    }
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
    backstage_postgres_password = local.backstage_postgres_password
    keycloak = {
      admin_password = local.keycloak_admin_password
      postgres_password = local.keycloak_postgres_password
    }
    user_password = var.ide_password
    user_password_hash = local.user_password_hash
    user_password_key = local.password_key
    git_token = local.gitlab_token
  })
}
