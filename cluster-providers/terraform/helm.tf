# Helm resources applied to the hub cluster before ArgoCD takes over.
#
# Crossplane (core, providers, DeploymentRuntimeConfigs, ProviderConfig) is NOT
# installed here — ArgoCD installs it via the `crossplane` + `crossplane-base`
# addons (same as the kind-kro-ack provider, which bootstraps no crossplane in
# its Taskfile). Terraform owns the crossplane provider pod-identity roles +
# associations (see iam.tf), so crossplane no longer needs to be up at bootstrap
# to create identities, and crossplane-base already ships the PodIdentity
# ProviderConfig — so the previous pre-ArgoCD ProviderConfig apply was redundant.
#
# Only ESO is installed here: it must exist before ArgoCD so the seed secret /
# ClusterSecretStore can be created and addons' ExternalSecrets resolve on first sync.

# --- External Secrets Operator (installed before ArgoCD can manage it) ---
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
