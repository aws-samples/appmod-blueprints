vpc_cidr           = "10.3.0.0/16"
kubernetes_version = "1.31"
ingress_name       = "peeks-spoke-dev-ingress"

addons = {
  enable_ack_s3             = true
  enable_ack_dynamodb       = true
  enable_crossplane         = true
  enable_platform_manifests = true
}