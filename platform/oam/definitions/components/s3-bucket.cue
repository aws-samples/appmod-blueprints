"s3-bucket": {
	alias: ""
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "apps/v1"
		kind:       "Deployment"
	}
	description: "S3 Bucket"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "s3.aws.upbound.io/v1beta1"
		kind:       "Bucket"
		metadata: name: "\(parameter.name)"
		spec: {
			forProvider: region: "\(parameter.region)"
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
					      "Action": ["s3:*"],
					      "Resource": "*"
					    }
					  ]
					}
					"""}
			}
		}
	}

	parameter: {
		name:   string
		region: string
	}
}
