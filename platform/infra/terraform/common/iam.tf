################################################################################
# ArgoCD EKS Access
################################################################################
resource "aws_iam_role" "argocd_central" {
  name_prefix = "${local.context_prefix}-argocd-hub"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowEksAuthToAssumeRoleForPodIdentity"
        Effect = "Allow"
        Action = ["sts:AssumeRole", "sts:TagSession"]
        Principal = {
          Service = "pods.eks.amazonaws.com"
        }
      },
    ]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "argocd_central" {
  name = "argocd"
  role = aws_iam_role.argocd_central.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["sts:AssumeRole", "sts:TagSession"]
        Effect   = "Allow"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role" "spoke" {
  for_each           = local.spoke_clusters
  name_prefix        = "${each.value.name}-argocd-spoke"
  assume_role_policy = data.aws_iam_policy_document.assume_role_policy[each.key].json
}

data "aws_iam_policy_document" "assume_role_policy" {
  for_each = local.spoke_clusters
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.argocd_central.arn]
    }
  }
}

resource "aws_eks_access_entry" "spoke" {
  for_each      = local.spoke_clusters
  cluster_name  = each.value.name
  principal_arn = aws_iam_role.spoke[each.key].arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "spoke" {
  for_each = local.spoke_clusters
  depends_on = [
    aws_eks_access_entry.spoke[each.key]
  ]
  cluster_name  = each.value.name
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  principal_arn = aws_iam_role.spoke[each.key].arn

  access_scope {
    type = "cluster"
  }
}


# ################################################################################
# # Team Roles Backend
# ################################################################################
resource "aws_iam_role" "backend_team" {
  for_each    = local.spoke_clusters
  name_prefix = "${each.value.name}-backend-team-view-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    "Statement" : [
      {
        "Effect" : "Allow",
        "Principal" : {
          "AWS" : data.aws_iam_session_context.current.issuer_arn
        },
        "Action" : "sts:AssumeRole"
      }
    ]
  })
  tags = local.tags
}

resource "aws_eks_access_entry" "backend_team" {
  for_each          = local.spoke_clusters
  cluster_name      = each.value.name
  principal_arn     = aws_iam_role.backend_team[each.key].arn
  kubernetes_groups = ["backend-team-view"]
  type              = "STANDARD"
}

################################################################################
# Team Roles Frontend
################################################################################
resource "aws_iam_role" "frontend_team" {
  for_each    = local.spoke_clusters
  name_prefix = "${each.value.name}-frontend-team-view-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    "Statement" : [
      {
        "Effect" : "Allow",
        "Principal" : {
          "AWS" : data.aws_iam_session_context.current.issuer_arn
        },
        "Action" : "sts:AssumeRole"
      }
    ]
  })
  tags = local.tags
}

resource "aws_eks_access_entry" "frontend_team" {
  for_each          = local.spoke_clusters
  cluster_name      = each.value.name
  principal_arn     = aws_iam_role.frontend_team[each.key].arn
  kubernetes_groups = ["frontend-team-view"]
  type              = "STANDARD"
}
