output "prod_cluster_name" {
  description = "EKS Prod Cluster name"
  value       = module.eks_prod_cluster_with_vpc.eks_cluster_id
}

output "configure_kubectl" {
  description = "Configure kubectl: make sure you're logged in with the correct AWS profile and run the following command to update your kubeconfig"
  value       = module.eks_prod_cluster_with_vpc.configure_kubectl
}

# output "argocd_prod_load_balancer_url" {
#   value = data.kubernetes_service.argocd_prod_server.status[0].load_balancer[0].ingress[0].hostname
# }

# output "argocd_prod_initial_admin_secret" {
#   value = "kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath=\"{.data.password}\" | base64 -d"
# }