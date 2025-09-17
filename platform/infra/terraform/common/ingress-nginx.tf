################################################################################
# Ingress Nginx Controller
################################################################################

# Create namespace for ingress-nginx
resource "kubernetes_namespace" "ingress_nginx" {
  # depends_on = [local.cluster_info]

  metadata {
    name = "ingress-nginx"
  }
}

################################################################################
# Security Groups for Ingress Nginx
################################################################################

# Get CloudFront prefix list dynamically
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# Security group for HTTP access (port 80) from CloudFront
resource "aws_security_group" "ingress_http" {
  for_each = var.clusters
  name        = "${each.value.name}-ingress-http"
  description = "HTTP from anywhere"
  vpc_id      = local.cluster_vpc_ids[each.value.name]

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description     = "HTTP from anywhere"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, {
    Name = "${each.value.name}-ingress-http"
  })
}

# Security group for HTTPS access (port 443) from CloudFront
resource "aws_security_group" "ingress_https" {
  for_each = var.clusters
  name        = "${each.value.name}-ingress-https"
  # description = "HTTPS only from CloudFront"
  description = "HTTPS from anywhere"
  vpc_id      = local.cluster_vpc_ids[each.value.name]

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    # prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
    # description     = "HTTPS only from CloudFront"
    cidr_blocks = ["0.0.0.0/0"]
    description     = "HTTPS from anywhere"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, {
    Name = "${each.value.name}-ingress-https"
  })
}

locals {
  # Create the values content using templatefile
  ingress_nginx_values = templatefile("${path.module}/manifests/ingress-nginx-initial-values.yaml", {
    SECURITY_GROUPS = local.ingress_security_groups[local.hub_cluster.name]
    INGRESS_NAME    = local.ingress_name[local.hub_cluster.name]
  })
}

################################################################################
# Deploy ingress-nginx using Helm in the hub cluster
################################################################################

resource "helm_release" "ingress_nginx" {
  depends_on = [
    kubernetes_namespace.ingress_nginx,
    aws_security_group.ingress_http,
    aws_security_group.ingress_https
  ]

  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  version    = "4.12.2"
  namespace  = kubernetes_namespace.ingress_nginx.metadata[0].name
  timeout    = 600
  values     = [local.ingress_nginx_values]
}

# Get the NLB DNS name for the ingress-nginx service
data "aws_lb" "ingress_nginx" {
  depends_on = [helm_release.ingress_nginx]
  name       = local.ingress_name[local.hub_cluster.name]
}
