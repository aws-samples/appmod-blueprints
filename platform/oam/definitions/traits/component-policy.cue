import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

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
		appName:   string
		name:      string
		namespace: string
	}
	parameter: {
		policy?: string
		service: string
	}

	// The object keeps the name <appName>-<component>-iam-policy: the
	// aws-service-identity trait's accessFor finds it by that name. The AWS policy
	// name (crossplane.io/external-name) is account-global, so it carries the cluster
	// and a hash, like the trait's role name:
	//   <first 100 chars of "<cluster>-<appName>-<component>">-<8 hex>-iam-policy   (<= 128)
	// where the 8 hex chars are sha256("<region>/<cluster>/<namespace>/<appName>/<component>").
	// Without it, the same app on two clusters of one account (dev and prod spokes,
	// or two installs) shares one policy.
	_cluster:    "{{ .Values.global.clusterName }}"
	_region:     "{{ .Values.global.awsRegion }}"
	_policyKey:  _region + "/" + _cluster + "/" + context.namespace + "/" + context.appName + "/" + context.name
	_policyHash: strings.SliceRunes(hex.Encode(sha256.Sum256(_policyKey)), 0, 8)
	_policyBase: _cluster + "-" + context.appName + "-" + context.name
	_policyHead: [if len(_policyBase) > 100 {strings.SliceRunes(_policyBase, 0, 100)}, _policyBase][0]
	_policyName: _policyHead + "-" + _policyHash + "-iam-policy"

	outputs: {
		if parameter.policy == _|_ {
			"\(context.appName)-\(context.name)-iam-policy": {
				apiVersion: "iam.aws.upbound.io/v1beta1"
				kind:       "Policy"
				metadata: {
					name: "\(context.appName)-\(context.name)-iam-policy"
					annotations: "crossplane.io/external-name": _policyName
				}
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
				metadata: {
					name: "\(context.appName)-\(context.name)-iam-policy"
					annotations: "crossplane.io/external-name": _policyName
				}
				spec: {
					providerConfigRef: name: "default"
					forProvider: policy:     "\(parameter.policy)"
				}
			}
		}
	}
}
