"s3-bucket": {
	"alias": ""
	"annotations": {}
	"attributes": {
		"workload": {
			"type": "autodetects.core.oam.dev"
		}
	}
	"description": "S3 Bucket"
	"labels": {}
	"type": "component"
}

template: {
	output: {
		apiVersion: "s3.aws.upbound.io/v1beta1"
		kind:       "Bucket"
		metadata: name: "\(parameter.name)"
		spec: {
			forProvider: region:     "\(parameter.region)"
			providerConfigRef: name: "default"
		}
	}
	parameter: {
		name:   string
		region: string
	}
}
