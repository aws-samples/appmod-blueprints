resource "kubectl_manifest" "application_argocd_cert_manager" {
  yaml_body = templatefile("${path.module}/templates/argocd-apps/cert-manager.yaml", {
    REPO_URL = local.repo_url
  })
}

resource "terraform_data" "wait_for_cert_manager" {
  provisioner "local-exec" {
    command = "kubectl wait --for=jsonpath=.status.health.status=Healthy -n argocd application/cert-manager && kubectl wait --for=jsonpath=.status.sync.status=Synced --timeout=900s -n argocd application/cert-manager"
  }

  depends_on = [kubectl_manifest.application_argocd_cert_manager]
}
