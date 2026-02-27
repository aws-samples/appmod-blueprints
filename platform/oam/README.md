# OAM Strands Agent Examples

This directory contains OAM (Open Application Model) component definitions and examples for deploying Strands agents with Argo Rollouts on Kubernetes.

## Files

- `kagent-rollout-component.yaml` - ComponentDefinition for Strands agents with Argo Rollouts support
- `agent.cue` - Simplified agent ComponentDefinition with blue-green deployment (CUE format)
- `example-strands-agent.yaml` - Example weather agent with canary deployment
- `example-strands-agent-bluegreen.yaml` - Example assistant agent with blue-green deployment
- `example-strands-agent-gateway.yaml` - Example agent using AgentGateway for LLM access
- `example-agent-simple.yaml` - Example using agent.cue ComponentDefinition
- `example-pdf-agent.yaml` - Example PDF processing agent
- `agentgateway-backend.yaml` - AgentGateway backend configuration for Bedrock
- `agentgateway-httproute.yaml` - HTTP routing configuration
- `register-agent-with-gateway.yaml` - Examples for registering agents with AgentGateway
- `appmod-service.cue` - Full-featured service ComponentDefinition with canary/blue-green support
- `generate-component-from-cue.sh` - Helper script to generate CRD from CUE files
- `vela-cue-commands.md` - Documentation for vela CLI commands

## Important Note About Images

The example files use `tiangolo/uvicorn-gunicorn-fastapi:python3.11` as a placeholder image for testing the Argo Rollouts mechanism. This is NOT a Strands agent image and will not provide actual agent functionality.

To use real Strands agents, you must build and push your own images following the instructions below.

## Prerequisites

1. Kubernetes cluster with:
   - KubeVela installed
   - Argo Rollouts installed
   - AWS Load Balancer Controller (for ALB traffic routing)

2. AWS resources:
   - Amazon Bedrock access with Claude models enabled
   - ECR repository for your Strands agent images
   - IAM roles/service accounts for pod identity

## Building a Strands Agent Image

You can build a Strands agent image using the provided application in `applications/strands/`:

```bash
# Navigate to the Strands application directory
cd applications/strands

# Build for AMD64 (compatible with AWS EKS)
./build.sh

# Or use Podman
./build-podman.sh

# Push to ECR
./build.sh push
# Or with Podman
./build-podman.sh push
```

The build scripts automatically:
- Build for AMD64 architecture
- Detect AWS account ID and region
- Create ECR repository if needed
- Tag and push to ECR

See `applications/strands/README.md` for detailed instructions.

Alternatively, follow the [official Strands EKS deployment guide](https://strandsagents.com/latest/documentation/docs/examples/deploy_to_eks/).

## Setting up Pod Identity for Bedrock

### Option 1: Using LLM Gateway (Recommended)

The LLM Gateway (LiteLLM proxy) provides centralized LLM access with pod identity authentication. The gateway handles authentication to Bedrock, so individual agents don't need AWS credentials.

Benefits:
- No AWS credentials needed in agent pods
- Centralized access control and monitoring
- Simplified agent deployment
- Support for multiple LLM providers

The agent.cue ComponentDefinition uses LLM Gateway by default:

```yaml
modelConfig:
  modelId: claude-sonnet
  llmGatewayUrl: http://litellm-proxy.agentgateway-system.svc.cluster.local:4000
  llmGatewayApiKey: sk-1234
```

See `example-agent-simple.yaml` for a complete example.

### Option 2: Direct Bedrock Access with Pod Identity

If not using LLM Gateway, create IAM policy and pod identity association for direct Bedrock access:

```bash
# Create Bedrock policy
cat > bedrock-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam create-policy \
  --policy-name strands-agents-bedrock-policy \
  --policy-document file://bedrock-policy.json

# Create pod identity association
eksctl create podidentityassociation \
  --cluster your-cluster-name \
  --namespace kagent \
  --service-account-name weather-agent-sa \
  --permission-policy-arns arn:aws:iam::${AWS_ACCOUNT_ID}:policy/strands-agents-bedrock-policy \
  --role-name eks-strands-weather-agent
```

## Deploying an Agent

### Install the ComponentDefinition

```bash
kubectl apply -f kagent-rollout-component.yaml
```

### Deploy a Canary Agent

```bash
# Update the image in example-strands-agent.yaml to your ECR image
kubectl apply -f example-strands-agent.yaml
```

This creates:
- A Rollout with canary deployment strategy
- Two services: `weather-agent-stable` and `weather-agent-canary`
- An agent card ConfigMap for discovery

### Deploy a Blue-Green Agent

```bash
kubectl apply -f example-strands-agent-bluegreen.yaml
```

This creates:
- A Rollout with blue-green deployment strategy
- Two services: `assistant-agent-stable` and `assistant-agent-preview`
- Manual promotion control

## Monitoring Rollouts

```bash
# Watch rollout progress
kubectl argo rollouts get rollout weather-agent -n kagent --watch

# Promote a canary deployment
kubectl argo rollouts promote weather-agent -n kagent

# Abort a rollout
kubectl argo rollouts abort weather-agent -n kagent

# Restart a rollout
kubectl argo rollouts restart weather-agent -n kagent
```

## Registering Agents with AgentGateway

AgentGateway uses Kubernetes Gateway API to route requests to agents. 

### Automatic Registration (Default)

When using the `agent.cue` ComponentDefinition, agents are automatically registered with AgentGateway by default. The component creates an HTTPRoute that routes traffic from the gateway to your agent's stable service.

```yaml
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: my-assistant
spec:
  components:
    - name: assistant
      type: agent
      properties:
        name: assistant
        namespace: agents
        # ... other properties ...
        
        # Gateway registration (enabled by default)
        registerWithGateway: true  # Default: true
```

This automatically creates:
- Service with `appProtocol: kgateway.dev/a2a` annotation
- HTTPRoute pointing to `agentgateway-proxy`
- Routes all traffic (/) to the agent's stable service

### Manual Registration

To disable automatic registration and create custom routes:

```yaml
properties:
  registerWithGateway: false  # Disable auto-registration
```

Then create your own HTTPRoute for custom routing (path-based, hostname-based, etc.):

```yaml
# Custom HTTPRoute for path-based routing
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: custom-agent-routes
  namespace: agents
spec:
  parentRefs:
  - name: agentgateway-proxy
    namespace: agentgateway-system
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /assistant
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /
    backendRefs:
    - name: assistant-agent-stable
      port: 8083
```

See `register-agent-with-gateway.yaml` for more custom routing examples.

### Access Registered Agents

Once registered, agents are accessible through the gateway:

```bash
# Get gateway endpoint
GATEWAY_URL=$(kubectl get svc -n agentgateway-system agentgateway-proxy -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Call agent through gateway (automatic registration)
curl http://${GATEWAY_URL}/.well-known/agent.json
curl -X POST http://${GATEWAY_URL}/message \
  -H 'Content-Type: application/json' \
  -d '{"text": "Hello, assistant!"}'

# With custom path-based routing
curl http://${GATEWAY_URL}/assistant/.well-known/agent.json
```

## Testing the Agent

### Port-forward to test locally

```bash
kubectl port-forward -n kagent svc/weather-agent-stable 8083:8083
```

### Test A2A endpoint

```bash
# Get agent card
curl http://localhost:8083/.well-known/agent.json

# Send a request (adjust based on your agent's API)
curl -X POST http://localhost:8083/invoke \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "What is the weather in Seattle?"}'
```

## Customizing Deployment Strategies

### Canary with ALB Traffic Routing

```yaml
rolloutStrategy:
  canary:
    steps:
      - setWeight: 20
      - pause: {duration: 5m}
      - setWeight: 50
      - pause: {duration: 5m}
    trafficRouting:
      alb:
        ingress: weather-agent-ingress
        rootService: weather-agent-stable
        servicePort: 8083
    dynamicStableScale: true
```

### Canary with Istio

```yaml
rolloutStrategy:
  canary:
    steps:
      - setWeight: 25
      - pause: {duration: 2m}
    trafficRouting:
      istio:
        virtualService:
          name: weather-agent-vsvc
          routes:
            - primary
```

### Blue-Green with Auto-Promotion

```yaml
rolloutStrategy:
  blueGreen:
    autoPromotionEnabled: true
    scaleDownDelaySeconds: 30
```

## Troubleshooting

### Check Rollout status

```bash
kubectl describe rollout weather-agent -n kagent
```

### Check pod logs

```bash
kubectl logs -n kagent -l kagent.dev/agent=weather-agent
```

### Verify services

```bash
kubectl get svc -n kagent -l kagent.dev/agent=weather-agent
```

### Check agent card

```bash
kubectl get configmap -n kagent weather-agent-card -o yaml
```

## References

- [Strands Agents Documentation](https://strandsagents.com/latest/documentation/)
- [Argo Rollouts Documentation](https://argo-rollouts.readthedocs.io/)
- [KubeVela OAM Specification](https://kubevela.io/docs/)
- [A2A Protocol Specification](https://github.com/aws/agent-to-agent-protocol)
