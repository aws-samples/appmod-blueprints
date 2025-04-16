"rds-cluster-mysql": {
	alias: ""
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "apps/v1"
		kind:       "Deployment"
	}
	description: "Amazon RDS MySQL Cluster"
	labels: {}
	type: "component"
}

template: {
    output: {
        apiVersion: "awsblueprints.io/v1alpha1"
        kind:       "RelationalDatabase"
        metadata: {
            name:      context.name
            namespace: context.namespace
        }
        spec: {
            resourceConfig: {
                name: context.name
                deletionPolicy: "Delete"
                tags: {
                    Name: context.name
                    "crossplane-managed": "true"
                }
            }
            databaseName: "\(context.name)db"
            writeConnectionSecretToRef: {
                name:      "\(context.name)-connection"
                namespace: context.namespace
            }
        }
    }
}
