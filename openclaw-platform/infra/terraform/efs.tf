# efs.tf — EFS filesystem for persistent per-user workspaces
# Sandbox pods mount /workspace from here via subPath=<user-suffix>.
# Survives Sandbox deletion by the reaper — user context persists across sessions.

resource "aws_security_group" "efs" {
  name        = "${local.cluster_name}-efs"
  description = "NFS from EKS nodes to EFS workspaces"
  vpc_id      = module.vpc.vpc_id
  tags        = local.tags
}

resource "aws_security_group_rule" "efs_ingress_nfs" {
  type                     = "ingress"
  from_port                = 2049
  to_port                  = 2049
  protocol                 = "tcp"
  security_group_id        = aws_security_group.efs.id
  source_security_group_id = module.eks.node_security_group_id
  description              = "NFS from EKS nodes"
}

resource "aws_efs_file_system" "workspaces" {
  creation_token = "${local.cluster_name}-workspaces"
  encrypted      = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  tags = merge(local.tags, { Name = "${local.cluster_name}-workspaces" })
}

resource "aws_efs_mount_target" "workspaces" {
  count = length(module.vpc.private_subnets)

  file_system_id  = aws_efs_file_system.workspaces.id
  subnet_id       = module.vpc.private_subnets[count.index]
  security_groups = [aws_security_group.efs.id]
}

# ---- IAM for EFS CSI driver (IRSA) ----
resource "aws_iam_role" "efs_csi" {
  name = "${local.cluster_name}-efs-csi"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:kube-system:efs-csi-controller-sa"
          "${module.eks.oidc_provider}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "efs_csi" {
  role       = aws_iam_role.efs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy"
}

# StorageClass for dynamic access points (one AP per PVC, user data isolated by GID)
resource "kubectl_manifest" "efs_storageclass" {
  yaml_body = <<-YAML
    apiVersion: storage.k8s.io/v1
    kind: StorageClass
    metadata:
      name: efs-workspaces
    provisioner: efs.csi.aws.com
    parameters:
      provisioningMode: efs-ap
      fileSystemId: ${aws_efs_file_system.workspaces.id}
      directoryPerms: "700"
      uid: "1000"
      gid: "1000"
    reclaimPolicy: Retain
  YAML

  depends_on = [module.eks]
}

output "efs_workspaces_id" {
  value = aws_efs_file_system.workspaces.id
}
