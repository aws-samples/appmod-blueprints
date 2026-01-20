# Mountpoint for Amazon S3 CSI Driver
# Enables mounting S3 buckets as volumes in Kubernetes pods

# IAM role for S3 CSI driver
resource "aws_iam_role" "s3_csi_driver" {
  for_each = var.clusters

  name = "${var.resource_prefix}-s3-csi-driver-role-${each.key}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
        Action = [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })

  tags = {
    Name        = "${var.resource_prefix}-s3-csi-driver-role-${each.key}"
    Environment = each.value.environment
    ManagedBy   = "Terraform"
  }
}

# Attach S3 read-only policy
resource "aws_iam_role_policy_attachment" "s3_csi_driver_s3" {
  for_each = var.clusters

  role       = aws_iam_role.s3_csi_driver[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}

# Pod Identity association for S3 CSI driver
resource "aws_eks_pod_identity_association" "s3_csi_driver" {
  for_each = var.clusters

  cluster_name    = each.value.name
  namespace       = "kube-system"
  service_account = "s3-csi-driver-sa"
  role_arn        = aws_iam_role.s3_csi_driver[each.key].arn

  tags = {
    Name        = "${var.resource_prefix}-s3-csi-driver-pod-identity-${each.key}"
    Environment = each.value.environment
    ManagedBy   = "Terraform"
  }
}

resource "aws_eks_addon" "s3_csi_driver" {
  for_each = var.clusters

  cluster_name             = each.value.name
  addon_name               = "aws-mountpoint-s3-csi-driver"
  addon_version            = "v2.3.0-eksbuild.1"
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  tags = {
    Name        = "${var.resource_prefix}-s3-csi-driver-${each.key}"
    Environment = each.value.environment
    ManagedBy   = "Terraform"
  }
}
