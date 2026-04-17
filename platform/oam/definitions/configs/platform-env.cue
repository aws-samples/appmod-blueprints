metadata: {
	name:        "platform-env"
	alias:       "Platform Environment"
	description: "Cluster-level environment metadata shared across all components"
	scope:       "system"
	sensitive:   false
}

template: {
	parameter: {
		// +usage=Environment name (e.g. dev, staging, prod)
		envName: string
		// +usage=EKS cluster name
		clusterName: string
		// +usage=AWS region
		region: string
	}
}
