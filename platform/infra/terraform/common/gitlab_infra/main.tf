################################################################################
# GitLab Network Load Balancer
################################################################################

# Security group for HTTP access (port 80) for GitLab
resource "aws_security_group" "gitlab_http" {
  name        = "${local.hub_cluster.name}-gitlab-http"
  description = "HTTP for GitLab"
  vpc_id      = local.cluster_vpc_ids[local.hub_cluster.name]

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP for GitLab"
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = {
    Name = "${local.hub_cluster.name}-gitlab-http"
  }
}

# Get subnets from the EKS cluster, excluding ap-northeast-2a
data "aws_subnets" "cluster_subnets" {
  filter {
    name   = "vpc-id"
    values = [local.cluster_vpc_ids[local.hub_cluster.name]]
  }
  
  tags = {
    "kubernetes.io/role/elb" = "1"
  }
}

data "aws_subnet" "cluster_subnet_details" {
  for_each = toset(data.aws_subnets.cluster_subnets.ids)
  id       = each.value
}

locals {
  # Filter out ap-northeast-2a subnets
  allowed_subnet_ids = [
    for id, subnet in data.aws_subnet.cluster_subnet_details : id
    if subnet.availability_zone != "ap-northeast-2a"
  ]
  allowed_subnets_string = join(",", local.allowed_subnet_ids)
}

# Create a Kubernetes namespace for GitLab
resource "kubernetes_namespace" "gitlab" {
  # depends_on = [local.cluster_info]

  metadata {
    name = "gitlab"
    labels = {
      "app.kubernetes.io/managed-by" = "Helm"
    }
    annotations = {
      "meta.helm.sh/release-name" = "gitlab"
      "meta.helm.sh/release-namespace" = "gitlab"
    }
  }
}

# Create a Kubernetes service for GitLab with LoadBalancer type
resource "kubernetes_service" "gitlab_nlb" {
  depends_on = [kubernetes_namespace.gitlab]

  timeouts {
    create = "15m"
  }

  metadata {
    name      = "gitlab"
    namespace = "gitlab"
    annotations = {
      "service.beta.kubernetes.io/aws-load-balancer-name" = "gitlab"
      "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
      "service.beta.kubernetes.io/aws-load-balancer-security-groups" = local.gitlab_security_groups
      "service.beta.kubernetes.io/aws-load-balancer-manage-backend-security-group-rules" = "true"
      "service.beta.kubernetes.io/aws-load-balancer-subnets" = local.gitlab_subnets
      "meta.helm.sh/release-name" = "gitlab"
      "meta.helm.sh/release-namespace" = "gitlab"
    }
    labels = {
      "app.kubernetes.io/managed-by" = "Helm"
    }
  }

  spec {
    selector = {
      app = "gitlab"
    }

    port {
      name        = "http"
      port        = 80
      target_port = 80
      protocol    = "TCP"
    }

    port {
      name        = "ssh"
      port        = 22
      target_port = 22
      protocol    = "TCP"
    }

    type             = "LoadBalancer"
    load_balancer_class = "eks.amazonaws.com/nlb"
  }
}

# Get the NLB DNS name for the GitLab service
data "aws_lb" "gitlab_nlb" {
  depends_on = [kubernetes_service.gitlab_nlb]

  # Use the name directly as specified in the kubernetes_service annotations
  name = "gitlab"
}

################################################################################
# CloudFront Distribution for GitLab NLB
################################################################################
resource "aws_cloudfront_vpc_origin" "gitlab" {
  vpc_origin_endpoint_config {
    name                   = "${var.resource_prefix}-gitlab-vpc-origin"
    arn                    = data.aws_lb.gitlab_nlb.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

resource "aws_cloudfront_distribution" "gitlab" {
  depends_on = [data.aws_lb.gitlab_nlb]
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "CloudFront distribution for GitLab"
  price_class         = "PriceClass_All"
  http_version        = "http2"
  wait_for_deployment = false

  origin {
    domain_name = data.aws_lb.gitlab_nlb.dns_name
    origin_id   = aws_cloudfront_vpc_origin.gitlab.id

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.gitlab.id
      origin_read_timeout    = 60
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = "X-Forwarded-Proto"
      value = "https"
    }

    custom_header {
      name  = "X-Forwarded-Port"
      value = "443"
    }
  }

  default_cache_behavior {
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = aws_cloudfront_vpc_origin.gitlab.id

    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    # Using policy names instead of hardcoded IDs
    cache_policy_id          = data.aws_cloudfront_cache_policy.use_origin_cache_control_headers_query_strings.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  tags = {
    Name        = "gitlab-cloudfront"
    # Environment = local.environment
  }
}

################################################################################
# GitLab Helm Chart
################################################################################

locals {
  # Create the values content using templatefile
  gitlab_values = templatefile("${path.module}/gitlab-initial-values.yaml", {
    DOMAIN_NAME = local.gitlab_domain_name
    INITIAL_ROOT_PASSWORD = var.git_password
    SECURITY_GROUPS_GITLAB = local.gitlab_security_groups
    GIT_USERNAME = var.git_username
    WORKING_REPO = var.working_repo
  })
}

resource "helm_release" "gitlab" {
  depends_on = [
    aws_cloudfront_distribution.gitlab
  ]

  name       = "gitlab"
  chart      = "${path.module}/../../../../../gitops/addons/charts/gitlab"
  timeout    = 600
  values     = [local.gitlab_values]
  create_namespace = false
  namespace  = kubernetes_namespace.gitlab.metadata[0].name
}
