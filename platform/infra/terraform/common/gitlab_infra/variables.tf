variable "resource_prefix" {
  description = "Prefix for project"
  type        = string
  default     = "peeks"
}

variable "git_password" {
  description = "Password to login on the Gitea instance"
  type        = string
  sensitive   = true
  default     = ""
}

variable "git_username" {
  description = "Git username for workshop"
  type        = string
  default     = "user1"
}

variable "working_repo" {
  description = "Working repository name"
  type        = string
  default     = "platform-on-eks-workshop"
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
    path= string
    basepath = string
  })
  default = {
    url      = "https://github.com/aws-samples/appmod-blueprints"
    revision = "main"
    path = "bootstrap"
    basepath = "gitops/fleet/"
  }
}

# Cluster configurations
variable "clusters" {
  description = "Cluster configuration"
  type = map(object({
    name = string
    region = string
    environment = string
    auto_mode = bool
    addons = map(bool)
  }))
  default = {
    hub = {
      name = "hub"
      region = "us-west-2"
      environment = "control-plane"
      auto_mode = true
      addons = {}
    }
    spoke1 = {
      name = "spoke-dev"
      region = "us-west-2"
      environment = "dev"
      auto_mode = true
      addons = {}
    }
    spoke2 = {
      name = "spoke-prod"
      region = "us-west-2"
      environment = "prod"
      auto_mode = true
      addons = {}
    }
  }
}
