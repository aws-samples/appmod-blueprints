"dynamodb-table": {
	"alias": ""
	"annotations": {}
	"attributes": {
		"workload": {
			"definition": {
				"apiVersion": "apps/v1"
				"kind":       "Deployment"
			}
		}
	}
	"description": "Amazon DynamoDB Table"
	"labels": {}
	"type": "component"
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
				hashKey:      parameter.partitionKeyName
				rangeKey:     parameter.sortKeyName
				billingMode:  "PROVISIONED"
				readCapacity: parameter.readCapacity
				region:       parameter.region
				tags: Environment: parameter.environment
				writeCapacity: parameter.writeCapacity
			}
			providerConfigRef: name: "default"
		}
	}

	parameter: {
		// Table name
		tableName: string

		// Partition key name
		partitionKeyName: string

		// Sort key name
		sortKeyName: string

		// Read capacity units
		readCapacity: *20 | int

		// Write capacity units
		writeCapacity: *20 | int

		// AWS region
		region: string

		// Environment tag
		environment: *"dev" | string
	}
}
