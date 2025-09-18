vpc_cidr           = "10.3.0.0/16"
kubernetes_version = "1.31"
ingress_name       = "peeks-spoke-dev-ingress"

# Enable basic addons for testing auto mode functionality
addons = {
  enable_aws_load_balancer_controller = true
  enable_metrics_server               = true
  enable_external_secrets             = true
  enable_aws_cloudwatch_metrics       = true
  enable_ack_s3                       = true
}