terraform {
  required_version = ">= 1.3.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "managed_service_prometheus" {
  source  = "terraform-aws-modules/managed-service-prometheus/aws"
  version = "~> 2.2.2"
  workspace_alias = "aws-observability-accelerator-multicluster"
}

locals {
  name        = "aws-observability-accelerator"
  description = "Amazon Managed Grafana workspace for ${local.name}"

  tags = {
    GithubRepo = "terraform-aws-observability-accelerator"
    GithubOrg  = "aws-observability"
  }
}

module "managed_grafana" {
  source  = "terraform-aws-modules/managed-service-grafana/aws"

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
  saml_admin_role_values  = ["grafana-admin"]
  saml_editor_role_values = ["grafana-editor","grafana-viewer"]
  saml_email_assertion    = "mail"
  saml_groups_assertion   = "groups"
  saml_login_assertion    = "mail"
  saml_name_assertion     = "displayName"
  saml_org_assertion      = "org"
  saml_role_assertion     = "role"
  # Dummy values for SAML configuration to setup will be updated after keycloak integration
  saml_idp_metadata_url   = var.grafana_keycloak_idp_url

  tags = local.tags
}