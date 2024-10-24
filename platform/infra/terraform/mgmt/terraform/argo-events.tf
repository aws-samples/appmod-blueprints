resource "kubectl_manifest" "applications-argocd-argo-events" {
  yaml_body = templatefile("${path.module}/templates/argocd-apps/argo-events.yaml", {
    GITHUB_URL = "https://argoproj.github.io/argo-helm"
    }
  )
}

