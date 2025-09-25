variable "hub_vpc_id" {
  description = "VPC id for Hub cluster"
  type        = string
}

variable "hub_subnet_ids" {
  description = "Subnet id for Hub cluster"
  type        = list(string)
}

variable "resource_prefix" {
  description = "Prefix for project"
  type        = string
  default     = "peeks"
}

variable "workshop_participant_role_arn" {
  description = "AWS Workshop participant role ARN"
  type        = string
  default     = ""
}

# Cluster configurations
variable "clusters" {
  description = "Cluster configuration"
  type = map(object({
    name = string
    region = string
    kubernetes_version = string
    environment = string
    auto_mode = bool
    addons = map(bool)
  }))
}