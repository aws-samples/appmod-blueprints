variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-west-2"
}

variable "bedrock_region" {
  description = "AWS region for Bedrock inference (use cross-region inference profile region)"
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Project name used as prefix for all resources"
  type        = string
  default     = "openclaw"
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS cluster"
  type        = string
  default     = "1.32"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_kata_nodes" {
  description = "Whether to deploy bare-metal Kata container node group"
  type        = bool
  default     = true
}

variable "kata_instance_types" {
  description = "Bare-metal instance types for Kata container nodes"
  type        = list(string)
  default     = ["c5.metal", "m5.metal"]
}

variable "kata_ami_id" {
  description = "Pre-built Kata AMI ID. If empty, Packer will bake one on first apply."
  type        = string
  default     = ""
}

variable "cluster_endpoint_public_access" {
  description = "Whether the EKS cluster API endpoint is publicly accessible"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "admin_role_arns" {
  description = "IAM role ARNs granted cluster-admin via EKS access entries (auditable via CloudTrail)"
  type        = list(string)
  default     = []
}

variable "gitops_repo_url" {
  description = "Git repository URL ArgoCD watches for app-of-apps (e.g. https://github.com/org/eks-platform-openclaw)"
  type        = string
}

variable "gitops_target_revision" {
  description = "Git branch/tag ArgoCD tracks"
  type        = string
  default     = "HEAD"
}

variable "route53_zone_id" {
  description = "Route53 public hosted zone ID that external-dns manages records in"
  type        = string
}

variable "route53_zone_name" {
  description = "Route53 zone name (domain) external-dns filters on"
  type        = string
}

variable "wildcard_cert_arn" {
  description = "ACM certificate ARN for the wildcard domain (set in terraform.tfvars — not committed)"
  type        = string
}

variable "finance_ui_host" {
  description = "Public hostname for the finance assistant UI (e.g. finassist.example.com)"
  type        = string
}
