packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "ap-southeast-1"
}

variable "cluster_name" {
  type    = string
  default = "kata-eks"
}

variable "kubernetes_version" {
  type        = string
  default     = "1.35"
  description = "Kubernetes version for EKS-optimized AMI lookup"
}

variable "kata_version" {
  type    = string
  default = "3.26.0"
}

variable "use_nested_virtualization" {
  type        = bool
  default     = true
  description = "Build AMI on nested virtualization instance (c8i) vs bare metal (c5.metal)"
}

variable "nested_build_instance_type" {
  type        = string
  default     = "c8i.4xlarge"
  description = "Instance type for nested virtualization AMI builds"
}

variable "baremetal_build_instance_type" {
  type        = string
  default     = "c5.metal"
  description = "Instance type for bare metal AMI builds"
}

variable "vpc_id" {
  type        = string
  default     = ""
  description = "VPC ID for the build instance. If empty, Packer uses the default VPC."
}

variable "subnet_id" {
  type        = string
  default     = ""
  description = "Subnet ID for the build instance. If empty, Packer picks a public subnet."
}

variable "security_group_id" {
  type        = string
  default     = ""
  description = "Security group ID for the build instance. If empty, Packer creates a temporary one."
}

# =============================================================================
# Nested Virtualization Build (c8i/m8i instances)
# Cost-effective: ~$0.25/hr vs ~$1.11/hr for bare metal
# =============================================================================
source "amazon-ebs" "kata_nested" {
  ami_name      = "${var.cluster_name}-kata-al2023-nested-{{timestamp}}"
  instance_type = var.nested_build_instance_type
  region        = var.aws_region

  source_ami_filter {
    filters = {
      name                = "amazon-eks-node-al2023-x86_64-standard-${var.kubernetes_version}-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["602401143452"] # Amazon EKS AMI account
  }

  vpc_id                      = var.vpc_id != "" ? var.vpc_id : null
  subnet_id                   = var.subnet_id != "" ? var.subnet_id : null
  security_group_id           = var.security_group_id != "" ? var.security_group_id : null
  associate_public_ip_address = true

  ssh_username = "ec2-user"

  # Standard instance polling (faster than bare metal)
  aws_polling {
    delay_seconds = 15
    max_attempts  = 40
  }

  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 250
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name               = "${var.cluster_name}-kata-al2023-nested"
    KataVersion        = var.kata_version
    KubernetesVersion  = var.kubernetes_version
    BuildInstanceType  = var.nested_build_instance_type
    VirtualizationMode = "nested"
  }
}

# =============================================================================
# Bare Metal Build (c5.metal, i3.metal, etc.)
# For performance-critical workloads requiring direct VT-x access
# =============================================================================
source "amazon-ebs" "kata_baremetal" {
  ami_name      = "${var.cluster_name}-kata-al2023-baremetal-{{timestamp}}"
  instance_type = var.baremetal_build_instance_type
  region        = var.aws_region

  source_ami_filter {
    filters = {
      name                = "amazon-eks-node-al2023-x86_64-standard-${var.kubernetes_version}-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["602401143452"] # Amazon EKS AMI account
  }

  vpc_id                      = var.vpc_id != "" ? var.vpc_id : null
  subnet_id                   = var.subnet_id != "" ? var.subnet_id : null
  security_group_id           = var.security_group_id != "" ? var.security_group_id : null
  associate_public_ip_address = true

  ssh_username = "ec2-user"

  # Bare metal takes longer to stop/start
  aws_polling {
    delay_seconds = 30
    max_attempts  = 60
  }

  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 250
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name               = "${var.cluster_name}-kata-al2023-baremetal"
    KataVersion        = var.kata_version
    KubernetesVersion  = var.kubernetes_version
    BuildInstanceType  = var.baremetal_build_instance_type
    VirtualizationMode = "baremetal"
  }
}

# =============================================================================
# Build Configuration
# =============================================================================
build {
  # Use nested virtualization by default for cost savings
  # Switch to baremetal source for performance-critical deployments
  sources = var.use_nested_virtualization ? ["source.amazon-ebs.kata_nested"] : ["source.amazon-ebs.kata_baremetal"]

  provisioner "shell" {
    environment_vars = [
      "KATA_VERSION=${var.kata_version}"
    ]
    script = "install-kata.sh"
  }
}
