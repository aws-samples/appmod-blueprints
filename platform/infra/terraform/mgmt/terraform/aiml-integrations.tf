data "http" "spark_operator_manifestfile" {
  count = local.aiml_integrations_count
  url   = "https://raw.githubusercontent.com/cnoe-io/stacks/main/ref-implementation/spark-operator.yaml"
}
resource "kubectl_manifest" "spark_operator_manifest" {
  count     = local.aiml_integrations_count
  yaml_body = data.http.spark_operator_manifestfile[0].response_body
}

resource "kubectl_manifest" "application_argocd_ray_operator_crds" {
  count     = local.aiml_integrations_count
  yaml_body = templatefile("${path.module}/templates/argocd-apps/ray-operator-crds.yaml", {
    GITHUB_URL = local.repo_url
  }
  )
}

resource "kubectl_manifest" "application_argocd_ray_operator_install" {
  count     = local.aiml_integrations_count
  yaml_body = templatefile("${path.module}/templates/argocd-apps/ray-operator.yaml", {
    GITHUB_URL = local.repo_url
  }
  )
}