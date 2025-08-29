resource "kubectl_manifest" "application_kyverno" {
  yaml_body = file("${path.module}/templates/argocd-apps/kyverno.yaml")
}

resource "kubectl_manifest" "application_kyverno_enforce" {
  depends_on = [
    kubectl_manifest.application_kyverno,
  ]
  yaml_body = file("${path.module}/templates/argocd-apps/kyverno-enforce.yaml")
}

resource "kubectl_manifest" "application_kyverno_enforce_exceptions" {
  depends_on = [
    kubectl_manifest.application_kyverno_enforce,
  ]
  yaml_body = templatefile("${path.module}/templates/argocd-apps/kyverno-enforce-exceptions.yaml", {
    GITHUB_URL = local.repo_url
    GITHUB_BRANCH = local.repo_branch
  }
  )
}