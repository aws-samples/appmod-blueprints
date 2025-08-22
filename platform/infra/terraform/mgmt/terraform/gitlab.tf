#---------------------------------------------------------------
# Gitea installation
#---------------------------------------------------------------
resource "kubernetes_manifest" "namespace_gitlab" {
  manifest = {
    "apiVersion" = "v1"
    "kind" = "Namespace"
    "metadata" = {
      "name" = "gitlab"
    }
  }
}

resource "kubernetes_manifest" "secret_gitlab_credentials" {
  depends_on = [
    kubernetes_manifest.namespace_gitlab
  ]

  manifest = {
    "apiVersion" = "v1"
    "kind" = "Secret"
    "metadata" = {
      "name" = "gitlab-credential"
      "namespace" = "gitlab"
    }
    "data" = {
      "username" = "${base64encode("root")}"
      "password" = "${base64encode("Changeme!2345")}"
    }
  }
}

resource "terraform_data" "gitlab_setup" {
  depends_on = [
    kubernetes_manifest.namespace_gitlab
  ]

  provisioner "local-exec" {
    command = "./install.sh"

    working_dir = "${path.module}/scripts/gitlab"
    interpreter = ["/bin/bash", "-c"]
  }

  provisioner "local-exec" {
    when = destroy

    command = "./uninstall.sh"

    working_dir = "${path.module}/scripts/gitlab"
    interpreter = ["/bin/bash", "-c"]
  }
}