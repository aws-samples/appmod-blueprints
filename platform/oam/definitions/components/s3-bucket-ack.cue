"s3-bucket-ack": {
	alias: ""
	annotations: {}
	attributes: workload: type: "autodetects.core.oam.dev"
	description: "S3 Bucket ACK"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "s3.services.k8s.aws/v1alpha1"
		kind:       "Bucket"
		metadata: {
			name: "\(parameter.name)"
			annotations: {
				"services.k8s.aws/region":              "\(parameter.region)"
				"argocd.argoproj.io/sync-options": "Ignore=true,SkipDryRunOnMissingResource=true"
			}
		}
		spec: name: "\(parameter.name)"
	}

	parameter: {
		name:   string
		region: string
	}
}
