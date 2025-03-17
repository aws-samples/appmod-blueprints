resource "kubectl_manifest" "application_kubevela" {
  yaml_body = templatefile("${path.module}/templates/argocd-apps/kubevela.yaml", {
      GITHUB_URL = local.repo_url
      GITHUB_BRANCH = local.repo_branch
    }
  )
}