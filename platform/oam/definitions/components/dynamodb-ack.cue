"ddb-table": {
	alias: ""
	annotations: {}
	attributes: workload: type: "autodetects.core.oam.dev"
	description: "DynamoDB Table ACK"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "dynamodb.services.k8s.aws/v1alpha1"
		kind:       "Table"
		metadata: {
			name: "\(parameter.name)"
			annotations: {
				"services.k8s.aws/region":         "\(parameter.region)"
				"argocd.argoproj.io/sync-options": "Ignore=true,SkipDryRunOnMissingResource=true"
			}
		}
		spec: {
			tableName:   "\(parameter.name)"
			billingMode: "PAY_PER_REQUEST"
			attributeDefinitions: [{
				attributeName: "\(parameter.attributeName)"
				attributeType: "\(parameter.attributeType)"
			}]
			keySchema: [{
				attributeName: "\(parameter.attributeName)"
				keyType:       "HASH"
			}]
		}
	}

	parameter: {
		name:          string
		region:        string
		attributeName: string
		attributeType: string
	}
}
