################################################################################
# Usage Telemetry
################################################################################

resource "aws_cloudformation_stack" "usage_tracking" {
  count = var.usage_tracking_tag != null ? 1 : 0

  name = "platform-engineering-on-eks"

  on_failure = "DO_NOTHING"
  template_body = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09",
    Description              = "Usage telemetry for Modern Engineering. (${var.usage_tracking_tag})",
    Resources = {
      EmptyResource = {
        Type = "AWS::CloudFormation::WaitConditionHandle"
      }
    }
  })
}
