# --- Inputs matching config.yaml contract ---

variable "cluster_name" {
  description = "Hub cluster name (hub.clusterName)"
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version (hub.kubernetesVersion)"
  type        = string
  default     = "1.35"
}

variable "vpc_cidr" {
  description = "VPC CIDR block (hub.vpcCidr)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "aws_region" {
  description = "AWS region (aws.region)"
  type        = string
}

variable "aws_account_id" {
  description = "AWS account ID (aws.accountId)"
  type        = string
}

# Git repo coordinates
variable "repo_url" {
  description = "Git repository URL (repo.url)"
  type        = string
}

variable "repo_revision" {
  description = "Git branch or tag (repo.revision)"
  type        = string
  default     = "main"
}

variable "repo_basepath" {
  description = "Path prefix in the repo (repo.basepath)"
  type        = string
  default     = "gitops/"
}

# Domain and networking
variable "domain" {
  description = "Base domain for ingress (domain)"
  type        = string
}

variable "resource_prefix" {
  description = "Prefix for tenant-facing resources (resourcePrefix)"
  type        = string
  default     = ""
}

variable "ingress_name" {
  description = "Ingress name override (ingressName)"
  type        = string
  default     = ""
}

variable "ingress_security_groups" {
  description = "Ingress security groups (ingressSecurityGroups)"
  type        = string
  default     = ""
}

# Identity Center (for EKS ArgoCD Capability)
variable "idc_instance_arn" {
  description = "AWS Identity Center instance ARN (identityCenter.instanceArn)"
  type        = string
}

variable "idc_region" {
  description = "Identity Center region (identityCenter.region)"
  type        = string
}

variable "idc_admin_group_id" {
  description = "Identity Center admin group ID (identityCenter.adminGroupId)"
  type        = string
}

# ArgoCD Capability
variable "argocd_capability_name" {
  description = "EKS ArgoCD capability name (argocdCapability.name)"
  type        = string
  default     = "argocd"
}

# Addon versions — read from registry, never hardcoded
variable "eso_version" {
  description = "External Secrets Operator Helm chart version (from addons/registry/core.yaml)"
  type        = string
  default     = "0.19.2"
}

# Root appset path
variable "root_appset_path" {
  description = "Path to bootstrap/root-appset.yaml relative to repo root"
  type        = string
  default     = "../gitops/bootstrap/root-appset.yaml"
}
