# Helm + kubectl resources applied to the hub cluster
# ESO, ClusterSecretStore, seed cluster secret, root-appset

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
    aws_eks_pod_identity_association.eso,
    aws_eks_capability.argocd,
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
        addonsRepoURL      = var.repo_url
        addonsRepoRevision = var.repo_revision
        addonsRepoBasepath = var.repo_basepath
        fleetRepoURL       = var.repo_url
        fleetRepoRevision  = var.repo_revision
        fleetRepoBasepath  = var.repo_basepath
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
