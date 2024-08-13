variable "aws_region" {
  description = "AWS region for the EKS cluster"
  type        = string
  default     = "us-west-2"
}

variable "eks_cluster_name" {
  description = "Name of the existing EKS cluster"
  type        = string
  default     = "import-eks-cluster-for-irsa"
}

variable "namespace" {
  description = "Namespace to create in the EKS cluster"
  type        = string
  default     = "irsa"
}

