output "service_account_metadata" {
  description = "Metadata for created service account."
  value       = kubernetes_service_account.service_account.metadata
}
