################################################################################
# GitLab Network Load Balancer
################################################################################

# Security group for GitLab NLB
resource "aws_security_group" "gitlab_ssh" {
  name        = "${local.name}-gitlab-ssh"
  description = "SSH for GitLab"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "SSH for GitLab"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = {
    Name = "${local.name}-gitlab-ssh"
  }
}

# Security group for HTTP access (port 80) for GitLab
resource "aws_security_group" "gitlab_http" {
  name        = "${local.name}-gitlab-http"
  description = "HTTP for GitLab"
  vpc_id      = module.vpc.vpc_id

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
    Name = "${local.name}-gitlab-http"
  }
}

# Create a Kubernetes namespace for GitLab
resource "kubernetes_namespace" "gitlab" {
  depends_on = [local.cluster_info]

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

  metadata {
    name      = "gitlab"
    namespace = "gitlab"
    annotations = {
      "service.beta.kubernetes.io/aws-load-balancer-name" = "gitlab"
      "service.beta.kubernetes.io/aws-load-balancer-type" = "external"
      "service.beta.kubernetes.io/aws-load-balancer-scheme" = "internet-facing"
      "service.beta.kubernetes.io/aws-load-balancer-nlb-target-type" = "ip"
      "service.beta.kubernetes.io/aws-load-balancer-security-groups" = local.gitlab_security_groups
      "service.beta.kubernetes.io/aws-load-balancer-manage-backend-security-group-rules" = "true"
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
    origin_id   = "gitlab-origin"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60
      origin_keepalive_timeout = 30
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
    target_origin_id = "gitlab-origin"

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
    Environment = local.environment
  }
}

################################################################################
# GitLab Helm Chart
################################################################################

locals {
  # Create the values content using templatefile
  gitlab_values = templatefile("${path.module}/gitlab-initial-values.yaml", {
    DOMAIN_NAME = local.gitlab_domain_name
    INITIAL_ROOT_PASSWORD = var.ide_password
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
  chart      = "${path.module}/../../../../gitops/addons/charts/gitlab"
  timeout    = 600
  values     = [local.gitlab_values]
  create_namespace = false
  namespace  = kubernetes_namespace.gitlab.metadata[0].name
}
