resource "aws_bedrock_guardrail" "openclaw" {
  name                      = "${local.cluster_name}-guardrail"
  description               = "Content filtering for OpenClaw agent sandboxes — blocks prompt injection and harmful outputs"
  blocked_input_messaging   = "This request was blocked by content policy."
  blocked_outputs_messaging = "This response was blocked by content policy."

  # Block harmful content categories
  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
  }

  # Block sensitive data (PII) from leaking in outputs
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "AWS_ACCESS_KEY"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "AWS_SECRET_KEY"
      action = "BLOCK"
    }
  }

  tags = local.tags
}

resource "aws_bedrock_guardrail_version" "openclaw" {
  guardrail_arn = aws_bedrock_guardrail.openclaw.guardrail_arn
  description   = "Production version"
}

output "bedrock_guardrail_id" {
  description = "Bedrock Guardrail ID — referenced in LiteLLM model config"
  value       = aws_bedrock_guardrail.openclaw.guardrail_id
}

output "bedrock_guardrail_version" {
  description = "Bedrock Guardrail version"
  value       = aws_bedrock_guardrail_version.openclaw.version
}
