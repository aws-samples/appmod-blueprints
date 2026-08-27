# EKS cluster with Auto Mode — mirrors Crossplane composition's eks-cluster resource

data "aws_caller_identity" "current" {}

resource "aws_eks_cluster" "hub" {
  name     = var.cluster_name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  bootstrap_self_managed_addons = false

  access_config {
    authentication_mode = "API"
  }

  vpc_config {
    endpoint_private_access = true
    endpoint_public_access  = true
    subnet_ids              = concat(aws_subnet.public[*].id, aws_subnet.private[*].id)
  }

  compute_config {
    enabled       = true
    node_pools    = ["general-purpose", "system"]
    node_role_arn = aws_iam_role.node.arn
  }

  storage_config {
    block_storage {
      enabled = true
    }
  }

  kubernetes_network_config {
    elastic_load_balancing {
      enabled = true
    }
  }

  tags = local.common_tags

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

# --- Access Entries ---
# Caller gets cluster admin
resource "aws_eks_access_entry" "caller" {
  cluster_name  = aws_eks_cluster.hub.name
  principal_arn = local.caller_role_arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "caller" {
  cluster_name  = aws_eks_cluster.hub.name
  principal_arn = local.caller_role_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.caller]
}

# ArgoCD capability role gets cluster admin (for managing workloads)
resource "aws_eks_access_entry" "argocd" {
  cluster_name  = aws_eks_cluster.hub.name
  principal_arn = aws_iam_role.argocd_capability.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "argocd" {
  cluster_name  = aws_eks_cluster.hub.name
  principal_arn = aws_iam_role.argocd_capability.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  access_scope { type = "cluster" }
  depends_on = [aws_eks_access_entry.argocd]
}

locals {
  # Convert arn:aws:sts::ACCT:assumed-role/ROLE/session -> arn:aws:iam::ACCT:role/ROLE
  caller_arn      = data.aws_caller_identity.current.arn
  is_assumed_role = length(regexall(":assumed-role/", local.caller_arn)) > 0
  caller_role_arn = local.is_assumed_role ? "arn:aws:iam::${var.aws_account_id}:role/${regex(":assumed-role/([^/]+)", local.caller_arn)[0]}" : local.caller_arn
}
