import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

// DEPRECATED — superseded by the `aws-service-identity` TRAIT
// (platform/oam/definitions/traits/aws-service-identity.cue). Kept only so Applications that
// still list this component keep rendering during the migration window; it will be
// removed once nothing references it.
//
// Why it is being replaced: this is a COMPONENT, so every workload that needed an
// AWS identity had to add a second entry to its OAM and hand it cluster-specific
// values (clusterName, clusterRegion, resourcePrefix). That breaks OAM portability
// — the same Application could not deploy unchanged to another cluster or region.
// The trait takes zero parameters: it emits a PodIdentity claim and the
// XPodIdentity Composition resolves cluster and region ambiently from the
// cluster's env-config EnvironmentConfig.
//
// Migration: drop this component, attach `aws-service-identity` to the workload
// component instead, and rename `componentNamesForAccess` to the trait's
// `accessFor`. The workload component (e.g. `service-rollout`) now owns the
// ServiceAccount this used to create.
//
// NOTE: the policyArnRef below (polObj) intentionally names the SAME Policy object as
// the `component-iam-policy` trait: `<appName>-<component>-iam-policy` without a
// global.clusterName, otherwise the trait's per-cluster object name (same rule, same
// inputs), so the old and new identity paths resolve the SAME policy for the duration
// of the migration. Keep the two in step.
"dp-service-account": {
	"alias": ""
	"annotations": {}
	"attributes": {
		"status": {
			"healthPolicy": "    isHealth: context.output.status.atProvider.associationArn != _|_"
		}
		"workload": {
			"type": "autodetects.core.oam.dev"
		}
	}
	"description": "DEPRECATED (use the aws-service-identity trait): Service account creation that enables access to cloud resources"
	"labels": {}
	"type": "component"
}

template: {
	output: {
		apiVersion: "eks.aws.upbound.io/v1beta1"
		kind:       "PodIdentityAssociation"
		metadata: name: "\(context.name)-podidentity"
		spec: {
			forProvider: {
				clusterName: "\(parameter.clusterName)"
				namespace:   "\(context.namespace)"
				region:      "\(parameter.clusterRegion)"
				roleArnRef: {
					name: "\(parameter.resourcePrefix)-\(context.name)-iam-role"
				}
				serviceAccount: "\(context.name)"
			}
			providerConfigRef: name: "default"
		}
	}

	outputs: {
		"\(parameter.resourcePrefix)-\(context.name)-iam-role": {
			apiVersion: "iam.aws.upbound.io/v1beta1"
			kind:       "Role"
			metadata: name: "\(parameter.resourcePrefix)-\(context.name)-iam-role"
			spec: {
				forProvider: assumeRolePolicy: {"""
					  {
					    "Version": "2012-10-17",
					    "Statement": [
					      {
					        "Effect": "Allow",
					        "Principal": {
					          "Service": "pods.eks.amazonaws.com"
					        },
					        "Action": [
					          "sts:AssumeRole",
					          "sts:TagSession"
					        ]
					      }
					    ]
					  }
					"""}
				providerConfigRef: name: "default"
			}
		}

		if parameter.componentNamesForAccess != _|_ {
			for _, c in parameter.componentNamesForAccess {
				let component = context.components["\(c)"]
				let polBase = strings.ToLower(strings.Replace("{{ .Values.global.clusterName }}", "_", "-", -1)) + "-" + context.appName + "-" + c
				let polHead = [if len(polBase) > 100 {strings.SliceRunes(polBase, 0, 100)}, polBase][0]
				let polHash = strings.SliceRunes(hex.Encode(sha256.Sum256("{{ .Values.global.awsRegion }}/{{ .Values.global.clusterName }}/" + context.namespace + "/" + context.appName + "/" + c)), 0, 8)
				// Same object name as the component-iam-policy trait gives its Policy (keep in step).
				let polObj = [if "{{ .Values.global.clusterName }}" == "" {"\(context.appName)-\(c)-iam-policy"}, polHead + "-" + polHash + "-iam-policy"][0]
				if component != _|_ {}
				"\(context.name)-\(c)-iam-policy": {
					apiVersion: "iam.aws.upbound.io/v1beta1"
					kind:       "RolePolicyAttachment"
					metadata: name: "\(context.name)-\(c)-role-policy-attachment"
					spec: {
						forProvider: {
							policyArnRef: name: polObj
							roleRef: name:      "\(parameter.resourcePrefix)-\(context.name)-iam-role"
						}
						providerConfigRef: name: "default"
					}
				}
			}
		}

		"\(context.name)-service-account": {
			apiVersion: "v1"
			kind:       "ServiceAccount"
			metadata: name: "\(context.name)"
		}

	}

	parameter: {
		// +usage=Specify the components with policies to add to the service account
		componentNamesForAccess?: [...string]
		// +usage=Region cluster is in
		clusterRegion: string
		// +usage=name of the cluster for pod identity
		clusterName: string
		// +usage=Resource name prefix for account/region-level segregation
		resourcePrefix: *"peeks" | string
	}
}
