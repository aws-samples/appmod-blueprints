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

variable "service_account_name" {
  description = "Name of service account to create for IRSA"
  type        = string
  default     = "eks-service-account"
}

variable "iam_policies" {
  description = "Map of policies to add to service account role"
  type        = map(string)
  default = {
    "policy1" = "AmazonEKSServicePolicy"
  }
}




