# IAM roles — mirrors Crossplane composition + crossplane-pod-identity chart
# Cluster role, node role, ArgoCD capability role, ESO pod identity role

# ===== EKS Cluster Role (Auto Mode) =====
resource "aws_iam_role" "cluster" {
  name = "${var.cluster_name}-cluster-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
    "arn:aws:iam::aws:policy/AmazonEKSComputePolicy",
    "arn:aws:iam::aws:policy/AmazonEKSNetworkingPolicy",
    "arn:aws:iam::aws:policy/AmazonEKSBlockStoragePolicy",
    "arn:aws:iam::aws:policy/AmazonEKSLoadBalancingPolicy",
  ])
  role       = aws_iam_role.cluster.name
  policy_arn = each.value
}

# ===== EKS Auto Mode Node Role =====
resource "aws_iam_role" "node" {
  name = "${var.cluster_name}-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodeMinimalPolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPullOnly",
  ])
  role       = aws_iam_role.node.name
  policy_arn = each.value
}

# ===== ArgoCD Capability Role =====
resource "aws_iam_role" "argocd_capability" {
  name = "${var.cluster_name}-ArgoCDCapabilityRole"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "capabilities.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags = merge(local.common_tags, { purpose = "eks-argocd-capability" })
}

# ===== ESO Pod Identity Role =====
resource "aws_iam_role" "eso" {
  name = "${var.cluster_name}-ESOPodIdentityRole"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags = merge(local.common_tags, { purpose = "eso-pod-identity" })
}

resource "aws_iam_policy" "eso" {
  name = "${var.cluster_name}-ESOSecretsManagerPolicy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:ListSecrets",
        "secretsmanager:CreateSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:TagResource",
      ]
      Resource = "*"
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "eso" {
  role       = aws_iam_role.eso.name
  policy_arn = aws_iam_policy.eso.arn
}

resource "aws_eks_pod_identity_association" "eso" {
  cluster_name    = aws_eks_cluster.hub.name
  namespace       = "external-secrets"
  service_account = "external-secrets-sa"
  role_arn        = aws_iam_role.eso.arn
  tags            = local.common_tags
}

# ===== Crossplane Provider Roles + Pod Identity =====
# These must exist before ArgoCD installs crossplane-base (createIdentity: false in registry)

locals {
  crossplane_providers = {
    iam = {
      role_name       = "${var.cluster_name}-CrossplaneIAMProviderRole"
      service_account = "provider-aws-iam"
    }
    eks = {
      role_name       = "${var.cluster_name}-CrossplaneEKSProviderRole"
      service_account = "provider-aws-eks"
    }
    ec2 = {
      role_name       = "${var.cluster_name}-CrossplaneEC2ProviderRole"
      service_account = "provider-aws-ec2"
    }
    secretsmanager = {
      role_name       = "${var.cluster_name}-CrossplaneSecretsManagerProviderRole"
      service_account = "provider-aws-secretsmanager"
    }
  }
}

resource "aws_iam_role" "crossplane_provider" {
  for_each = local.crossplane_providers
  name     = each.value.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
  tags = merge(local.common_tags, { purpose = "${each.key}-provider" })
}

resource "aws_iam_role_policy_attachment" "crossplane_provider" {
  for_each   = local.crossplane_providers
  role       = aws_iam_role.crossplane_provider[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

resource "aws_eks_pod_identity_association" "crossplane_provider" {
  for_each        = local.crossplane_providers
  cluster_name    = aws_eks_cluster.hub.name
  namespace       = "crossplane-system"
  service_account = each.value.service_account
  role_arn        = aws_iam_role.crossplane_provider[each.key].arn
  tags            = local.common_tags
}
