aws_region           = "us-west-2"
eks_cluster_name     = "import-eks-cluster-for-irsa"
namespace            = "irsa"
service_account_name = "eks-service-account"
iam_policies = {
  "policy1" = "AmazonEKSServicePolicy"
  "policy2" = "AmazonS3ReadOnlyAccess"
}

