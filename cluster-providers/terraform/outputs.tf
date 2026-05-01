output "cluster_name" {
  value = aws_eks_cluster.hub.name
}

output "cluster_arn" {
  value = aws_eks_cluster.hub.arn
}

output "cluster_endpoint" {
  value = aws_eks_cluster.hub.endpoint
}

output "vpc_id" {
  value = aws_vpc.hub.id
}

output "argocd_capability_role_arn" {
  value = aws_iam_role.argocd_capability.arn
}

output "eso_role_arn" {
  value = aws_iam_role.eso.arn
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --name ${aws_eks_cluster.hub.name} --region ${var.aws_region}"
}
