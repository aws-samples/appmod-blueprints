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
		apiVersion: "rds.aws.upbound.io/v1beta1"
		kind:       "Cluster"
		metadata: {
			name: "\(context.name)-cluster"
		}
		spec: {
			forProvider: {
				autoGeneratePassword: true
				engine:               "aurora-mysql"
				masterPasswordSecretRef: {
					key:       "password"
					name:      "\(context.name)-cluster-password"
					namespace: "vela-system"
				}
				masterUsername: "awsrdsadmin"
				region:         "\(parameter.region)"
				dbSubnetGroupNameRef: name: "\(context.name)-subnetgroup"
				skipFinalSnapshot: true
			}
			writeConnectionSecretToRef: {
				name:      "\(context.name)-cluster-connection"
				namespace: "vela-system"
			}
		}
	}
	outputs: {
		"\(context.name)-subnetgroup": {
			apiVersion: "rds.aws.upbound.io/v1beta1"
			kind:       "SubnetGroup"
			metadata: name: "\(context.name)-subnetgroup"
			spec: {
				forProvider: {
					region: "\(parameter.region)"
					subnetIds: [ for subnetId in parameter.subnetIds {"\(subnetId)"}]
				}
			}
		}

		"\(context.name)-instance": {
			apiVersion: "rds.aws.upbound.io/v1beta1"
			kind:       "ClusterInstance"
			metadata: name: "\(context.name)-clusterinstance"
			spec: {
				forProvider: {
					region: "\(parameter.region)"
					clusterIdentifierRef: name: "\(context.name)-cluster"
					engine:        "aurora-mysql"
					instanceClass: "db.r5.large"
				}
			}
		}

	}

	parameter: {
		region: string
		subnetIds: [...string]
	}
}
