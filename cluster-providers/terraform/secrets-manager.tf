# Secrets Manager — seeds cluster config and keycloak passwords
# Mirrors the secrets-manager:seed and secrets-manager:seed-keycloak tasks

resource "aws_secretsmanager_secret" "cluster_config" {
  name                    = "${var.cluster_name}/config"
  recovery_window_in_days = 0
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "cluster_config" {
  secret_id = aws_secretsmanager_secret.cluster_config.id
  secret_string = jsonencode({
    metadata = jsonencode({
      addonsRepoURL           = var.repo_url
      addonsRepoRevision      = var.repo_revision
      addonsRepoBasepath      = var.repo_basepath
      fleetRepoURL            = var.repo_url
      fleetRepoRevision       = var.repo_revision
      fleetRepoBasepath       = var.repo_basepath
      aws_region              = var.aws_region
      aws_account_id          = var.aws_account_id
      aws_cluster_name        = var.cluster_name
      aws_vpc_id              = aws_vpc.hub.id
      alb_controller_mode     = "auto"
      ingress_domain_name     = var.domain
      ingress_name            = var.ingress_name
      ingress_security_groups = var.ingress_security_groups
      resource_prefix         = var.resource_prefix
    })
    config = jsonencode({ tlsClientConfig = { insecure = false } })
    server = aws_eks_cluster.hub.arn
    addons = ""
  })
}

# --- Keycloak secret (random passwords) ---
resource "random_password" "keycloak_admin" {
  length  = 24
  special = false
}

resource "random_password" "keycloak_postgres" {
  length  = 24
  special = false
}

resource "random_password" "keycloak_user" {
  length  = 16
  special = false
}

resource "aws_secretsmanager_secret" "keycloak" {
  name                    = "${var.cluster_name}/keycloak"
  recovery_window_in_days = 0
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "keycloak" {
  secret_id = aws_secretsmanager_secret.keycloak.id
  secret_string = jsonencode({
    keycloak_admin_password    = random_password.keycloak_admin.result
    keycloak_postgres_password = random_password.keycloak_postgres.result
    user_password              = random_password.keycloak_user.result
  })
}
