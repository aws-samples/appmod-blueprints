#---------------------------------------------------------------
# Gitea installation
#---------------------------------------------------------------
resource "kubernetes_manifest" "namespace_gitea" {
  manifest = {
    "apiVersion" = "v1"
    "kind" = "Namespace"
    "metadata" = {
      "name" = "gitea"
    }
  }
}

resource "kubernetes_manifest" "secret_gitea_credentials" {
  depends_on = [
    kubernetes_manifest.namespace_gitea
  ]

  manifest = {
    "apiVersion" = "v1"
    "kind" = "Secret"
    "metadata" = {
      "name" = "gitea-credential"
      "namespace" = "gitea"
    }
    "data" = {
      "username" = "${base64encode("giteaAdmin")}"
      "password" = "${base64encode("mysecretgiteapassword!")}"
    }
  }
}

resource "terraform_data" "gitea_setup" {
  depends_on = [
    kubernetes_manifest.namespace_gitea
  ]

  provisioner "local-exec" {
    command = "./install.sh ${local.domain_name}"

    working_dir = "${path.module}/scripts/gitea"
    interpreter = ["/bin/bash", "-c"]
  }

  provisioner "local-exec" {
    when = destroy

    command = "./uninstall.sh"

    working_dir = "${path.module}/scripts/gitea"
    interpreter = ["/bin/bash", "-c"]
  }
}

resource "kubectl_manifest" "ingress_gitea" {
  depends_on = [
    terraform_data.gitea_setup
  ]

  yaml_body = templatefile("${path.module}/templates/manifests/ingress-gitea.yaml", {
    GITEA_DOMAIN_NAME = local.domain_name
  }
  )
}


