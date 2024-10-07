resource "kubectl_manifest" "application_kubevela" {
  yaml_body = templatefile("${path.module}/templates/argocd-apps/kubevela.yaml", {
      GITHUB_URL = "https://kubevela.github.io/charts"
    }
  )
}