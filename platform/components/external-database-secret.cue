"external-database-secret": {
	alias: ""
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "apps/v1"
		kind:       "Deployment"
	}
	description: "External secret for RDS or standalone relational database instance"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "external-secrets.io/v1beta1"
		kind:       "ExternalSecret"
		metadata: {
			name: context.name
		}
		spec: {
			data: [
				{
					secretKey: "username"
					remoteRef: {key: parameter.secret_name, property: "username"}
				},
				{
					secretKey: "password"
					remoteRef: {key: parameter.secret_name, property: "password"}

				},
				{
					secretKey: "host"
					remoteRef: {key: parameter.secret_name, property: "host"}

				}
			]
			refreshInterval: "1h"
			secretStoreRef: {
				kind: "ClusterSecretStore"
				name: "aws-secret-manager"
			}
			target: {
				name:           parameter.secret_name
				creationPolicy: "Owner"
			}
		}
	}

	parameter: {
		secret_name: string
	}
}
