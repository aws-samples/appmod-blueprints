// MCP Server ComponentDefinition with blue-green deployment and agentgateway registration

"mcp-server": {
	alias: ""
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "argoproj.io/v1alpha1"
		kind:       "Rollout"
	}
	description: "MCP server with blue-green deployment and agentgateway registration"
	labels: {}
	type: "component"
}

template: {
	output: {
		apiVersion: "argoproj.io/v1alpha1"
		kind:       "Rollout"
		metadata: {
			name:      parameter.name
			namespace: parameter.namespace
			labels: {
				"app.kubernetes.io/name":      parameter.name
				"app.kubernetes.io/component": "mcp-server"
			}
		}
		spec: {
			replicas: parameter.replicas
			strategy: blueGreen: {
				activeService:        parameter.name + "-stable"
				previewService:       parameter.name + "-preview"
				autoPromotionEnabled: parameter.autoPromotionEnabled
				if parameter.autoPromotionSeconds != _|_ {
					autoPromotionSeconds: parameter.autoPromotionSeconds
				}
				if parameter.scaleDownDelaySeconds != _|_ {
					scaleDownDelaySeconds: parameter.scaleDownDelaySeconds
				}
			}
			selector: matchLabels: "app.kubernetes.io/name": parameter.name
			template: {
				metadata: labels: "app.kubernetes.io/name": parameter.name
				spec: {
					serviceAccountName: parameter.serviceAccount
					containers: [{
						name:  "mcp-server"
						image: parameter.image
						ports: [{
							name:          "mcp"
							containerPort: parameter.containerPort
							protocol:      "TCP"
						}]
						env: [for e in parameter.env {e}]
						livenessProbe: {
							if parameter.healthPath != _|_ {
								httpGet: {
									path: parameter.healthPath
									port: parameter.containerPort
								}
							}
							if parameter.healthPath == _|_ {
								tcpSocket: port: parameter.containerPort
							}
							initialDelaySeconds: 10
							periodSeconds:       30
						}
						readinessProbe: {
							if parameter.healthPath != _|_ {
								httpGet: {
									path: parameter.healthPath
									port: parameter.containerPort
								}
							}
							if parameter.healthPath == _|_ {
								tcpSocket: port: parameter.containerPort
							}
							initialDelaySeconds: 5
							periodSeconds:       10
						}
						if parameter.resources != _|_ {
							resources: parameter.resources
						}
					}]
				}
			}
		}
	}

	outputs: {
		// Stable service (active) — used by AgentgatewayBackend
		stableService: {
			apiVersion: "v1"
			kind:       "Service"
			metadata: {
				name:      parameter.name + "-stable"
				namespace: parameter.namespace
				labels: "app.kubernetes.io/name": parameter.name
			}
			spec: {
				selector: "app.kubernetes.io/name": parameter.name
				ports: [{
					name:        "mcp"
					port:        80
					targetPort:  parameter.containerPort
					protocol:    "TCP"
					appProtocol: "agentgateway.dev/mcp"
				}]
				type: "ClusterIP"
			}
		}

		// Preview service (for blue-green)
		previewService: {
			apiVersion: "v1"
			kind:       "Service"
			metadata: {
				name:      parameter.name + "-preview"
				namespace: parameter.namespace
				labels: "app.kubernetes.io/name": parameter.name
			}
			spec: {
				selector: "app.kubernetes.io/name": parameter.name
				ports: [{
					name:        "mcp"
					port:        80
					targetPort:  parameter.containerPort
					protocol:    "TCP"
					appProtocol: "agentgateway.dev/mcp"
				}]
				type: "ClusterIP"
			}
		}

		// AgentgatewayBackend — static target pointing to stable service
		mcpBackend: {
			apiVersion: "agentgateway.dev/v1alpha1"
			kind:       "AgentgatewayBackend"
			metadata: {
				name:      parameter.name + "-backend"
				namespace: parameter.namespace
				labels: "app.kubernetes.io/name": parameter.name
			}
			spec: mcp: targets: [{
				name: parameter.name + "-target"
				static: {
					host:     parameter.name + "-stable." + parameter.namespace + ".svc.cluster.local"
					port:     80
					protocol: parameter.mcpProtocol
				}
			}]
		}

		// HTTPRoute — registers MCP server with the gateway at /mcp/<name>
		if parameter.registerWithGateway {
			gatewayRoute: {
				apiVersion: "gateway.networking.k8s.io/v1"
				kind:       "HTTPRoute"
				metadata: {
					name:      parameter.name
					namespace: parameter.namespace
					labels: "app.kubernetes.io/name": parameter.name
				}
				spec: {
					parentRefs: [{
						name:      "agentgateway-proxy"
						namespace: parameter.gatewayNamespace
					}]
					rules: [{
						matches: [{
							path: {
								type:  "PathPrefix"
								value: "/mcp/" + parameter.name
							}
						}]
						backendRefs: [{
							group: "agentgateway.dev"
							kind:  "AgentgatewayBackend"
							name:  parameter.name + "-backend"
						}]
					}]
				}
			}
		}

		// Optional: AgentgatewayPolicy for tool-level authorization
		if parameter.authPolicy != _|_ && len(parameter.authPolicy.matchExpressions) > 0 {
			toolAccessPolicy: {
				apiVersion: "agentgateway.dev/v1alpha1"
				kind:       "AgentgatewayPolicy"
				metadata: {
					name:      parameter.name + "-tool-access"
					namespace: parameter.namespace
					labels: "app.kubernetes.io/name": parameter.name
				}
				spec: {
					targetRefs: [{
						group: "agentgateway.dev"
						kind:  "AgentgatewayBackend"
						name:  parameter.name + "-backend"
					}]
					backend: mcp: authorization: {
						action: parameter.authPolicy.action
						policy: matchExpressions: parameter.authPolicy.matchExpressions
					}
				}
			}
		}
	}

	parameter: {
		// Required fields
		name:        string
		namespace:   string
		description: string
		image:       string

		// Container port — FastMCP default is 8000
		containerPort: *8000 | int

		// Health check path — if set, uses HTTP GET probe; if omitted, uses TCP socket
		healthPath?: string

		// MCP protocol
		mcpProtocol: *"StreamableHTTP" | "SSE"

		// Optional fields with defaults
		replicas:       *1 | int
		serviceAccount: *"default" | string

		// Blue-green deployment settings
		autoPromotionEnabled:  *true | bool
		autoPromotionSeconds:  *10 | int
		scaleDownDelaySeconds: *30 | int

		// AgentGateway registration
		registerWithGateway: *true | bool
		gatewayNamespace:    *"agentgateway-system" | string

		// Environment variables
		env: *[] | [...{
			name:  string
			value: string
		}]

		// Resource limits
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

		// Tool-level authorization policy (CEL-based)
		authPolicy?: {
			action:           *"Allow" | "Deny"
			matchExpressions: [...string]
		}
	}
}
