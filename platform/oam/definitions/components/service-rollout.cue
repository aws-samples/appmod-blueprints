// service-rollout ComponentDefinition
//
// Generic long-running service (micro or monolith) managed by an Argo Rollout with
// canary delivery and optional quality gates. Successor to `appmod-service`, which
// remains in place (deprecated) until consumers have migrated.
//
// WHAT CHANGED FROM appmod-service, and why:
//
//  1. It OWNS a ServiceAccount named `context.name`. appmod-service only
//     REFERENCED one (`parameter.serviceAccount`, default "default"), so nothing
//     created it and most workloads silently ran as `default`. A dedicated SA per
//     component is the workload's single identity anchor.
//
//  2. The `serviceAccount` parameter is GONE. The SA name is now a convention
//     (== component name), not an input. This is what lets `aws-service-identity`
//     attach with no parameters at all: that trait emits a PodIdentity claim for
//     `serviceAccount: context.name`, so an arbitrary SA name would never match.
//
//  3. The `image_name` parameter is GONE. It only ever fed the container name and
//     the Prometheus container filter; both now derive from `context.name`, so the
//     parameter had no remaining purpose. One name, one place.
//
//  4. The inline EKS Pod Identity wiring is GONE (the token volume, its mount, and
//     AWS_CONTAINER_CREDENTIALS_FULL_URI / AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE,
//     previously gated on `serviceAccount != "default"`). That is now the sole job
//     of the `aws-service-identity` trait, which additionally creates the IAM role
//     via the XPodIdentity Composition, sets AWS_REGION, and gates startup on the
//     identity actually existing. Keeping both would double-declare the volume and
//     the env. A workload that needs AWS credentials attaches the trait.
//
// The canary strategy, the functional/performance/metric gates and their
// AnalysisTemplates, the preview Service, the PDB and the AMP wiring are carried
// over unchanged — this is not a behaviour change to delivery, only to identity.
//
// This CUE file is the source of truth. The YAML under
// gitops/addons/charts/kubevela/templates/ is generated from it by
// platform/oam/generate.sh; do not edit the YAML.

import "strings"

"service-rollout": {
	"alias": ""
	"annotations": {}
	"attributes": {
		"workload": {
			"type": "autodetects.core.oam.dev"
		}
	}
	"description": "Generic service managed by an Argo Rollout (canary) with quality gates and a dedicated ServiceAccount"
	"labels": {}
	"type": "component"
}

template: {
	let previewService = "\(context.name)-preview"

	// The amp-workspace-url / amp-workspace-region values are injected at trait
	// render time via KubeVela trait args and consumed below by the
	// Prometheus analysis provider used for canary metric checks. This intentionally
	// mixes KubeVela arg templating with CUE; the args are supplied by the AppmodService
	// RGD from the amp-workspace secret.
	let ampWorkspaceUrl = #"{{ "{{" }}args.amp-workspace-url{{ "}}" }}"#
	let ampWorkspaceRegion = #"{{ "{{" }}args.amp-workspace-region{{ "}}" }}"#

	// Container name is context.name (see note 3 in the file header), so the
	// Prometheus container filter derives from it too.
	let prometheusTargetQuery = "k8s_container_name=\"\(context.name)\", k8s_namespace_name=\"\(context.namespace)\""

	output: {
		apiVersion: "argoproj.io/v1alpha1"
		kind:       "Rollout"
		metadata: name: context.name
		spec: {
			replicas:             parameter.replicas
			revisionHistoryLimit: 2
			selector: matchLabels: app: context.name
			strategy: canary:
			{
				canaryService: previewService
				steps: [
					{
						setWeight: 20
					},
					if parameter.functionalGate != _|_ {
						{
							pause: duration: parameter.functionalGate.pause
						}
					},
					if parameter.functionalGate != _|_ {
						{
							analysis: {
								templates: [
									{
										templateName: "functional-gate-\(context.name)"
									},
								]
								args: [
									{
										name:  "service-name"
										value: previewService
									},
								]
							}
						}
					},
					{
						setWeight: 40
					},
					{
						pause: duration: "5s"
					},
					{
						setWeight: 60
					},
					{
						pause: duration: "5s"
					},
					{
						setWeight: 80
					},
					if parameter.performanceGate != _|_ {
						{
							pause: duration: parameter.performanceGate.pause
						}
					},
					if parameter.performanceGate != _|_ {
						{
							analysis: {
								templates: [
									{
										templateName: "performance-gate-\(context.name)"
									},
								]
								args: [
									{
										name:  "service-name"
										value: previewService
									},
								]
							}
						}
					},
					if parameter.MetricGate != _|_ {
						{
							pause: duration: parameter.MetricGate.pause
						}
					},
					if parameter.metrics != _|_ {
						{
							analysis: {
								templates: [
									{
										templateName: "metrics-\(context.name)"
									},
								]
								args: [
									{
										name:  "service-name"
										value: previewService
									},
								]
							}
						}
					},
				]
			}
			template: {
				metadata: {
					labels: app: context.name
					annotations: {
						if parameter.functionalGate != _|_ {
							color: parameter.functionalGate.extraArgs
						}
						replicas:                       "\(parameter.replicas)"
						"rollout.argoproj.io/revision": parameter.image
					}
				}
				spec: {
					// NOTE: no EKS Pod Identity wiring here by design. Attach the
					// `aws-service-identity` trait to grant this workload an AWS
					// identity — it projects the pod-identity token, injects the
					// credential env (including AWS_REGION), creates the IAM role via
					// the XPodIdentity Composition, and blocks startup until that
					// identity exists. See note 4 in the file header.
					containers: [{
						image:           parameter.image
						imagePullPolicy: "Always"
						// Container name == component name, by convention, so traits
						// that patch "the app container" (e.g. aws-service-identity,
						// whose containerName defaults to context.name) match with no
						// parameters. See note 3 in the file header.
						name: context.name
						ports: [{
							containerPort: parameter.targetPort
						}]
						env: [
							if parameter.env != _|_ for _, e in parameter.env if e.name != "APP_BASE_PATH" {e},
							// APP_BASE_PATH is derived from appPath so prefixed asset/image URLs follow the app path.
							// NOTE (kubevela): appPath and the path-based-ingress trait path are SEPARATE inputs and
							// MUST be set to the same value, or prefixed assets 404. (The kro RGD derives both from
							// a single ingress.path; on the OAM path the manifest/scaffolder must keep them in sync.)
							{
								name:  "APP_BASE_PATH"
								value: parameter.appPath
							},
						]
						if parameter.readinessProbe != _|_ {
							readinessProbe: parameter.readinessProbe
						}
						if parameter.resources != _|_ {
							resources: parameter.resources
						}
					}]
					// Convention, not configuration: the ServiceAccount this component
					// owns (emitted below) carries the same name as the component, which
					// is what aws-service-identity's PodIdentity claim targets.
					serviceAccountName: context.name
					topologySpreadConstraints: [{
						maxSkew:           1
						topologyKey:       "topology.kubernetes.io/zone"
						whenUnsatisfiable: "ScheduleAnyway"
						labelSelector: matchLabels: app: context.name
					}]
				}
			}
		}
	}
	outputs: {
		// Dedicated ServiceAccount — the workload's single identity anchor, and the
		// subject that aws-service-identity binds an IAM role to.
		"service-rollout-serviceaccount": {
			apiVersion: "v1"
			kind:       "ServiceAccount"
			metadata: {
				name:      context.name
				namespace: context.namespace
				labels: app: context.name
			}
		}
		"service-rollout-service": {
			apiVersion: "v1"
			kind:       "Service"
			metadata: name: context.name
			spec: {
				selector: app: context.name
				ports: [{
					port:       parameter.port
					targetPort: parameter.targetPort
				}]
			}
		}
		"service-rollout-preview": {
			apiVersion: "v1"
			kind:       "Service"
			metadata: name: previewService
			spec: {
				selector: app: context.name
				ports: [{
					port:       parameter.port
					targetPort: parameter.targetPort
				}]
			}
		}
		"amp-workspace-secrets": {
			apiVersion: "external-secrets.io/v1"
			kind:       "ExternalSecret"
			metadata: {
				name:      "amp-workspace-secrets-\(context.name)"
				namespace: context.namespace
			}
			spec: {
				secretStoreRef: {
					name: "aws-secrets-manager"
					kind: "ClusterSecretStore"
				}
				target: {
					name: "amp-workspace-\(context.name)"
					template: type: "Opaque"
				}
				data: [
					{
						secretKey: "amp-workspace-url"
						remoteRef: {
							key:      "peeks/platform/amp"
							property: "amp-workspace"
						}
					},
					{
						secretKey: "amp-workspace-region"
						remoteRef: {
							key:      "peeks/platform/amp"
							property: "amp-region"
						}
					},
				]
			}
		}
		if parameter.metrics != _|_ {
			"success-rate-analysis-template": {
				apiVersion: "argoproj.io/v1alpha1"
				kind:       "AnalysisTemplate"
				metadata: name: "metrics-\(context.name)"
				spec: {
					args: [{
						name: "amp-workspace-url"
						valueFrom: secretKeyRef: {
							name: "amp-workspace-\(context.name)"
							key:  "amp-workspace-url"
						}
					}, {
						name: "amp-workspace-region"
						valueFrom: secretKeyRef: {
							name: "amp-workspace-\(context.name)"
							key:  "amp-workspace-region"
						}
					}]
					metrics:
					[
						for idx, criteria in parameter.metrics.evaluationCriteria {
							name: "metric[\(idx)]-\(context.name): \(criteria.metric)"
							if criteria.successOrFailCondition == "success" {
								interval:         criteria.interval
								count:            criteria.count
								successCondition: "result[0] \(criteria.comparisonType) \(criteria.threshold)"
							}
							if criteria.successOrFailCondition == "fail" {
								interval:         criteria.interval
								count:            criteria.count
								failureCondition: "result[0] \(criteria.comparisonType) \(criteria.threshold)"
							}
							provider: prometheus: {
								address: ampWorkspaceUrl
								query: [
									if criteria.function != _|_ if criteria.rateInterval != _|_ {
										"\(criteria.function)(rate(\(criteria.metric){\(prometheusTargetQuery)}[\(criteria.rateInterval)]))"
									},
									if criteria.function != _|_ if criteria.rateInterval == _|_ {
										"\(criteria.function)(\(criteria.metric){\(prometheusTargetQuery)})"
									},
									if criteria.function == _|_ if criteria.rateInterval != _|_ {
										"rate(\(criteria.metric){\(prometheusTargetQuery)}[\(criteria.rateInterval)])"
									},
									if criteria.function == _|_ if criteria.rateInterval == _|_ {
										"\(criteria.metric){\(prometheusTargetQuery)}"
									},
								][0]
								authentication: sigv4: region: ampWorkspaceRegion
							}
						},
					]
				}
			}
		}
		if parameter.functionalGate != _|_ {
			"appmod-functional-analysis-template": {
				kind:       "AnalysisTemplate"
				apiVersion: "argoproj.io/v1alpha1"
				metadata: name: "functional-gate-\(context.name)"
				spec: metrics: [
					{
						name: "\(context.name)-metrics"
						provider: job: spec: {
							template: spec: {
								containers: [
									{
										name:  "test"
										image: parameter.functionalGate.image
										command: ["sh"]
										args: [
											"-c",
											"set -e; echo 'Fetching response...'; RESPONSE=$(wget -qO- http://\(previewService):\(parameter.port)\(parameter.appPath)/ 2>&1); echo 'Response received:'; echo \"$RESPONSE\"; echo ''; echo 'Testing for: \(parameter.functionalGate.extraArgs)'; if echo \"$RESPONSE\" | grep -q '\(parameter.functionalGate.extraArgs)'; then echo 'PASS: Found \(parameter.functionalGate.extraArgs)'; exit 0; else echo 'FAIL: \(parameter.functionalGate.extraArgs) not found'; exit 1; fi",
										]
									},
								]
								restartPolicy: "Never"
							}
							backoffLimit: 0
						}
					},
				]
			}
		}
		if parameter.performanceGate != _|_ {
			"appmod-performance-analysis-template": {
				kind:       "AnalysisTemplate"
				apiVersion: "argoproj.io/v1alpha1"
				metadata: name: "performance-gate-\(context.name)"
				spec: metrics: [
					{
						name: "\(context.name)-metrics"
						provider: job: spec: {
							template: spec: {
								containers: [
									if strings.Contains(context.name, "java") {
										{
											name:  "test"
											image: parameter.performanceGate.image
											command: ["sh"]
											args: [
												"-c",
												"RESULT=$(ab -n 1000 -c 10 http://\(previewService):\(parameter.port)\(parameter.appPath)/ 2>/dev/null | grep -o 'Time per request:[^[]*' | head -1 | awk '{print int($4)}'); [ $RESULT -lt \(parameter.performanceGate.extraArgs) ] && exit 0 || exit 1",
											]
										}
									},
									if strings.Contains(context.name, "rust") {
										{
											name:  "test"
											image: parameter.performanceGate.image
											command: ["run"]
											args: [
												"run",
												"-t",
												"http://\(previewService):\(parameter.port)",
												"/benchmark.yaml",
											]
											volumeMounts: [{
												name:      "benchmark-config"
												mountPath: "/benchmark.yaml"
												subPath:   "benchmark.yaml"
											}]
										}
									},
								]
								if strings.Contains(context.name, "rust") {
									volumes: [{
										name: "benchmark-config"
										configMap: name: "benchmark-config-\(context.name)"
									}]
								}
								restartPolicy: "Never"
							}
							backoffLimit: 0
						}
					},
				]
			}
		}
		if parameter.performanceGate != _|_ && strings.Contains(context.name, "rust") {
			"benchmark-configmap": {
				apiVersion: "v1"
				kind:       "ConfigMap"
				metadata: name: "benchmark-config-\(context.name)"
				data: {
					"benchmark.yaml": """
						config:
						  target: "http://127.0.0.1:80"
						  phases:
						    - duration: 5
						      arrivalRate: 1
						      rampTo: 10
						      name: Warm up
						    - duration: 10
						      arrivalRate: 10
						      rampTo: 100
						      name: Burn
						    - duration: 10
						      arrivalRate: 100
						      name: End

						  plugins:
						    ensure: {}
						    apdex: {}
						    metrics-by-endpoint: {}
						  apdex:
						    threshold: 100
						  ensure:
						    thresholds:
						      - http.response_time.p99: 6000
						      - http.response_time.p95: 6000

						scenarios:
						  - name: "Navigate Menus"
						    flow:
						      - get:
						          url: "/collection/FRONT_PAGE"
						      - post:
						          url: "/products/"
						          json: "Shirt"
						      - post:
						          url: "/products/"
						          json: "Keyboard"
						"""
				}
			}
		}
		"service-rollout-pdb": {
			apiVersion: "policy/v1"
			kind:       "PodDisruptionBudget"
			metadata: name: context.name
			spec: {
				maxUnavailable: 1
				selector: matchLabels: app: context.name
			}
		}
	}

	#QualityGate: {
		image:     string
		pause:     string
		extraArgs: *"" | string
	}

	#MetricGate: {
		pause: *"1s" | string
		evaluationCriteria:
		[...{
			interval:               *"1s" | string
			count:                  *1 | int
			function?:              "sum" | "avg" | "max" | "min" | "count"
			rateInterval?:          string
			successOrFailCondition: *"success" | "fail"
			metric:                 string
			comparisonType:         *">" | ">=" | "<" | "<=" | "==" | "!="
			threshold:              *0 | number
		}]
	}

	parameter: {
		image:      string
		replicas:   *3 | int
		port:       *80 | int
		targetPort: *8080 | int
		appPath:    *"/" | string
		env?: [...{name: string, value: string}]
		readinessProbe?: {...}
		resources?: {
			requests?: {
				cpu?:    string
				memory?: string
			}
			limits?: {
				cpu?:    string
				memory?: string
			}
		}
		functionalGate?:  #QualityGate
		performanceGate?: #QualityGate
		metrics?:         #MetricGate
	}
}
