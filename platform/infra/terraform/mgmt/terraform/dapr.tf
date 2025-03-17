resource "kubectl_manifest" "application_dapr_system" {
  yaml_body = file("${path.module}/templates/argocd-apps/dapr.yaml")
}
