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
  saml_idp_metadata_url        = local.keycloak_saml_url

  create_security_group = true
  security_group_rules = {
    egress_mysql = {
      description = "Allow egress to MySQL"
      from_port = 3306
      to_port = 3306
      protocol = "tcp"
      cidr_blocks = [local.hub_vpc_cidr]
    }

    egress_http = {
      description = "Allow egress to http"
      from_port = 80
      to_port = 80
      protocol = "tcp"
      cidr_blocks= ["0.0.0.0/0"]
    }

    egress_https = {
      description = "Allow egress to https"
      from_port = 443
      to_port = 443
      protocol = "tcp"
      cidr_blocks= ["0.0.0.0/0"]
    }
  }

  vpc_configuration = {
    subnet_ids = local.hub_subnet_ids
  }

  tags = local.tags
}

################################################################################
# EKS Monitoring with Terraform Observability Accelerator
################################################################################
# For spoek-dev cluster

# Wait for Flux CRD to be available
resource "null_resource" "spoke_dev_flux_crd_wait" {
  depends_on = [module.gitops_bridge_bootstrap]

  provisioner "local-exec" {
    command = <<-EOT
      while ! kubectl --context ${local.spoke_clusters["spoke1"].name} get crd kustomizations.kustomize.toolkit.fluxcd.io >/dev/null 2>&1; do
        sleep 10
      done
      kubectl --context ${local.spoke_clusters["spoke1"].name} wait --for=condition=Established crd/kustomizations.kustomize.toolkit.fluxcd.io --timeout=600s >/dev/null
    EOT
  }
}

module "eks_monitoring_spoke_dev" {
  depends_on = [
    module.gitops_bridge_bootstrap,
    null_resource.spoke_dev_flux_crd_wait,
  ]

  source         = "github.com/aws-observability/terraform-aws-observability-accelerator//modules/eks-monitoring?ref=v2.13.1"
  eks_cluster_id = data.aws_eks_cluster.clusters["spoke1"].id

  providers = {
    kubectl    = kubectl.spoke1
    helm       = helm.spoke1
    kubernetes = kubernetes.spoke1
  }

  enable_amazon_eks_adot = true
  enable_cert_manager    = false
  enable_java            = true
  enable_nginx           = true
  enable_custom_metrics  = true

  enable_dashboards       = true
  enable_external_secrets = false
  enable_fluxcd           = false
  enable_alerting_rules   = true
  enable_recording_rules  = true

  enable_apiserver_monitoring  = true
  enable_adotcollector_metrics = true

  grafana_api_key = module.managed_grafana.workspace_api_keys["operator"].key
  grafana_url     = "https://${module.managed_grafana.workspace_endpoint}"

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

# This is needed for Grafana Operator to work correctly
# As ESO is not deployed through terraform-aws-observability-accelerator
resource "kubectl_manifest" "spoke_dev_grafana_secret" {
  provider   = kubectl.spoke1
  yaml_body  = <<YAML
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: grafana-admin-credentials
  namespace: grafana-operator
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: grafana-admin-credentials
  data:
  - secretKey: GF_SECURITY_ADMIN_APIKEY
    remoteRef:
      key: "${data.aws_eks_cluster.clusters["spoke1"].id}/secrets"
      property: grafana_api_key
      conversionStrategy: Default
      decodingStrategy: None
      metadataPolicy: None
YAML
  depends_on = [module.eks_monitoring_spoke_dev]
}

# For spoek-prod cluster

# Wait for Flux CRD to be available
resource "null_resource" "spoke_prod_flux_crd_wait" {
  depends_on = [module.gitops_bridge_bootstrap]

  provisioner "local-exec" {
    command = <<-EOT
      while ! kubectl --context ${local.spoke_clusters["spoke2"].name} get crd kustomizations.kustomize.toolkit.fluxcd.io >/dev/null 2>&1; do
        sleep 10
      done
      kubectl --context ${local.spoke_clusters["spoke2"].name} wait --for=condition=Established crd/kustomizations.kustomize.toolkit.fluxcd.io --timeout=600s >/dev/null
    EOT
  }
}
module "eks_monitoring_spoke_prod" {
  depends_on = [
    module.gitops_bridge_bootstrap,
    null_resource.spoke_prod_flux_crd_wait,
  ]

  source         = "github.com/aws-observability/terraform-aws-observability-accelerator//modules/eks-monitoring?ref=v2.13.1"
  eks_cluster_id = data.aws_eks_cluster.clusters["spoke2"].id

  providers = {
    kubectl    = kubectl.spoke2
    helm       = helm.spoke2
    kubernetes = kubernetes.spoke2
  }

  enable_amazon_eks_adot = true
  enable_cert_manager    = false
  enable_java            = true
  enable_nginx           = true
  enable_custom_metrics  = true

  # Since the following were enabled in conjunction with the set up of the
  # spoke-dev EKS cluster, we will skip them with the spoke-prod EKS cluster
  enable_dashboards       = false
  enable_external_secrets = false
  enable_fluxcd           = false
  enable_alerting_rules   = false
  enable_recording_rules  = false

  enable_apiserver_monitoring  = false
  enable_adotcollector_metrics = false

  # grafana_api_key = module.managed_grafana.workspace_api_keys["operator"].key
  # grafana_url     = module.managed_grafana.workspace_endpoint

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

# This is needed for Grafana Operator to work correctly
# As ESO is not deployed through terraform-aws-observability-accelerator
resource "kubectl_manifest" "spoke_prod_grafana_secret" {
  provider   = kubectl.spoke2
  yaml_body  = <<YAML
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: grafana-admin-credentials
  namespace: grafana-operator
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: grafana-admin-credentials
  data:
  - secretKey: GF_SECURITY_ADMIN_APIKEY
    remoteRef:
      key: "${data.aws_eks_cluster.clusters["spoke2"].id}/secrets"
      property: grafana_api_key
      conversionStrategy: Default
      decodingStrategy: None
      metadataPolicy: None
YAML
  depends_on = [module.eks_monitoring_spoke_prod]
}

locals {
  scrape_interval = "30s"
  scrape_timeout  = "10s"
}

resource "aws_prometheus_scraper" "peeks-scraper" {
  for_each = { for k, v in local.spoke_clusters : k => v if try(v.addons.enable_prometheus_scraper, false) }
  source {
    eks {
      cluster_arn        = each.value.name
      subnet_ids         = data.aws_eks_cluster.clusters[each.key].vpc_config[0].subnet_ids
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
