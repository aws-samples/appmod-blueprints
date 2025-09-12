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

resource "aws_iam_role_policy" "argocd_central_policy" {
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
# Creating parameter for all clusters to read
resource "aws_ssm_parameter" "argocd_hub_role" {
  name  = "${local.context_prefix}-${var.ssm_parameter_name_argocd_role_suffix}"
  type  = "String"
  value = aws_iam_role.argocd_central.arn
}
################################################################################
# Team Roles Backend
################################################################################
resource "aws_iam_role" "backend_team_view" {
  name_prefix = "backend-team-view-"
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
# Creating parameter for all clusters to read
resource "aws_ssm_parameter" "backend_team_view_role" {
  name  = "${local.context_prefix}-${var.backend_team_view_role_suffix}"
  type  = "String"
  value = aws_iam_role.backend_team_view.arn
}
################################################################################
# Team Roles Frontend
################################################################################
resource "aws_iam_role" "frontend_team_view" {
  name_prefix = "frontend-team-view-"
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
# Creating parameter for all clusters to read
resource "aws_ssm_parameter" "frontend_team_view_role" {
  name  = "${local.context_prefix}-${var.frontend_team_view_role_suffix}"
  type  = "String"
  value = aws_iam_role.frontend_team_view.arn
}