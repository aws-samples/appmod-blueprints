# AWS provider is configured at the root level

module "managed_service_prometheus" {
  source          = "terraform-aws-modules/managed-service-prometheus/aws"
  version         = "~> 2.2.2"
  workspace_alias = "${var.resource_prefix}-observability-amp"
}

module "managed_grafana" {
  source = "terraform-aws-modules/managed-service-grafana/aws"

  name                      = "${var.resource_prefix}-observability"
  associate_license         = false
  description               = "Amazon Managed Grafana workspace for ${var.resource_prefix}-observability"
  account_access_type       = "CURRENT_ACCOUNT"
  authentication_providers  = ["SAML"]
  permission_type           = "SERVICE_MANAGED"
  data_sources              = ["CLOUDWATCH", "PROMETHEUS", "XRAY"]
  notification_destinations = ["SNS"]
  stack_set_name            = "${var.resource_prefix}-observability"

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
    operator = { # For terraform-aws-observability-accelerator module
      key_name        = "grafana-operator"
      key_role        = "ADMIN"
      seconds_to_live = 432000
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
  saml_idp_metadata_url = local.keycloak_saml_url

  tags = local.tags
}

################################################################################
# EKS Monitoring with Terraform Observability Accelerator
################################################################################

module "eks_monitoring" {
  source                 = "github.com/aws-observability/terraform-aws-observability-accelerator//modules/eks-monitoring?ref=v2.13.0"
  eks_cluster_id         = data.aws_eks_cluster.clusters[local.hub_cluster_key].id
  enable_amazon_eks_adot = true
  enable_cert_manager    = false
  enable_java            = true
  enable_nginx           = true
  enable_custom_metrics  = true

  # This configuration section results in actions performed on AMG and AMP; and it needs to be done just once
  # And hence, this in performed in conjunction with the setup of the eks_cluster_1 EKS cluster
  enable_dashboards       = true
  enable_external_secrets = false
  enable_fluxcd           = false
  enable_alerting_rules   = true
  enable_recording_rules  = true

  # Additional dashboards
  enable_apiserver_monitoring  = true
  enable_adotcollector_metrics = true

  grafana_api_key = module.managed_grafana.workspace_api_keys[operator].key
  grafana_url     = module.managed_grafana.workspace_endpoint

  # prevents the module to create a workspace
  enable_managed_prometheus = false

  managed_prometheus_workspace_id       = module.managed_service_prometheus.workspace_id
  managed_prometheus_workspace_endpoint = module.managed_service_prometheus.workspace_prometheus_endpoint
  managed_prometheus_workspace_region   = local.hub_cluster.region

  prometheus_config = {
    global_scrape_interval = "60s"
    global_scrape_timeout  = "15s"
    scrape_sample_limit    = 2000
  }

  custom_metrics_config = {
    polyglot_app_config = {
      enableBasicAuth       = false
      path                  = "/metrics"
      basicAuthUsername     = "username"
      basicAuthPassword     = "password"
      ports                 = ".*:(8080)$"
      droppedSeriesPrefixes = "(unspecified.*)$"
    }
  }
}

locals{
    scrape_interval = "30s"
    scrape_timeout  = "10s"
}

resource "aws_prometheus_scraper" "peeks-scraper" {
  for_each = { for k, v in local.spoke_clusters : k => v if try(v.addons.enable_prometheus_scraper, false) }
  source {
    eks {
      cluster_arn = each.value.name
      subnet_ids  = data.aws_eks_cluster.clusters[each.key].vpc_config[0].subnet_ids
      security_group_ids = [data.aws_eks_cluster.clusters[each.key].vpc_config[0].cluster_security_group_id, data.aws_eks_cluster.clusters[each.key].vpc_config[0].security_group_ids]
    }
  }
  destination {
    amp {
       workspace_arn = module.managed_service_prometheus.workspace_arn
    }
  }
  alias = "peeks-hub"
  scrape_configuration = replace(
    replace(
      replace(
        replace(
          replace(
            file("${path.module}/manifests/scraper-config.yaml"),
            "{scrape_interval}",
            local.scrape_interval
          ),
          "{scrape_timeout}",
          local.scrape_timeout
        ),
        "{cluster}",
        each.value.name
      ),
      "{region}",
      each.value.region
    ),
    "{account_id}",
    data.aws_caller_identity.current.account_id
  )
}
