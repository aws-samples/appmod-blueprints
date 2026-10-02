"component-iam-policy": {
	"annotations": {}
	"attributes": {
		"appliesToWorkloads": [
			"deployments.apps",
			"statefulsets.apps",
			"daemonsets.apps",
			"jobs.batch",
		]
		"podDisruptive": false
	}
	"description": "Specify an IAM policy for your workload to get access to the component"
	"labels": {}
	"type": "trait"
}

template: {
	context: {
		appName: string
		name:    string
	}
	parameter: {
		policy?: string
		service: string
	}
	outputs: {
		if parameter.policy == _|_ {
			"\(context.appName)-\(context.name)-iam-policy": {
				apiVersion: "iam.aws.upbound.io/v1beta1"
				kind:       "Policy"
				metadata: name: "\(context.appName)-\(context.name)-iam-policy"
				spec: {
					providerConfigRef: name: "default"
					forProvider: policy: {"""
              {
                "Version": "2012-10-17",
                "Statement": [
                  {
                    "Effect": "Allow",
                    "Action": [
                      "\(parameter.service):*"
                    ],
                    "Resource": "*"
                  }
                ]
              }
            """}
				}
			}
		}

		if parameter.policy != _|_ {
			"\(context.appName)-\(context.name)-iam-policy": {
				apiVersion: "iam.aws.upbound.io/v1beta1"
				kind:       "Policy"
				metadata: name: "\(context.appName)-\(context.name)-iam-policy"
				spec: {
					providerConfigRef: name: "default"
					forProvider: policy:     "\(parameter.policy)"
				}
			}
		}
	}
}
