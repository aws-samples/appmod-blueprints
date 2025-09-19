vpc_cidr           = "10.3.0.0/16"
kubernetes_version = "1.31"
ingress_name       = "peeks-spoke-prod-ingress"

addons = {
  enable_ack_s3 = true
}

