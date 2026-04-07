"dynamodb-table": {
	alias: ""
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "apps/v1"
		kind:       "Deployment"
	}
	description: "Amazon DynamoDB Table"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "dynamodb.aws.upbound.io/v1beta1"
		kind:       "Table"
		metadata: name: parameter.tableName
		spec: {
			forProvider: {
				attribute: [
					{
						name: parameter.partitionKeyName
						type: "S"
					},
					{
						name: parameter.sortKeyName
						type: "S"
					},
				]
				hashKey:       parameter.partitionKeyName
				rangeKey:      parameter.sortKeyName
				billingMode:   "PROVISIONED"
				readCapacity:  parameter.readCapacity
				region:        parameter.region
				tags: Environment: parameter.environment
				writeCapacity: parameter.writeCapacity
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
					      "Action": ["dynamodb:*"],
					      "Resource": "*"
					    }
					  ]
					}
					"""}
			}
		}
	}

	parameter: {
		tableName:        string
		partitionKeyName: string
		sortKeyName:      string
		readCapacity:     *20 | int
		writeCapacity:    *20 | int
		region:           string
		environment:      *"dev" | string
	}
}
