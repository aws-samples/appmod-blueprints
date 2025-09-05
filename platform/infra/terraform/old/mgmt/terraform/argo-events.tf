resource "kubectl_manifest" "applications-argocd-argo-events" {
  yaml_body = file("${path.module}/templates/argocd-apps/argo-events.yaml")
}

