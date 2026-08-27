# EKS ArgoCD Capability — native Terraform resource (aws provider >= 6.25)

resource "aws_eks_capability" "argocd" {
  cluster_name              = aws_eks_cluster.hub.name
  capability_name           = var.argocd_capability_name
  type                      = "ARGOCD"
  role_arn                  = aws_iam_role.argocd_capability.arn
  delete_propagation_policy = "RETAIN"

  configuration {
    argo_cd {
      aws_idc {
        idc_instance_arn = var.idc_instance_arn
        idc_region       = var.idc_region
      }
      rbac_role_mapping {
        role = "ADMIN"
        identity {
          id   = var.idc_admin_group_id
          type = "SSO_GROUP"
        }
      }
    }
  }

  tags = local.common_tags

  depends_on = [aws_eks_access_entry.argocd]
}
