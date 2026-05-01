# ArgoCD via EKS Blueprints Addons — AWS-maintained bootstrap pattern
# aws_eks_capability is not yet available in the Terraform AWS provider

module "eks_blueprints_addons" {
  source  = "aws-ia/eks-blueprints-addons/aws"
  version = "~> 1.0"

  cluster_name      = module.eks.cluster_name
  cluster_endpoint  = module.eks.cluster_endpoint
  cluster_version   = module.eks.cluster_version
  oidc_provider_arn = module.eks.oidc_provider_arn

  enable_argocd = true
  argocd = {
    namespace     = "argocd"
    chart_version = "7.8.0"
  }

  tags = local.tags
}

# App-of-apps root Application — ArgoCD watches gitops/apps/ in the repo
resource "kubectl_manifest" "argocd_app_of_apps" {
  yaml_body = <<-YAML
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: openclaw-apps
      namespace: argocd
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: default
      source:
        repoURL: ${var.gitops_repo_url}
        targetRevision: ${var.gitops_target_revision}
        path: openclaw-platform/gitops/apps
      destination:
        server: https://kubernetes.default.svc
        namespace: argocd
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
  YAML

  depends_on = [module.eks_blueprints_addons]
}
