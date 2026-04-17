import "strings"

"agentcore-memory": {
	alias: ""
	annotations: {}
	attributes: {
		workload: type: "autodetects.core.oam.dev"
		status: healthPolicy: "isHealth: *(context.output.status.atProvider.id != \"\") | false"
	}
	description: "AgentCore Memory provisioned via Crossplane managed resource with IAM policy"
	labels: {}
	type: "component"
}

template: {
	let _autoName = strings.Replace(context.namespace + "_" + context.name, "-", "_", -1)

	output: {
		apiVersion: "bedrockagentcore.aws.m.upbound.io/v1beta1"
		kind:       "Memory"
		metadata: name: context.name
		spec: {
			forProvider: {
				name:                parameter.memoryName
				region:              parameter.region
				description:         parameter.description
				eventExpiryDuration: parameter.eventExpiryDuration
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
		// +usage=Memory name in AWS (must match ^[a-zA-Z][a-zA-Z0-9_]{0,47}$). Defaults to <namespace>_<componentName>
		memoryName: *_autoName | string
		// +usage=AWS region
		region: *"us-west-2" | string
		// +usage=Description of the memory
		description: *"AgentCore Memory" | string
		// +usage=Number of days after which events expire (3-365)
		eventExpiryDuration: *30 | int
	}
}
