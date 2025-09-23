vpc_name                        = "peeks-hub-cluster"  # Will be overridden by deploy.sh
kubernetes_version              = "1.32"
cluster_name                    = "peeks-hub-cluster"  # Will be overridden by deploy.sh
ingress_name                    = "peeks-hub-ingress"
tenant                          = "tenant1"

git_hostname                    = ""
git_org_name                    = "user1"
backstage_image                 = "" # ghcr.io/cnoe-io/backstage-app:135c0cb26f3e004a27a11edb6a4779035aff9805

gitops_addons_repo_name         = "platform-on-eks-workshop"
gitops_addons_repo_base_path    = "gitops/addons/"
gitops_addons_repo_path         = "bootstrap"
gitops_addons_repo_revision     = "main"

gitops_fleet_repo_name          = "platform-on-eks-workshop"
gitops_fleet_repo_base_path     = "gitops/fleet/"
gitops_fleet_repo_path          = "bootstrap"
gitops_fleet_repo_revision      = "main"

gitops_platform_repo_name       = "platform-on-eks-workshop"
gitops_platform_repo_base_path  = "gitops/platform/"
gitops_platform_repo_path       = "bootstrap"
gitops_platform_repo_revision   = "main"

gitops_workload_repo_name       = "platform-on-eks-workshop"
gitops_workload_repo_base_path  = "gitops/apps/"
gitops_workload_repo_path       = ""
gitops_workload_repo_revision   = "main"


# AWS Accounts used for demo purposes (cluster1 cluster2)
account_ids = "<aws_account_id>" # update this with your spoke aws accounts ids

# Enabled addons for hub cluster
addons = {
  enable_ack_dynamodb                 = true
  enable_ack_ec2                      = true
  enable_ack_efs                      = true
  enable_ack_eks                      = true
  enable_ack_iam                      = true
  enable_ack_s3                       = true
  enable_argocd                       = true
  enable_argo_rollouts                = true
  enable_argo_workflows               = true
  enable_backstage                    = true
  enable_cert_manager                 = true
  enable_crossplane                   = true
  enable_external_secrets             = true
  enable_flux                         = true
  enable_gitlab                       = true
  enable_grafana                      = true
  enable_ingress_class_alb            = true
  enable_ingress_nginx                = true
  enable_kargo                        = true
  enable_keycloak                     = true
  enable_kro                          = true
  enable_kro_eks_rgs                  = true
  enable_kubevela                     = true
  enable_kyverno                      = true
  enable_kyverno_policies             = true
  enable_kyverno_policy_reporter      = true
  enable_metrics_server               = true
  enable_mutli_acct                   = true
}
