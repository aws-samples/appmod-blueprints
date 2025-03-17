resource "random_password" "backstage_postgres_password" {
  length           = 16
  special          = false
  # override_special = "!#"
}

resource "kubernetes_manifest" "namespace_backstage" {
  manifest = {
    "apiVersion" = "v1"
    "kind" = "Namespace"
    "metadata" = {
      "name" = "backstage"
    }
  }
}

resource "kubernetes_manifest" "secret_backstage_postgresql_config" {
  depends_on = [
    kubernetes_manifest.namespace_backstage
  ]

  manifest = {
    "apiVersion" = "v1"
    "kind" = "Secret"
    "metadata" = {
      "name" = "postgresql-config"
      "namespace" = "backstage"
    }
    "data" = {
      "POSTGRES_DB" = "${base64encode("backstage")}"
      "POSTGRES_PASSWORD" = "${base64encode(random_password.backstage_postgres_password.result)}"
      "POSTGRES_USER" = "${base64encode("backstage")}"
    }
  }
}

# Fetch the initial admin secret from ArgoCD
data "kubernetes_secret" "argocd-initial-admin-secret" {
  metadata {
    name      = "argocd-initial-admin-secret"
    namespace = "argocd"
  }
}

# create a new secret by name argocd-credentials in backstage namespace referencing argocd-initial-admin-secret for username and password
resource "kubernetes_manifest" "secret_backstage_argocd_credentials" {
  depends_on = [
    kubernetes_manifest.namespace_backstage,
    data.kubernetes_secret.argocd-initial-admin-secret
  ]

  manifest = {
    "apiVersion" = "v1"
    "kind" = "Secret"
    "metadata" = {
      "name" = "argocd-credentials"
      "namespace" = "backstage"
    }
    "data" = {
      ARGOCD_ADMIN_PASSWORD = "${base64encode(data.kubernetes_secret.argocd-initial-admin-secret.data.password)}"
    }
  }
}

resource "kubernetes_manifest" "secret_gitea_backstage_credential" {
  depends_on = [
    kubernetes_manifest.namespace_backstage
  ]

  manifest = {
    "apiVersion" = "v1"
    "kind" = "Secret"
    "metadata" = {
      "name" = "gitea-credentials"
      "namespace" = "backstage"
    }
    "data" = {
      "username" = "${base64encode("giteaAdmin")}"
      "password" = "${base64encode("mysecretgiteapassword!")}"
    }
  }
}

resource "terraform_data" "backstage_keycloak_setup" {
  depends_on = [
    kubectl_manifest.application_argocd_keycloak,
    kubernetes_manifest.namespace_backstage
  ]

  provisioner "local-exec" {
    command = "./install.sh ${random_password.backstage_postgres_password.result} ${local.domain_name}"

    working_dir = "${path.module}/scripts/backstage"
    interpreter = ["/bin/bash", "-c"]
  }

  provisioner "local-exec" {
    when = destroy

    command = "./uninstall.sh"

    working_dir = "${path.module}/scripts/backstage"
    interpreter = ["/bin/bash", "-c"]
  }
}

resource "kubectl_manifest" "application_argocd_backstage" {
  depends_on = [
    terraform_data.backstage_keycloak_setup
  ]

  yaml_body = templatefile("${path.module}/templates/argocd-apps/backstage.yaml", {
      GITHUB_URL = local.repo_url
      GITHUB_BRANCH = local.repo_branch
    }
  )
}

resource "kubectl_manifest" "ingress_backstage" {
  depends_on = [
    kubectl_manifest.application_argocd_backstage,
  ]

  yaml_body = templatefile("${path.module}/templates/manifests/ingress-backstage.yaml", {
      BACKSTAGE_DOMAIN_NAME = local.domain_name
    }
  )
}
