# IAM role for Karpenter-managed nodes (when EKS Auto Mode compute_config is disabled)
resource "aws_iam_role" "karpenter_node" {
  for_each = var.clusters
  
  name = "${each.value.name}-karpenter-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "${each.value.name}-karpenter-node-role"
  }
}

# Attach required policies for EKS nodes
resource "aws_iam_role_policy_attachment" "karpenter_node_policies" {
  for_each = {
    for pair in flatten([
      for cluster_key, cluster in var.clusters : [
        for policy in [
          "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
          "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
          "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
          "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
        ] : {
          key    = "${cluster_key}-${split("/", policy)[1]}"
          cluster_key = cluster_key
          policy = policy
        }
      ]
    ]) : pair.key => pair
  }

  role       = aws_iam_role.karpenter_node[each.value.cluster_key].name
  policy_arn = each.value.policy
}

# Create instance profile with eks- prefix (required by EKS Auto Mode)
resource "aws_iam_instance_profile" "karpenter_node" {
  for_each = var.clusters
  
  name = "eks-${each.value.name}-karpenter-node"
  role = aws_iam_role.karpenter_node[each.key].name

  tags = {
    Name = "eks-${each.value.name}-karpenter-node-profile"
  }
}

# Create EKS access entry for Karpenter nodes
resource "aws_eks_access_entry" "karpenter_node" {
  for_each = var.clusters
  
  cluster_name  = module.eks[each.key].cluster_name
  principal_arn = aws_iam_role.karpenter_node[each.key].arn
  type          = "EC2"

  depends_on = [module.eks]
}

# Associate AmazonEKSAutoNodePolicy to the access entry
resource "aws_eks_access_policy_association" "karpenter_node" {
  for_each = var.clusters
  
  cluster_name  = module.eks[each.key].cluster_name
  principal_arn = aws_iam_role.karpenter_node[each.key].arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAutoNodePolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.karpenter_node]
}

# Output the role names for NodeClass configuration
output "karpenter_node_role_names" {
  value = { for k, v in aws_iam_role.karpenter_node : k => v.name }
}

# Output the instance profile names
output "karpenter_node_instance_profiles" {
  value = { for k, v in aws_iam_instance_profile.karpenter_node : k => v.name }
}
