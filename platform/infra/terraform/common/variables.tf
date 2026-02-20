################################################################################
# Usage Telemetry
################################################################################

variable "usage_tracking_tag" {
  description = "Tag to identify Modern Engineering on AWS usage within tracking tools"
  type        = string
  default     = "uksb-u7h6yeonth"
}

variable "resource_prefix" {
  description = "Prefix for project"
  type        = string
  default     = "peeks"
}

variable "git_password" {
  description = "Password to login on the Git instance"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ide_password" {
  description = "IDE password for workshop admin accounts"
  type        = string
  sensitive   = true
}

variable "git_username" {
  description = "Git username for workshop"
  type        = string
  default     = "user1"
}

variable "gitlab_domain_name" {
  description = "Domain name"
  type        = string
  default     = "gitlab.cnoe.io"
}

variable "gitlab_security_groups" {
  description = "Domain name"
  type        = string
  default     = ""
}
variable "domain_name" {
  description = "Domain name"
  type        = string
  default     = "cnoe.io"
}

variable "repo" {
  description = "Repository configuration"
  type = object({
    url      = string
    revision = string
    path     = string
    basepath = string
  })
  default = {
    url      = "https://github.com/aws-samples/appmod-blueprints"
    revision = "main"
    path     = "bootstrap"
    basepath = "gitops/fleet/"
  }
}

# Cluster configurations
variable "clusters" {
  description = "Cluster configuration"
  type = map(object({
    name               = string
    region             = string
    kubernetes_version = string
    environment        = string
    auto_mode          = bool
    addons             = map(bool)
    tenant             = string
  }))
  default = {
    hub = {
      name               = "hub"
      region             = "us-west-2"
      kubernetes_version = "1.34"
      environment        = "control-plane"
      auto_mode          = true
      addons             = {}
      tenant             = "default"
    }
    spoke1 = {
      name               = "spoke-dev"
      region             = "us-west-2"
      kubernetes_version = "1.34"
      environment        = "dev"
      auto_mode          = true
      addons             = {}
      tenant             = "default"
    }
    spoke2 = {
      name               = "spoke-prod"
      region             = "us-west-2"
      kubernetes_version = "1.34"
      environment        = "prod"
      auto_mode          = true
      addons             = {}
      tenant             = "default"
    }
  }
}

variable "tenant" {
  description = "Name of the tenant for the Hub Cluster"
  type        = string
  default     = "control-plane"
}
variable "gitops_addons_repo_name" {
  description = "The name of git repo"
  default     = "platform-on-eks-workshop"
}

variable "gitops_addons_repo_path" {
  description = "The path of addons bootstraps in the repo"
  default     = "bootstrap"
}

variable "gitops_addons_repo_base_path" {
  description = "The base path of addons in the repon"
  default     = "gitops/addons/"
}

variable "gitops_addons_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}
# Fleet
variable "gitops_fleet_repo_name" {
  description = "The name of Git repo"
  default     = "platform-on-eks-workshop"
}

variable "gitops_fleet_repo_path" {
  description = "The path of fleet bootstraps in the repo"
  default     = "bootstrap"
}

variable "gitops_fleet_repo_base_path" {
  description = "The base path of fleet in the repon"
  default     = "gitops/fleet/"
}

variable "gitops_fleet_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}

# workload
variable "gitops_workload_repo_name" {
  description = "The name of Git repo"
  default     = "platform-on-eks-workshop"
}

variable "gitops_workload_repo_path" {
  description = "The path of workload bootstraps in the repo"
  default     = ""
}

variable "gitops_workload_repo_base_path" {
  description = "The base path of workloads in the repo"
  default     = "gitops/apps/"
}

variable "gitops_workload_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}

# Platform
variable "gitops_platform_repo_name" {
  description = "The name of Git repo"
  default     = "platform-on-eks-workshop"
}

variable "gitops_platform_repo_path" {
  description = "The path of platform bootstraps in the repo"
  default     = "bootstrap"
}

variable "gitops_platform_repo_base_path" {
  description = "The base path of platform in the repo"
  default     = "gitops/platform/"
}

variable "gitops_platform_repo_revision" {
  description = "The name of branch or tag"
  default     = "main"
}

variable "backstage_image" {
  description = "backstage image for workshop"
  type        = string
  default     = "public.ecr.aws/seb-demo/backstage:latest"
}

variable "working_repo" {
  description = "Working repository name"
  type        = string
  default     = "platform-on-eks-workshop"
}
