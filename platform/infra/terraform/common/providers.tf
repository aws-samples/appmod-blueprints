provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.mgmt.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.mgmt.certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      # This requires the awscli to be installed locally where Terraform is executed
      args = [
        "eks",
        "get-token",
        "--cluster-name", data.aws_eks_cluster.mgmt.name,
        "--region", local.region
      ]
    }
  }
}

provider "kubernetes" {
    host                   = data.aws_eks_cluster.mgmt.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.mgmt.certificate_authority[0].data)
  # insecure = true
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.mgmt.name,
      "--region", local.region
    ]
  }
}

provider "aws" {
  # Rate limiting and retry configuration to handle API throttling
  retry_mode = "adaptive"
  max_retries = 10
  
  # Increase default timeouts for operations
  default_tags {
    tags = {
      ManagedBy = "Terraform"
    }
  }
}
