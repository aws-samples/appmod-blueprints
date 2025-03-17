data "http" "spark_operator_manifestfile" {
  count = local.aiml_integrations_count
  url   = "https://raw.githubusercontent.com/cnoe-io/stacks/main/ref-implementation/spark-operator.yaml"
}
resource "kubectl_manifest" "spark_operator_manifest" {
  count     = local.aiml_integrations_count
  yaml_body = data.http.spark_operator_manifestfile[0].response_body
}

resource "kubectl_manifest" "application_argocd_ray_operator_crds" {
  count = local.aiml_integrations_count
  yaml_body = templatefile("${path.module}/templates/argocd-apps/ray-operator-crds.yaml", {
    GITHUB_URL = local.repo_url
    }
  )
}

resource "kubectl_manifest" "application_argocd_ray_operator_install" {
  count = local.aiml_integrations_count
  yaml_body = templatefile("${path.module}/templates/argocd-apps/ray-operator.yaml", {
    GITHUB_URL = local.repo_url
    }
  )
}
resource "kubernetes_manifest" "namespace_jupyterhub" {
  count = local.aiml_integrations_count
  manifest = {
    "apiVersion" = "v1"
    "kind"       = "Namespace"
    "metadata" = {
      "name" = "jupyterhub"
    }
  }
}

resource "terraform_data" "jupyterhub-setup" {
  count = local.aiml_integrations_count
  depends_on = [
    kubectl_manifest.application_argocd_keycloak,
    kubernetes_manifest.namespace_jupyterhub
  ]

  provisioner "local-exec" {
    command = "./install.sh ${local.domain_name}"

    working_dir = "${path.module}/scripts/jupyterhub"
    interpreter = ["/bin/bash", "-c"]
  }

  provisioner "local-exec" {
    when = destroy

    command = "./uninstall.sh"

    working_dir = "${path.module}/scripts/jupyterhub"
    interpreter = ["/bin/bash", "-c"]
  }
}
resource "kubectl_manifest" "applications-argocd-jupyterhub" {
  count = local.aiml_integrations_count
  depends_on = [
    terraform_data.jupyterhub-setup
  ]
  yaml_body = templatefile("${path.module}/templates/argocd-apps/jupyterhub.yaml", {
    JUPYTERHUB_URL = "https://${local.domain_name}/jupyterhub",
    KC_URL         = local.kc_url
    }
  )
}

resource "kubectl_manifest" "ingress-jupyterhub" {
  count = local.aiml_integrations_count
  depends_on = [
    kubectl_manifest.applications-argocd-jupyterhub,
  ]
  yaml_body = templatefile("${path.module}/templates/manifests/ingress-jupyterhub.yaml", {
    JUPYTERHUB_DOMAIN_NAME = local.domain_name
    }
  )
}

