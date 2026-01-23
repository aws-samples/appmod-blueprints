provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.clusters[local.hub_cluster_key].endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters[local.hub_cluster_key].certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      # This requires the awscli to be installed locally where Terraform is executed
      args = [
        "eks",
        "get-token",
        "--cluster-name", data.aws_eks_cluster.clusters[local.hub_cluster_key].name,
        "--region", local.hub_cluster.region
      ]
    }
  }
}

provider "kubernetes" {
    host                   = data.aws_eks_cluster.clusters[local.hub_cluster_key].endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters[local.hub_cluster_key].certificate_authority[0].data)
  # insecure = true
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.clusters[local.hub_cluster_key].name,
      "--region", local.hub_cluster.region
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

provider "gitlab" {
  base_url = "https://${var.gitlab_domain_name}/api/v4"
  token = "root-${var.ide_password}"
  early_auth_check = false # Required to avoid failures before gitlab is setup
}

# These providers are required for spoke clusters as the providers can not be dynamic
# Required for terraform-aws-observability-accelerator
# TODO: Find a way to deploy terraform-aws-observability-accelerator outside of tf
provider "helm" {
  alias = "spoke1" # For Spoke 1 cluster
  kubernetes {
    host                   = data.aws_eks_cluster.clusters["spoke1"].endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters["spoke1"].certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      # This requires the awscli to be installed locally where Terraform is executed
      args = [
        "eks",
        "get-token",
        "--cluster-name", data.aws_eks_cluster.clusters["spoke1"].name,
        "--region", local.spoke_clusters["spoke1"].region
      ]
    }
  }
}
provider "helm" {
  alias = "spoke2" # For Spoke 2 cluster
  kubernetes {
    host                   = data.aws_eks_cluster.clusters["spoke2"].endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters["spoke2"].certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      # This requires the awscli to be installed locally where Terraform is executed
      args = [
        "eks",
        "get-token",
        "--cluster-name", data.aws_eks_cluster.clusters["spoke2"].name,
        "--region", local.spoke_clusters["spoke2"].region
      ]
    }
  }
}
provider "kubectl" {
  alias                  = "spoke1" # For Spoke 1 cluster
  host                   = data.aws_eks_cluster.clusters["spoke1"].endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters["spoke1"].certificate_authority[0].data)
  load_config_file       = false

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.clusters["spoke1"].name,
      "--region", local.spoke_clusters["spoke1"].region
    ]
  }
}

provider "kubectl" {
  alias                  = "spoke2" # For Spoke 2 cluster
  host                   = data.aws_eks_cluster.clusters["spoke2"].endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters["spoke2"].certificate_authority[0].data)
  load_config_file       = false

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.clusters["spoke2"].name,
      "--region", local.spoke_clusters["spoke2"].region
    ]
  }
}

provider "kubernetes" {
  alias                  = "spoke1" # For Spoke 1 cluster
  host                   = data.aws_eks_cluster.clusters["spoke1"].endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters["spoke1"].certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.clusters["spoke1"].name,
      "--region", local.spoke_clusters["spoke1"].region
    ]
  }
}

provider "kubernetes" {
  alias                  = "spoke2" # For Spoke 2 cluster
  host                   = data.aws_eks_cluster.clusters["spoke2"].endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.clusters["spoke2"].certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = [
      "eks",
      "get-token",
      "--cluster-name", data.aws_eks_cluster.clusters["spoke2"].name,
      "--region", local.spoke_clusters["spoke2"].region
    ]
  }
}