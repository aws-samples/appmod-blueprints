variable "aws_region" {
  description = "AWS Region"
  type        = string
  default = "us-west-2"
}

variable "tfe_project" {
  description = "Unique project name for terraform lock file"
  type        = string
  default = "eks-accelerator"
}

variable "grafana_keycloak_idp_url" {
  description = "Unique project name for terraform lock file"
  type        = string
  default = "http://modern-engg-xxxxxx.elb.us-west-2.amazonaws.com/keycloak/realms/grafana/protocol/saml/descriptor"
}

variable "eks_cluster_private_subnets" {
  description = "VPC Private subnets for AMG configuration"
  type = list(string)
}

variable "eks_cluster_node_security_group_id" {
  description = "VPC security groups for AMG configuration"
  type = string

}
