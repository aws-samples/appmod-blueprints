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
        compositionSelector: {
          matchLabels: {
            "awsblueprints.io/provider": "aws"
            "awsblueprints.io/environment": "prod"
            "awsblueprints.io/createDBSubnetGroup": "true"
            "awsblueprints.io/dbEngine": "mysql"
          }
        }
        resourceConfig: {
            name: context.name
            deletionPolicy: "Delete"
            tags: [
              {
                key: "env"
                value: "prod"
              },
              {
                key: "app"
                value: "\(context.name)"
              },
            ]
        }
        databaseName: "initdb"
        deploy: "\(parameter.deploy)"
    }
  }
	parameter: {
    deploy: string
	}
}
