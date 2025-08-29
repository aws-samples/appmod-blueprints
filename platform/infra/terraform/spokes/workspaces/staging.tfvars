vpc_cidr           = "10.2.0.0/16"
kubernetes_version = "1.31"

git_hostname                    = ""
git_org_name                    = "user1"

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
gitops_workload_repo_base_path  = "gitops/workloads/"
gitops_workload_repo_path       = ""
gitops_workload_repo_revision   = "main"
