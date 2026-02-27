// Simplified agent ComponentDefinition with blue-green deployment
import "strings"

agent: {
	alias: ""
	annotations: {}
	attributes: workload: definition: {
		apiVersion: "argoproj.io/v1alpha1"
		kind:       "Rollout"
	}
	description: "Declarative agent with blue-green deployment"
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
				"app.kubernetes.io/component": "ai-agent"
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
			selector: matchLabels: {
				"app.kubernetes.io/name": parameter.name
			}
			template: {
				metadata: labels: {
					"app.kubernetes.io/name": parameter.name
				}
				spec: {
					serviceAccountName: parameter.serviceAccount
					containers: [{
						name:  "agent"
						image: parameter.image
						ports: [{
							name:          "a2a"
							containerPort: 8083
							protocol:      "TCP"
						}]
						env: [
							{
								name:  "AGENT_NAME"
								value: parameter.name
							},
							{
								name:  "AGENT_DESCRIPTION"
								value: parameter.description
							},
							{
								name:  "MODEL_ID"
								value: parameter.modelConfig.modelId
							},
							{
								name:  "SYSTEM_PROMPT"
								value: parameter.systemMessage
							},
							{
								name:  "PORT"
								value: "8083"
							},
							{
								name:  "AWS_REGION"
								value: parameter.modelConfig.region
							},
							{
								name:  "LLM_GATEWAY_URL"
								value: parameter.modelConfig.llmGatewayUrl
							},
							{
								name:  "LLM_GATEWAY_API_KEY"
								value: parameter.modelConfig.llmGatewayApiKey
							},
						] + [
							if len(parameter.mcpServers) > 0 {
								{
									name: "MCP_SERVERS"
									value: strings.Join([for s in parameter.mcpServers {
										"http://\(s.name).\(parameter.namespace).svc.cluster.local:\(s.port)"
									}], ",")
								}
							},
							for e in parameter.env {e},
						]
						livenessProbe: {
							httpGet: {
								path: "/health"
								port: 8083
							}
							initialDelaySeconds: 10
							periodSeconds:       30
						}
						readinessProbe: {
							httpGet: {
								path: "/health"
								port: 8083
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
		// Stable service (active)
		stableService: {
			apiVersion: "v1"
			kind:       "Service"
			metadata: {
				name:      parameter.name + "-stable"
				namespace: parameter.namespace
				labels: {
					"app.kubernetes.io/name": parameter.name
				}
			}
			spec: {
				selector: {
					"app.kubernetes.io/name": parameter.name
				}
				ports: [{
					name:        "a2a"
					port:        8083
					targetPort:  8083
					protocol:    "TCP"
					appProtocol: "kgateway.dev/a2a"
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
				labels: {
					"app.kubernetes.io/name": parameter.name
				}
			}
			spec: {
				selector: {
					"app.kubernetes.io/name": parameter.name
				}
				ports: [{
					name:        "a2a"
					port:        8083
					targetPort:  8083
					protocol:    "TCP"
					appProtocol: "kgateway.dev/a2a"
				}]
				type: "ClusterIP"
			}
		}

		// Agent card ConfigMap
		agentCard: {
			apiVersion: "v1"
			kind:       "ConfigMap"
			metadata: {
				name:      parameter.name + "-card"
				namespace: parameter.namespace
				labels: {
					"app.kubernetes.io/name": parameter.name
					"agent.dev/type":         "agent-card"
				}
			}
			data: {
				name:        parameter.name
				description: parameter.description
				model:       parameter.modelConfig.modelId
			}
			if parameter.mcpServers != _|_ && len(parameter.mcpServers) > 0 {
				data: mcpServers: strings.Join([for s in parameter.mcpServers {s.name}], ",")
			}
		}

		// HTTPRoute for AgentGateway registration (optional)
		if parameter.registerWithGateway {
			gatewayRoute: {
				apiVersion: "gateway.networking.k8s.io/v1"
				kind:       "HTTPRoute"
				metadata: {
					name:      parameter.name
					namespace: parameter.namespace
					labels: {
						"app.kubernetes.io/name": parameter.name
					}
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
								value: "/" + parameter.name
							}
						}]
						filters: [{
							type: "URLRewrite"
							urlRewrite: path: {
								type:               "ReplacePrefixMatch"
								replacePrefixMatch: "/"
							}
						}]
						backendRefs: [{
							name:      parameter.name + "-stable"
							port:      8083
							namespace: parameter.namespace
						}]
					}]
				}
			}
		}
	}

	parameter: {
		// Required fields
		name:          string
		namespace:     string
		description:   string
		systemMessage: string

		// Image with default to Strands agent
		image: *"498530348755.dkr.ecr.us-west-2.amazonaws.com/strands-agent:latest" | string

		// Optional fields with defaults
		replicas:       *3 | int
		serviceAccount: *"default" | string

		// Blue-green deployment settings
		autoPromotionEnabled:  *true | bool
		autoPromotionSeconds:  *10 | int
		scaleDownDelaySeconds: *30 | int

		// AgentGateway registration
		registerWithGateway: *true | bool
		gatewayNamespace:    *"agentgateway-system" | string

		// Model configuration
		modelConfig: {
			modelId:          *"claude-sonnet" | string
			region:           *"us-west-2" | string
			llmGatewayUrl:    *"http://litellm-proxy.agentgateway-system.svc.cluster.local:4000" | string
			llmGatewayApiKey: *"sk-1234" | string
		}

		// MCP servers
		mcpServers: *[] | [...{
			name: string
			port: *3000 | int
		}]

		// Additional environment variables
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
	}
}
