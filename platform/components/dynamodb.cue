"dynamodb-table": {
	alias: "table"
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "aws-service/v1"
		kind:       "Table"
	}
	description: "AWS DynamoDB table"
	labels: {}
	parameter: {
		attributeDefinitions: [...#AttributeDefinition]
		keySchema: [...#KeySchema]
		tableName: string
	}
	type: "component"
}

AttributeDefinition: {
	attributeName: string
	attributeType: string
}

KeySchema: {
	attributeName: string
	keyType:       string
}

template: {
	output: {
		apiVersion: "dynamodb.aws.crossplane.io/v1alpha1"
		kind:       "Table"
		metadata: {
			name: paramter.name
		}
		spec: {
			forProvider: {
				region:               parameter.region
				name:                 paramater.tableName
				billingMode:          "PAY_PER_REQUEST"
				attributeDefinitions: parameter.attributeDefinition
				keySchema:            paramter.keySchema
			}
			providerConfigRef: {
				name: "aws-provider"
			}
		}
	}
}
