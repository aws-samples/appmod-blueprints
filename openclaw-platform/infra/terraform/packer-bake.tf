# packer-bake.tf — Kata AMI resolution
#
# AMI baking happens BEFORE terraform apply via scripts/install.sh which:
#   1. Runs packer build (takes ~12 min first time)
#   2. Writes the AMI ID to terraform.auto.tfvars
#   3. Then runs terraform apply with kata_ami_id populated
#
# This avoids terraform data-source chicken-and-egg where the AMI doesn't
# exist on first apply. If kata_ami_id is empty we fail fast with a clear
# message telling the user to bake first.

locals {
  kata_ami_id_resolved = var.kata_ami_id
}

resource "null_resource" "validate_kata_ami" {
  count = var.enable_kata_nodes && local.kata_ami_id_resolved == "" ? 1 : 0

  provisioner "local-exec" {
    command = <<-EOT
      echo "ERROR: var.kata_ami_id is empty."
      echo "Run scripts/install.sh to bake the Kata AMI first, which will populate terraform.auto.tfvars."
      echo "Or bake manually:"
      echo "  cd ../packer && packer init . && packer build -var region=${var.region} -var source_type=nested kata-ami.pkr.hcl"
      exit 1
    EOT
  }
}

output "kata_ami_id" {
  value       = local.kata_ami_id_resolved
  description = "AMI ID used by Karpenter kata NodePools"
}
