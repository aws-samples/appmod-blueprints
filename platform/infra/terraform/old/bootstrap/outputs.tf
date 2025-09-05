output "eks-accelerator-bootstrap-state-bucket" {
  description = "EKS accelerator state bucket"
  value       = aws_s3_bucket.terraform-states-s3-bucket.id
}

output "eks-accelerator-bootstrap-ddb-lock-table" {
  description = "EKS accelerator DynamoDB lock table"
  value       = aws_dynamodb_table.terraform-lock.name
}

output "amp_workspace_id" {
  description = "Amazon Managed prometheus Workspace ID"
  value       = module.managed_service_prometheus.workspace_id
}

output "amg_workspace_id" {
  description = "Amazon Managed Grafana Workspace ID"
  value       = module.managed_grafana.workspace_id
}

output "grafana_workspace_endpoint" {
  description = "Amazon Managed Grafana Workspace endpoint"
  value       = module.managed_grafana.workspace_endpoint
}

output "grafana_workspace_iam_role_arn" {
  description = "Amazon Managed Grafana Workspace's IAM Role ARN"
  value       = module.managed_grafana.workspace_iam_role_arn
}
