output "instance_arn" {
  description = "ARN of the Identity Center instance"
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "ID of the Identity Store"
  value       = local.identity_store_id
}

output "admin_group_id" {
  description = "ID of the admin group"
  value       = local.identity_store_id != null ? aws_identitystore_group.admin[0].group_id : null
}

output "developer_group_id" {
  description = "ID of the developer group"
  value       = local.identity_store_id != null ? aws_identitystore_group.developer[0].group_id : null
}

output "test_user_id" {
  description = "ID of the test user (if created)"
  value       = var.create_test_user && local.identity_store_id != null ? aws_identitystore_user.test_user[0].user_id : null
}
