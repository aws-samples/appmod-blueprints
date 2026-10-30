// aws-service-identity TraitDefinition
//
// Grants a workload an AWS IAM identity via EKS Pod Identity — secretlessly and
// with zero cluster parameters. Emits a platform.gitops.io/PodIdentity claim
// (XPodIdentity Composition), which resolves clusterName/region ambiently from
// the cluster's env-config EnvironmentConfig and creates the IAM Role (named by
// this trait, see _roleName) + PodIdentityAssociation bound to the workload's
// ServiceAccount (owned by the component, name == context.name).
//
// Role name: IAM names are account-global, so "<serviceAccount>-role" was shared
// by every cluster of the account that ran the same workload (dev and prod spokes,
// or two installs). The name is now
//   <first 50 chars of "<cluster>-<serviceAccount>">-<8 hex>-role   (<= 64 chars)
// where the 8 hex chars are sha256("<region>/<cluster>/<namespace>/<serviceAccount>").
// The cluster is the platform's global.clusterName (aws_cluster_name annotation),
// the same name the PodIdentityAssociation targets; for the hub it starts with the
// install's resource_prefix. The hash keeps the name one-to-one with the
// (region, cluster, namespace, serviceAccount) it serves even when truncated.
//
// Ordering: EKS injects Pod Identity creds via a mutating webhook at pod
// admission, which only fires if the association already exists. To avoid that
// race we SELF-INJECT the creds URI + the pods.eks.amazonaws.com projected
// token, and add an init container that blocks (via `kubectl wait
// --for=condition=Ready`) until the PodIdentity resource is Ready — i.e. the
// Composition has created the IAM Role + PodIdentityAssociation.
//
// NOTE: this gate is CONTROL-PLANE readiness only. The brief AWS IAM data-plane
// propagation window (e.g. freshly-attached accessFor policies not yet enforced)
// is intentionally NOT handled here — handle it with app-level retry.
//
// The init container reads the PodIdentity via the pod's ServiceAccount, so the
// trait also emits a namespaced Role/RoleBinding granting get/list/watch on it.
// The image is distroless (no shell); `kubectl wait` is a single invocation, and
// if the PodIdentity isn't created yet the init container fails and the kubelet
// retries it (init-container restart) until it exists and is Ready.
//
// Cloud-agnostic sibling pattern: gcp-service-identity / azure-service-identity.
import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

"aws-service-identity": {
	alias:       ""
	annotations: {}
	attributes: {
		appliesToWorkloads: ["deployments.apps", "rollouts.argoproj.io"]
		conflictsWith: []
		podDisruptive:   true
		workloadRefPath: ""
	}
	description: "Grant a workload an AWS IAM identity via EKS Pod Identity (secretless, no cluster params)"
	labels: {}
	type: "trait"
}

template: {
	parameter: {
		// +usage=Sibling component names whose IAM policies to attach to this workload's role
		accessFor?: [...string]
		// +usage=Container to inject AWS credentials into (defaults to the component name)
		containerName: *context.name | string
		// +usage=Distroless kubectl image for the PodIdentity-readiness init gate (entrypoint = kubectl).
		// Chainguard kubectl:latest, pinned by multi-arch index digest (amd64+arm64) for immutability.
		waitImage: *"public.ecr.aws/chainguard/kubectl:latest@sha256:5cd49041fed950723afaefcd141a163e5a5306f243841510d3e1e3667b0cdfb9" | string
	}

	// Self-injected creds URI + token mount (the EKS webhook skips injection when
	// AWS_CONTAINER_CREDENTIALS_FULL_URI is already present).
	//
	// AWS_REGION / AWS_DEFAULT_REGION come from the chart's global.awsRegion, which
	// the addon ApplicationSet sources per-cluster from the cluster secret's
	// aws_region annotation. Region is therefore ENVIRONMENT config supplied by the
	// platform, and must never appear in a developer's OAM: the same Application
	// deploys unchanged to any region. Both names are set because SDKs differ in
	// which one they read.
	_credsEnv: [
		{name: "AWS_CONTAINER_CREDENTIALS_FULL_URI", value: "http://169.254.170.23/v1/credentials"},
		{name: "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE", value: "/var/run/secrets/pods.eks.amazonaws.com/serviceaccount/eks-pod-identity-token"},
		{name: "AWS_REGION", value: "{{ .Values.global.awsRegion }}"},
		{name: "AWS_DEFAULT_REGION", value: "{{ .Values.global.awsRegion }}"},
	]
	_tokenMount: {
		name:      "eks-pod-identity-token"
		mountPath: "/var/run/secrets/pods.eks.amazonaws.com/serviceaccount"
		readOnly:  true
	}

	// IAM role name, unique per (region, cluster, namespace, serviceAccount); see the
	// header. Computed here (not in the Composition) because the attachments below
	// need it, and passed to the Composition through the claim's spec.roleName.
	_cluster: "{{ .Values.global.clusterName }}"
	_region:  "{{ .Values.global.awsRegion }}"
	_roleKey: _region + "/" + _cluster + "/" + context.namespace + "/" + context.name
	_roleHash: strings.SliceRunes(hex.Encode(sha256.Sum256(_roleKey)), 0, 8)
	_roleBase: _cluster + "-" + context.name
	_roleHead: [if len(_roleBase) > 50 {strings.SliceRunes(_roleBase, 0, 50)}, _roleBase][0]
	_roleName: _roleHead + "-" + _roleHash + "-role"

	outputs: {
		// XPodIdentity claim — the Composition resolves clusterName/region from
		// env-config and creates the IAM Role (named spec.roleName) + PodIdentityAssociation.
		"\(context.name)-identity": {
			apiVersion: "platform.gitops.io/v1alpha1"
			kind:       "PodIdentity"
			metadata: {
				name:      context.name
				namespace: context.namespace
			}
			spec: {
				serviceAccount: context.name
				namespace:      context.namespace
				roleName:       _roleName
			}
		}

		// RBAC so the pod's ServiceAccount can read its own PodIdentity resource
		// (used by the wait-for-pod-identity init container). Namespaced, read-only.
		"\(context.name)-podidentity-reader-role": {
			apiVersion: "rbac.authorization.k8s.io/v1"
			kind:       "Role"
			metadata: {
				name:      "\(context.name)-podidentity-reader"
				namespace: context.namespace
			}
			rules: [{
				apiGroups: ["platform.gitops.io"]
				resources: ["podidentities"]
				verbs: ["get", "list", "watch"]
			}]
		}
		"\(context.name)-podidentity-reader-binding": {
			apiVersion: "rbac.authorization.k8s.io/v1"
			kind:       "RoleBinding"
			metadata: {
				name:      "\(context.name)-podidentity-reader"
				namespace: context.namespace
			}
			roleRef: {
				apiGroup: "rbac.authorization.k8s.io"
				kind:     "Role"
				name:     "\(context.name)-podidentity-reader"
			}
			subjects: [{
				kind:      "ServiceAccount"
				name:      context.name
				namespace: context.namespace
			}]
		}

		// Attach sibling components' IAM policies to the role the Composition
		// creates (name _roleName). The object name carries the namespace ("." cannot
		// occur in a namespace or component name, so it is one-to-one): these are
		// cluster-scoped objects, and two namespaces running the same component would
		// otherwise share one. It also differs from the former
		// "<name>-<c>-role-policy-attachment", so an upgraded install gets new
		// attachments instead of a role change on the old ones, which the provider
		// refuses (role is immutable on an attachment).
		if parameter.accessFor != _|_ {
			for _, c in parameter.accessFor {
				"\(context.name)-\(c)-iam-policy": {
					apiVersion: "iam.aws.upbound.io/v1beta1"
					kind:       "RolePolicyAttachment"
					metadata: name: "\(context.namespace).\(context.name)-\(c)-role-policy-attachment"
					spec: {
						forProvider: {
							policyArnRef: name: "\(context.appName)-\(c)-iam-policy"
							role: _roleName
						}
						providerConfigRef: name: "default"
					}
				}
			}
		}
	}

	// Patch the workload pod: token volume (for app creds), a PodIdentity-readiness
	// init gate, and creds env on the app container.
	patch: spec: template: spec: {
		// +patchKey=name
		volumes: [{
			name: "eks-pod-identity-token"
			projected: sources: [{
				serviceAccountToken: {
					audience:          "pods.eks.amazonaws.com"
					expirationSeconds: 86400
					path:              "eks-pod-identity-token"
				}
			}]
		}]
		// +patchKey=name
		// Control-plane readiness gate: distroless kubectl (entrypoint = kubectl)
		// blocks until the PodIdentity resource reports Ready. Uses the pod's
		// ServiceAccount (in-cluster config) + the Role/RoleBinding emitted above.
		initContainers: [{
			name:  "wait-for-pod-identity"
			image: parameter.waitImage
			args: [
				"wait", "--for=condition=Ready",
				"podidentities.platform.gitops.io/\(context.name)",
				"-n", context.namespace,
				"--timeout=300s",
			]
		}]
		// +patchKey=name
		containers: [{
			name: parameter.containerName
			// +patchKey=name
			env: _credsEnv
			// +patchKey=name
			volumeMounts: [_tokenMount]
		}]
	}
}
