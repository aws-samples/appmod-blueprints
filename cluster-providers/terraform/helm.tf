# Helm + kubectl resources applied to the hub cluster
# Crossplane, ESO, ClusterSecretStore, seed cluster secret, root-appset

# --- Crossplane (must be running before ArgoCD syncs crossplane-base) ---
resource "helm_release" "crossplane" {
  name             = "crossplane"
  repository       = "https://charts.crossplane.io/stable"
  chart            = "crossplane"
  version          = "2.2.1"
  namespace        = "crossplane-system"
  create_namespace = true
  wait             = true
  timeout          = 300

  depends_on = [aws_eks_cluster.hub]
}

# --- Crossplane Providers + ProviderConfig ---
# Install providers with correct service accounts so they pick up pod identity immediately
resource "kubectl_manifest" "crossplane_provider_config" {
  yaml_body = yamlencode({
    apiVersion = "aws.upbound.io/v1beta1"
    kind       = "ProviderConfig"
    metadata = {
      name = "default"
    }
    spec = {
      credentials = {
        source = "PodIdentity"
      }
    }
  })

  depends_on = [helm_release.crossplane]
}

resource "kubectl_manifest" "crossplane_drc" {
  for_each = local.crossplane_providers

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
  for_each = { for k, v in local.crossplane_providers : k => v if v.namespace == "crossplane-system" }

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
  for_each = {
    iam            = { package = "xpkg.upbound.io/upbound/provider-aws-iam:v2.5.3" }
    eks            = { package = "xpkg.upbound.io/upbound/provider-aws-eks:v2.5.3" }
    ec2            = { package = "xpkg.upbound.io/upbound/provider-aws-ec2:v2.5.3" }
    secretsmanager = { package = "xpkg.upbound.io/upbound/provider-aws-secretsmanager:v2.5.3" }
  }

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
resource "kubectl_manifest" "crossplane_provider_family" {
  yaml_body = yamlencode({
    apiVersion = "pkg.crossplane.io/v1"
    kind       = "Provider"
    metadata = {
      name = "provider-family-aws"
    }
    spec = {
      package = "xpkg.upbound.io/upbound/provider-family-aws:v2.5.3"
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
  timeout          = 300

  values = [yamlencode({
    serviceAccount = { name = "external-secrets-sa" }
  })]

  depends_on = [
    aws_eks_cluster.hub,
    aws_eks_capability.argocd,
    kubectl_manifest.crossplane_provider,
  ]
}

# --- ClusterSecretStore for AWS Secrets Manager ---
resource "kubectl_manifest" "cluster_secret_store" {
  yaml_body = yamlencode({
    apiVersion = "external-secrets.io/v1"
    kind       = "ClusterSecretStore"
    metadata = {
      name = "aws-secrets-manager"
    }
    spec = {
      provider = {
        aws = {
          service = "SecretsManager"
          region  = var.aws_region
        }
      }
    }
  })

  depends_on = [helm_release.external_secrets]
}

# --- Seed cluster secret (minimal — just enough for root-appset to target the hub) ---
resource "kubectl_manifest" "seed_secret" {
  yaml_body = yamlencode({
    apiVersion = "v1"
    kind       = "Secret"
    type       = "Opaque"
    metadata = {
      name      = var.cluster_name
      namespace = "argocd"
      labels = {
        "argocd.argoproj.io/secret-type" = "cluster"
        fleet_member                     = "control-plane"
        environment                      = "control-plane"
      }
      annotations = {
        addonsRepoURL           = var.repo_url
        addonsRepoRevision      = var.repo_revision
        addonsRepoBasepath      = var.repo_basepath
        fleetRepoURL            = var.repo_url
        fleetRepoRevision       = var.repo_revision
        fleetRepoBasepath       = var.repo_basepath
        aws_cluster_name        = var.cluster_name
        aws_region              = var.aws_region
        aws_account_id          = var.aws_account_id
        aws_vpc_id              = aws_vpc.hub.id
        ingress_domain_name     = var.domain
        ingress_name            = var.ingress_name
        ingress_security_groups = var.ingress_security_groups
        resource_prefix         = var.resource_prefix
      }
    }
    stringData = {
      name   = var.cluster_name
      server = aws_eks_cluster.hub.arn
      config = jsonencode({ tlsClientConfig = { insecure = false } })
    }
  })

  depends_on = [aws_eks_capability.argocd]
}

# --- Root ApplicationSet (bootstrap handoff to ArgoCD) ---
resource "kubectl_manifest" "root_appset" {
  yaml_body = file(var.root_appset_path)

  depends_on = [
    kubectl_manifest.seed_secret,
    kubectl_manifest.cluster_secret_store,
  ]
}
