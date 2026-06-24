# Helm + kubectl resources applied to the hub cluster
# Crossplane and ESO are installed here. Post-CRD resources (ProviderConfig,
# ClusterSecretStore, seed secret, root-appset) are applied by the Taskfile
# after providers are healthy, avoiding CRD race conditions.

# --- Crossplane (must be running before ArgoCD syncs crossplane-base) ---
resource "helm_release" "crossplane" {
  name             = "crossplane"
  repository       = "https://charts.crossplane.io/stable"
  chart            = "crossplane"
  version          = "2.2.1"
  namespace        = "crossplane-system"
  create_namespace = true
  wait             = true
  timeout          = 600

  depends_on = [aws_eks_cluster.hub]
}

# --- Crossplane Providers ---
locals {
  # All providers installed at bootstrap. IAM and EKS get pod identity from terraform
  # (createIdentity: false in registry); others get identity from ArgoCD post-bootstrap.
  crossplane_bootstrap_providers = {
    iam = {
      package         = "xpkg.upbound.io/upbound/provider-aws-iam:v2.5.3"
      service_account = "provider-aws-iam"
    }
    eks = {
      package         = "xpkg.upbound.io/upbound/provider-aws-eks:v2.5.3"
      service_account = "provider-aws-eks"
    }
    ec2 = {
      package         = "xpkg.upbound.io/upbound/provider-aws-ec2:v2.5.3"
      service_account = "provider-aws-ec2"
    }
    secretsmanager = {
      package         = "xpkg.upbound.io/upbound/provider-aws-secretsmanager:v2.5.3"
      service_account = "provider-aws-secretsmanager"
    }
  }
}

resource "kubectl_manifest" "crossplane_drc" {
  for_each = local.crossplane_bootstrap_providers

  yaml_body = yamlencode({
    apiVersion = "pkg.crossplane.io/v1beta1"
    kind       = "DeploymentRuntimeConfig"
    metadata = {
      name = "${each.key}-drc"
    }
    spec = {
      deploymentTemplate = {
        spec = {
          selector = {}
          template = {
            spec = {
              serviceAccountName = each.value.service_account
              containers = [{
                name = "package-runtime"
                resources = {
                  requests = { cpu = "100m", memory = "256Mi" }
                  limits   = { memory = "512Mi" }
                }
              }]
            }
          }
        }
      }
    }
  })

  depends_on = [helm_release.crossplane]
}

resource "kubectl_manifest" "crossplane_sa" {
  for_each = local.crossplane_bootstrap_providers

  yaml_body = yamlencode({
    apiVersion = "v1"
    kind       = "ServiceAccount"
    metadata = {
      name      = each.value.service_account
      namespace = "crossplane-system"
    }
  })

  depends_on = [helm_release.crossplane]
}

resource "kubectl_manifest" "crossplane_provider" {
  for_each = local.crossplane_bootstrap_providers

  yaml_body = yamlencode({
    apiVersion = "pkg.crossplane.io/v1"
    kind       = "Provider"
    metadata = {
      name = "provider-aws-${each.key}"
    }
    spec = {
      package = each.value.package
      runtimeConfigRef = {
        name = "${each.key}-drc"
      }
    }
  })

  depends_on = [
    kubectl_manifest.crossplane_drc,
    kubectl_manifest.crossplane_sa,
  ]
}

# Also install the provider-family-aws (required dependency)
# Name must match crossplane-base chart (upbound-provider-family-aws) to avoid
# duplicate package lock entries when ArgoCD syncs the same chart later.
resource "kubectl_manifest" "crossplane_provider_family" {
  yaml_body = yamlencode({
    apiVersion = "pkg.crossplane.io/v1"
    kind       = "Provider"
    metadata = {
      name = "upbound-provider-family-aws"
    }
    spec = {
      package = "xpkg.upbound.io/upbound/provider-family-aws:v2.5.3"
      runtimeConfigRef = {
        name = "iam-drc"
      }
    }
  })

  depends_on = [helm_release.crossplane]
}

# --- External Secrets Operator (chicken-and-egg: installed before ArgoCD can manage it) ---
resource "helm_release" "external_secrets" {
  name             = "external-secrets"
  repository       = "https://charts.external-secrets.io"
  chart            = "external-secrets"
  version          = var.eso_version
  namespace        = "external-secrets"
  create_namespace = true
  wait             = true
  timeout          = 600

  values = [yamlencode({
    serviceAccount = { name = "external-secrets-sa" }
  })]

  depends_on = [aws_eks_cluster.hub]
}
