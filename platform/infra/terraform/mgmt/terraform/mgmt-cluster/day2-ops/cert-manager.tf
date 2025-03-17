resource "kubectl_manifest" "application_argocd_cert_manager" {
  yaml_body = templatefile("${path.module}/templates/argocd-apps/cert-manager.yaml", {
    GITHUB_URL = local.repo_url
    GITHUB_BRANCH = local.repo_branch
  })

  provisioner "local-exec" {
    command = "kubectl wait --for=jsonpath=.status.health.status=Healthy --timeout=300s -n argocd application/cert-manager"

    interpreter = ["/bin/bash", "-c"]
  }
}