# Bedrock Guardrail overlay for finance topics.
# Apply alongside the existing guardrail in terraform/bedrock_guardrail.tf.
# This file augments — it does not replace.

resource "aws_bedrock_guardrail" "finance" {
  name                      = "${var.project_name}-finance"
  description               = "Finance assistant — denies specific securities, guaranteed returns, insider info, tax evasion; blocks financial PII"
  blocked_input_messaging   = "I can't process that input. If it contained account numbers, SSNs, or credentials, please remove them and try again."
  blocked_outputs_messaging = "I can't produce that output. Ask me to explain the concept or run the math instead."

  content_policy_config {
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
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
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  # Denied topics — finance-specific
  topic_policy_config {
    topics_config {
      name       = "SpecificSecurityRecommendations"
      definition = "Recommendations to buy, sell, or hold specific stocks, ETFs, mutual funds, cryptocurrencies, bonds, or other named securities."
      examples = [
        "You should buy NVDA",
        "Sell your Tesla shares now",
        "VTSAX is the best fund for you",
        "Put 20% in Bitcoin",
      ]
      type = "DENY"
    }
    topics_config {
      name       = "GuaranteedReturns"
      definition = "Statements that promise or guarantee investment returns, or that frame projections as certain rather than conditional on assumptions."
      examples = [
        "You will definitely have $2M at retirement",
        "This strategy guarantees 10% annual returns",
        "You can't lose money doing this",
      ]
      type = "DENY"
    }
    topics_config {
      name       = "InsiderOrMaterialNonPublic"
      definition = "Any information framed as insider knowledge, material non-public information, or guidance based on non-public data about a company."
      examples = [
        "I heard Apple is about to announce",
        "My friend at the company said",
        "There is a leaked earnings report",
      ]
      type = "DENY"
    }
    topics_config {
      name       = "TaxEvasion"
      definition = "Guidance on evading taxes, hiding income from tax authorities, or structuring transactions to defeat reporting requirements."
      examples = [
        "How do I hide this income from the IRS",
        "How to structure deposits to avoid CTR filing",
      ]
      type = "DENY"
    }
  }

  # Sensitive information
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "US_SOCIAL_SECURITY_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "US_BANK_ACCOUNT_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "US_BANK_ROUTING_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_CVV"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "PASSWORD"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "AWS_ACCESS_KEY"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "AWS_SECRET_KEY"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "NAME"
      action = "ANONYMIZE"
    }
  }

  word_policy_config {
    managed_word_lists_config {
      type = "PROFANITY"
    }
    # Credential-shape filters: if the model is ever coaxed (by prompt
    # injection, confused tool loop, or bug) into echoing a string that
    # looks like a secret, the guardrail blocks the response before it
    # reaches the user's screen or session logs. Belt and braces — the
    # primary defense is not exposing secrets to the model at all.
    words_config {
      text = "sk-"
    }
    words_config {
      text = "AKIA"
    }
    words_config {
      text = "ASIA"
    }
    words_config {
      text = "BEGIN PRIVATE KEY"
    }
    words_config {
      text = "BEGIN RSA PRIVATE KEY"
    }
    words_config {
      text = "BEGIN OPENSSH PRIVATE KEY"
    }
  }
}

resource "aws_bedrock_guardrail_version" "finance" {
  guardrail_arn = aws_bedrock_guardrail.finance.guardrail_arn
  description   = "Finance assistant initial release"
}

output "finance_guardrail_id" {
  value = aws_bedrock_guardrail.finance.guardrail_id
}

output "finance_guardrail_version" {
  value = aws_bedrock_guardrail_version.finance.version
}
