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
		metadata: {
			name:  "\(parameter.name)"
		}
		spec: {
			forProvider: {
				region: "\(parameter.region)"
			}
		}
	}
	parameter: {
    name: string
    region: string
  }
}
