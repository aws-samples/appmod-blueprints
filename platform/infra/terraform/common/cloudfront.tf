################################################################################
# CloudFront Distribution for Ingress NLB
################################################################################

# Custom origin request policy for Keycloak to forward all required headers
resource "aws_cloudfront_origin_request_policy" "keycloak_policy" {
  name    = "KeycloakOriginRequestPolicy"
  comment = "Origin request policy for Keycloak with all required headers"
  
  cookies_config {
    cookie_behavior = "all"
  }
  
  headers_config {
    header_behavior = "allViewer"
  }
  
  query_strings_config {
    query_string_behavior = "all"
  }
}

# Reference the managed policies by name instead of ID
data "aws_cloudfront_cache_policy" "use_origin_cache_control_headers_query_strings" {
  name = "UseOriginCacheControlHeaders-QueryStrings"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

resource "aws_cloudfront_distribution" "ingress" {
  depends_on = [helm_release.ingress_nginx]

  enabled             = true
  is_ipv6_enabled     = true
  comment             = "CloudFront distribution for ${local.ingress_name[local.hub_cluster.name]} NLB"
  price_class         = "PriceClass_All"
  http_version        = "http2"
  wait_for_deployment = false

  origin {
    domain_name = local.ingress_nlb_domain_name
    origin_id   = "http-origin"

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
    target_origin_id = "http-origin"

    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    # Using policy names instead of hardcoded IDs
    cache_policy_id          = data.aws_cloudfront_cache_policy.use_origin_cache_control_headers_query_strings.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
  }

  # Specific cache behavior for Keycloak resources to fix iframe and static resource issues
  ordered_cache_behavior {
    path_pattern     = "/keycloak/*"
    allowed_methods  = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "http-origin"

    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    # Use no-cache policy for Keycloak to avoid caching issues with dynamic content
    cache_policy_id          = data.aws_cloudfront_cache_policy.use_origin_cache_control_headers_query_strings.id
    origin_request_policy_id = aws_cloudfront_origin_request_policy.keycloak_policy.id

    # Ensure all headers and query strings are forwarded for Keycloak
    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
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
    Name        = "${local.ingress_name[local.hub_cluster.name]}-cloudfront"
    # Environment = local.environment
  }
}
