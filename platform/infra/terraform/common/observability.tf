# AWS provider is configured at the root level

module "managed_service_prometheus" {
  source          = "terraform-aws-modules/managed-service-prometheus/aws"
  version         = "~> 2.2.2"
  workspace_alias = "${var.resource_prefix}-multicluster"
}

locals {
  name        = "${var.resource_prefix}-observability"
  description = "Amazon Managed Grafana workspace for ${local.name}"
}

# Create the secret
resource "aws_secretsmanager_secret" "argorollouts_secret" {
  name = "${var.resource_prefix}-argo-rollouts"
  recovery_window_in_days = 0

  lifecycle {
    ignore_changes = [name]
  }

  tags = local.tags
}

# Create the secret version with key-value pairs
resource "aws_secretsmanager_secret_version" "argorollouts_secret_version" {
  secret_id = aws_secretsmanager_secret.argorollouts_secret.id
  secret_string = jsonencode({
    amp-region    = data.aws_region.current.name
    amp-workspace = module.managed_service_prometheus.workspace_prometheus_endpoint
  })
}

module "managed_grafana" {
  source = "terraform-aws-modules/managed-service-grafana/aws"

  name                      = local.name
  associate_license         = false
  description               = local.description
  account_access_type       = "CURRENT_ACCOUNT"
  authentication_providers  = ["SAML"]
  permission_type           = "SERVICE_MANAGED"
  data_sources              = ["CLOUDWATCH", "PROMETHEUS", "XRAY"]
  notification_destinations = ["SNS"]
  stack_set_name            = local.name

  configuration = jsonencode({
    unifiedAlerting = {
      enabled = true
    },
    plugins = {
      pluginAdminEnabled = false
    }
  })

  grafana_version = "10.4"

  # Workspace API keys
  workspace_api_keys = {
    viewer = {
      key_name        = "grafana-viewer"
      key_role        = "VIEWER"
      seconds_to_live = 3600
    }
    editor = {
      key_name        = "grafana-editor"
      key_role        = "EDITOR"
      seconds_to_live = 3600
    }
    admin = {
      key_name        = "grafana-admin"
      key_role        = "ADMIN"
      seconds_to_live = 3600
    }
  }

  # Workspace SAML configuration
  saml_admin_role_values       = ["grafana-admin"]
  saml_editor_role_values      = ["grafana-editor", "grafana-viewer"]
  saml_email_assertion         = "mail"
  saml_groups_assertion        = "groups"
  saml_login_assertion         = "mail"
  saml_name_assertion          = "displayName"
  saml_org_assertion           = "org"
  saml_role_assertion          = "role"
  saml_login_validity_duration = 120
  # Dummy values for SAML configuration to setup will be updated after keycloak integration
  saml_idp_metadata_url = var.grafana_keycloak_idp_url

  tags = local.tags
}

# Create SSM parameters for Prometheus workspace information
resource "aws_ssm_parameter" "amp_endpoint" {
  name      = "${local.context_prefix}-${var.amazon_managed_prometheus_suffix}-endpoint"
  type      = "String"
  value     = module.managed_service_prometheus.workspace_prometheus_endpoint
  overwrite = true
  tags      = local.tags
}

resource "aws_ssm_parameter" "amp_arn" {
  name      = "${local.context_prefix}-${var.amazon_managed_prometheus_suffix}-arn"
  type      = "String"
  value     = module.managed_service_prometheus.workspace_arn
  overwrite = true
  tags      = local.tags
}
