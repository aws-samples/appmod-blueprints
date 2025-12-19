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
