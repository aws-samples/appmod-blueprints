# packer-bake.tf — Build Kata AMI via Packer (first-apply only)
# Skipped if var.kata_ami_id is set (use prebuilt AMI) or if an AMI tagged
# Name=openclaw-kata-* already exists.

data "aws_ami" "existing_kata" {
  count       = var.kata_ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["self"]
  filter {
    name   = "name"
    values = ["openclaw-kata-*"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

locals {
  # Priority: explicit var > existing AMI > (null; packer will bake)
  resolved_kata_ami = var.kata_ami_id != "" ? var.kata_ami_id : (
    length(data.aws_ami.existing_kata) > 0 && try(data.aws_ami.existing_kata[0].id, "") != ""
    ? data.aws_ami.existing_kata[0].id
    : null
  )
  needs_packer_build = local.resolved_kata_ami == null
}

resource "null_resource" "packer_build_kata" {
  count = local.needs_packer_build ? 1 : 0

  triggers = {
    script_hash = filesha256("${path.module}/../packer/install-kata.sh")
    hcl_hash    = filesha256("${path.module}/../packer/kata-ami.pkr.hcl")
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/../packer"
    command     = <<-EOT
      set -euo pipefail
      which packer >/dev/null || { echo "packer CLI required"; exit 1; }
      packer init .
      packer build -var "region=${var.region}" -var "source_type=nested" kata-ami.pkr.hcl
    EOT
  }
}

# After build, re-resolve AMI ID via SSM parameter that packer writes
data "aws_ssm_parameter" "kata_ami" {
  count      = local.needs_packer_build ? 1 : 0
  name       = "/openclaw/kata-ami-id"
  depends_on = [null_resource.packer_build_kata]
}

locals {
  final_kata_ami_id = local.needs_packer_build ? data.aws_ssm_parameter.kata_ami[0].value : local.resolved_kata_ami
}

output "kata_ami_id" {
  value       = local.final_kata_ami_id
  description = "AMI ID used by Karpenter kata NodePools"
}
