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
  length           = 32
  override_special = "/-+"
  min_special      = 5
  min_numeric      = 5
}

# Backstage Postgres password
resource "random_password" "backstage_postgres" {
  length           = 32
  override_special = "/-+"
  min_special      = 5
  min_numeric      = 5
}

resource "random_password" "keycloak_admin" {
  length           = 32
  override_special = "/-+"
  min_special      = 5
  min_numeric      = 5

  keepers = {
    expiresAt = local.password_expiry
  }
}

resource "random_password" "devlake_encryption_secret" {
  length  = 128
  special = false
  lower   = false
  upper   = true
  numeric = false
}

resource "random_password" "devlake_mysql" {
  length           = 32
  override_special = "!-+"
  min_special      = 1
  min_numeric      = 1
  min_upper        = 1
  min_lower        = 1
}

resource "random_password" "grafana_mysql" {
  length           = 32
  override_special = "!-+"
  min_special      = 1
  min_numeric      = 1
  min_upper        = 1
  min_lower        = 1

}

# Store both hash and key in a single file to avoid regenerating on each run
locals {
  # Update password_expiry for password and key rotation
  password_expiry = "2025-12-31"

  # User Password and Key
  user_password_hash          = bcrypt(var.ide_password)
  keycloak_admin_password     = random_password.keycloak_admin.result
  keycloak_postgres_password  = random_password.keycloak_postgres.result
  backstage_postgres_password = random_password.backstage_postgres.result
  password_key                = random_string.password_key.result
  devlake_encryption_secret   = random_password.devlake_encryption_secret.result
  devlake_mysql_password      = random_password.devlake_mysql.result
  grafana_mysql_password      = random_password.grafana_mysql.result
}

# AWS Secrets Manager resources for the platform

# Platform Configuration
resource "aws_secretsmanager_secret" "cluster_config" {
  for_each                = var.clusters
  name                    = "${each.value.name}/config"
  description             = "Platform Configuration for cluster ${each.value.name}"
  recovery_window_in_days = 0

  tags = {
    Purpose = "Platform Configuration for cluster ${each.value.name}"
  }
}


# Store cluster config in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "cluster_config" {
  for_each  = var.clusters
  secret_id = aws_secretsmanager_secret.cluster_config[each.key].id
  secret_string = jsonencode({
    metadata = local.addons_metadata[each.key]
    addons   = local.addons[each.key]
    server   = each.value.environment != "control-plane" ? data.aws_eks_cluster.clusters[each.key].arn : ""
    vpc = {
      id         = local.cluster_vpc_ids[each.value.name]
      subnet_ids = data.aws_subnets.private_subnets[each.key].ids
    }
    config = {
      tlsClientConfig = {
        insecure = false
      }
    }
  })
}

# Platform Configuration
resource "aws_secretsmanager_secret" "git_secret" {
  for_each                = var.clusters
  name                    = "${each.value.name}/secrets"
  description             = "Platform Secrets for cluster ${each.value.name}"
  recovery_window_in_days = 0

  tags = {
    Purpose = "Platform Secrets for cluster ${each.value.name}"
  }
}

# Store the password in AWS Secrets Manager
resource "aws_secretsmanager_secret_version" "git_secret" {
  for_each  = var.clusters
  secret_id = aws_secretsmanager_secret.git_secret[each.key].id
  secret_string = jsonencode({
    backstage_postgres_password = local.backstage_postgres_password
    keycloak = {
      admin_password    = local.keycloak_admin_password
      postgres_password = local.keycloak_postgres_password
    }
    user_password             = var.ide_password
    user_password_hash        = local.user_password_hash
    user_password_key         = local.password_key
    git_token                 = local.gitlab_token
    git_username              = var.git_username
    argocd_auth_token         = var.argocd_auth_token
    grafana_api_key           = module.managed_grafana.workspace_api_keys["operator"].key
    devlake_encryption_secret = local.devlake_encryption_secret
    devlake_mysql_password    = local.devlake_mysql_password
    grafana_mysql_password    = local.grafana_mysql_password
  })
}

# Create the secret for AMP endpoint to be used in Kubevela service
# Only for backward compatibility
# TODO: Move this to cluster config secret
resource "aws_secretsmanager_secret" "argorollouts_secret" {
  name                    = "${local.context_prefix}/platform/amp"
  description             = "Platform AMP Endpoint"
  recovery_window_in_days = 0
}

# Create the secret version with key-value pairs
resource "aws_secretsmanager_secret_version" "argorollouts_secret_version" {
  secret_id = aws_secretsmanager_secret.argorollouts_secret.id
  secret_string = jsonencode({
    amp-region    = local.hub_cluster.region
    amp-workspace = module.managed_service_prometheus.workspace_prometheus_endpoint
  })
}
