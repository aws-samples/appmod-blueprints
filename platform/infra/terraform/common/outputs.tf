# Output the ArgoCD URL and login credentials
output "argocd_access" {
  description = "ArgoCD access information"
  value       = "ArgoCD URL: https://${local.ingress_domain_name}/argocd\nLogin: admin\nPassword: ${var.ide_password}"
  sensitive   = true
}

output "gitlab_access" {
  description = "Gitlab access information"
  value       = "Gitlab URL: https://${local.gitlab_domain_name}/\nLogin: ${var.git_username}\nPassword: ${var.ide_password}"
  sensitive   = true
}

output "ingress_domain_name" {
  description = "The CloudFront domain name for ingress"
  value       = local.ingress_domain_name
}

output "amp_workspace_endpoint" {
  description = "Amazon Managed Prometheus workspace endpoint"
  value       = module.managed_service_prometheus.workspace_prometheus_endpoint
}

output "amp_workspace_id" {
  description = "Amazon Managed Prometheus workspace ID"
  value       = module.managed_service_prometheus.workspace_id
}

output "amg_workspace_endpoint" {
  description = "Amazon Managed Grafana workspace endpoint"
  value       = module.managed_grafana.workspace_endpoint
}
