"component-iam-policy": {
	type: "trait"
	annotations: {}
	labels: {}
	description: "Specify an IAM policy for your workload to get access to the component"
	attributes: {
		podDisruptive: false
		appliesToWorkloads: ["deployments.apps", "statefulsets.apps", "daemonsets.apps", "jobs.batch"]
	}
}
template: {
	parameter: {
    policy?: string 
    service: string
	}
	outputs: {
    if parameter.policy == _|_ {
      "\(context.appName)-\(context.name)-iam-policy": {
        apiVersion: "iam.aws.upbound.io/v1beta1"
        kind: "Policy"
        metadata: name: "\(context.appName)-\(context.name)-iam-policy"
        spec: {
          forProvider: {
            policy: {"""
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
    }

    if parameter.policy != _|_ {
      "\(context.appName)-\(context.name)-iam-policy": {
        apiVersion: "iam.aws.upbound.io/v1beta1"
        kind: "Policy"
        metadata: name: "\(context.appName)-\(context.name)-iam-policy"
        spec: {
          name: "\(context.appName)-\(context.name)-iam-policy"
          forProvider: {
            policy: "\(parameter.policy)"
          }
        }
      }
    }
	}
}


