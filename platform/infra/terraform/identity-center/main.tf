# Data source to get existing IDC instance
data "aws_ssoadmin_instances" "existing" {}

# Create IDC instance if none exists
resource "aws_ssoadmin_instance" "main" {
  count = length(data.aws_ssoadmin_instances.existing.arns) == 0 ? 1 : 0
  name  = "PEEKS-WORKSHOP"
}

# Use existing instance or newly created one
locals {
  instance_arn      = length(data.aws_ssoadmin_instances.existing.arns) > 0 ? data.aws_ssoadmin_instances.existing.arns[0] : aws_ssoadmin_instance.main[0].arn
  identity_store_id = length(data.aws_ssoadmin_instances.existing.identity_store_ids) > 0 ? data.aws_ssoadmin_instances.existing.identity_store_ids[0] : aws_ssoadmin_instance.main[0].identity_store_id
}

# Create admin group
resource "aws_identitystore_group" "admin" {
  count             = local.identity_store_id != null ? 1 : 0
  identity_store_id = local.identity_store_id
  display_name      = "eks-argocd-admins"
  description       = "Admin group for EKS Managed Capability for ArgoCD"
}

# Create developer group
resource "aws_identitystore_group" "developer" {
  count             = local.identity_store_id != null ? 1 : 0
  identity_store_id = local.identity_store_id
  display_name      = "eks-argocd-developers"
  description       = "Developers group for EKS Managed Capability for ArgoCD"
}

# Optional: Create test user
resource "aws_identitystore_user" "test_user" {
  count             = var.create_test_user && local.identity_store_id != null ? 1 : 0
  identity_store_id = local.identity_store_id
  user_name         = "eks-argocd-admin-user"
  display_name      = "EKS Argo CD Admin User"

  name {
    given_name  = "EKS Admin"
    family_name = "Admin User"
  }

  emails {
    value   = "eks-argocd-admin@example.com"
    primary = true
  }
}

# Add test user to admin group
resource "aws_identitystore_group_membership" "test_user_admin" {
  count             = var.create_test_user && local.identity_store_id != null ? 1 : 0
  identity_store_id = local.identity_store_id
  group_id          = aws_identitystore_group.admin[0].group_id
  member_id         = aws_identitystore_user.test_user[0].user_id
}
