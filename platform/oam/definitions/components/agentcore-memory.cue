import "strings"

"agentcore-memory": {
	alias: ""
	annotations: {}
	attributes: {
		workload: type: "autodetects.core.oam.dev"
		status: healthPolicy: "isHealth: *(context.output.status.atProvider.outputs.MemoryId != \"\") | false"
	}
	description: "AgentCore Memory provisioned via CloudFormation with IAM policy"
	labels: {}
	type: "component"
}

template: {
	let _autoName = strings.Replace(context.namespace + "_" + context.name, "-", "_", -1)
	let _memoryName = *parameter.memoryNameOverride | _autoName

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
					        "Name": "\(_memoryName)",
					        "Description": "\(parameter.description)",
					        "EventExpiryDuration": \(parameter.eventExpiryDuration)
					      }
					    }
					  },
					  "Outputs": {
					    "MemoryId": {
					      "Value": {"Fn::GetAtt": ["Memory", "MemoryId"]}
					    },
					    "MemoryArn": {
					      "Value": {"Fn::GetAtt": ["Memory", "MemoryArn"]}
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
		// +usage=Override memory name in AWS (must match ^[a-zA-Z][a-zA-Z0-9_]{0,47}$). If not set, auto-generates <namespace>_<componentName>
		memoryNameOverride?: string
		// +usage=AWS region
		region: *"us-west-2" | string
		// +usage=Description of the memory
		description: *"AgentCore Memory" | string
		// +usage=Number of days after which events expire (7-365)
		eventExpiryDuration: *30 | int
	}
}
