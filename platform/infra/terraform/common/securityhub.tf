# Use null resource to ensure Security Hub is enabled without conflicts
resource "null_resource" "securityhub_account" {
  provisioner "local-exec" {
    command = <<-EOT
      aws securityhub enable-security-hub --enable-default-standards 2>/dev/null || true
    EOT
  }
}

resource "aws_securityhub_insight" "kyverno" {
  depends_on = [null_resource.securityhub_account]
  group_by_attribute = "ProductName"
  name               = "${var.resource_prefix}-kyverno-findings"
  filters {
    company_name {
      comparison = "EQUALS"
      value      = "Kyverno"
    }
    record_state {
      comparison = "EQUALS"
      value      = "ACTIVE"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NEW"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NOTIFIED"
    }
  }
}

resource "aws_securityhub_insight" "kyverno_disallow_privileged" {
  depends_on = [null_resource.securityhub_account]
  group_by_attribute = "ProductName"
  name               = "${var.resource_prefix}-kyverno-disallow-privilege-escalation"
  filters {
    company_name {
      comparison = "EQUALS"
      value      = "Kyverno"
    }
    record_state {
      comparison = "EQUALS"
      value      = "ACTIVE"
    }
    resource_details_other {
      comparison = "EQUALS"
      key        = "Policy"
      value      = "disallow-privilege-escalation"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NEW"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NOTIFIED"
    }
  }
}

resource "aws_securityhub_insight" "kyverno_restrict-image-registries" {
  depends_on = [null_resource.securityhub_account]
  group_by_attribute = "ProductName"
  name               = "${var.resource_prefix}-kyverno-restrict-image-registries"
  filters {
    company_name {
      comparison = "EQUALS"
      value      = "Kyverno"
    }
    record_state {
      comparison = "EQUALS"
      value      = "ACTIVE"
    }
    resource_details_other {
      comparison = "EQUALS"
      key        = "Policy"
      value      = "restrict-image-registries"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NEW"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NOTIFIED"
    }
  }
}

resource "aws_securityhub_insight" "kyverno_require-run-as-nonroot" {
  depends_on = [null_resource.securityhub_account]
  group_by_attribute = "ProductName"
  name               = "${var.resource_prefix}-kyverno-require-run-as-nonroot"
  filters {
    company_name {
      comparison = "EQUALS"
      value      = "Kyverno"
    }
    record_state {
      comparison = "EQUALS"
      value      = "ACTIVE"
    }
    resource_details_other {
      comparison = "EQUALS"
      key        = "Policy"
      value      = "require-run-as-nonroot"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NEW"
    }
    workflow_status {
      comparison = "EQUALS"
      value      = "NOTIFIED"
    }
  }
}
