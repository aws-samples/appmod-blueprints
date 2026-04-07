"agentcore-memory": {
	alias: ""
	annotations: {}
	attributes: workload: type: "autodetects.core.oam.dev"
	description: "AgentCore Memory provisioned via CloudFormation with IAM policy"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "cloudformation.aws.upbound.io/v1beta1"
		kind:       "Stack"
		metadata: name: "\(context.name)"
		spec: {
			forProvider: {
				name:   "\(context.name)"
				region: parameter.region
				templateBody: {"""
					{
					  "AWSTemplateFormatVersion": "2010-09-09",
					  "Description": "AgentCore Memory for \(context.name)",
					  "Resources": {
					    "Memory": {
					      "Type": "AWS::BedrockAgentCore::Memory",
					      "Properties": {
					        "Name": "\(context.name)",
					        "Description": "\(parameter.description)",
					        "EventExpiryDuration": \(parameter.eventExpiryDuration)
					      }
					    }
					  },
					  "Outputs": {
					    "MemoryId": {
					      "Value": {"Ref": "Memory"}
					    },
					    "MemoryArn": {
					      "Value": {"Fn::GetAtt": ["Memory", "Arn"]}
					    }
					  }
					}
					"""}
			}
			providerConfigRef: name: "provider-aws-config"
		}
	}

	outputs: {
		"\(context.name)-policy": {
			apiVersion: "iam.platform.aws/v1alpha1"
			kind:       "ComponentPolicy"
			metadata: {
				name:      "\(context.name)-policy"
				namespace: context.namespace
			}
			spec: {
				componentName: context.name
				namespace:     context.namespace
				policyDocument: {"""
					{
					  "Version": "2012-10-17",
					  "Statement": [
					    {
					      "Effect": "Allow",
					      "Action": ["bedrock-agentcore:*"],
					      "Resource": "*"
					    },
					    {
					      "Effect": "Allow",
					      "Action": [
					        "bedrock:InvokeModel",
					        "bedrock:InvokeModelWithResponseStream"
					      ],
					      "Resource": "*"
					    }
					  ]
					}
					"""}
			}
		}
	}

	parameter: {
		// +usage=AWS region
		region: *"us-west-2" | string
		// +usage=Description of the memory
		description: *"AgentCore Memory" | string
		// +usage=Number of days after which events expire (7-365)
		eventExpiryDuration: *30 | int
	}
}
