# MCP Gateway Operator - GitOps Addon

Deploys the MCP Gateway Operator on EKS via Argo CD with all prerequisites provisioned declaratively.

## What Gets Deployed

- **AgentCore Gateway** (Crossplane) — creates the Bedrock AgentCore MCP gateway + IAM role
- **OAuth2 Credential Provider** (Crossplane) — registers Keycloak as the outbound OAuth2 provider
- **ExternalSecret** — pulls Keycloak client credentials from the `keycloak-clients` secret
- **Pod Identity** (ACK) — IAM role + policy + PodIdentityAssociation for the operator
- **Operator** — Deployment + ServiceAccount + ClusterRole/Binding
- **CRD** — `mcpservers.mcpgateway.bedrock.aws` (auto-installed from `crds/`)
- **MCPServer CRs** — optional, defined in `values.yaml` under `mcpServers`

## Prerequisites

- ACK controllers for IAM and EKS (for pod identity)
- Crossplane AWS provider with `bedrockagentcore` support (for gateway + OAuth2 provider)
- Keycloak with the `agentcore-gateway` client configured (added to the keycloak config job)
- External Secrets Operator with the `keycloak` ClusterSecretStore

## Modes

### Create gateway (default)

The chart creates the AgentCore gateway via Crossplane. Set `gatewayId` on each MCPServer CR
after the gateway is provisioned, or pass `aws.gatewayId` globally once known:

```yaml
agentcoreGateway:
  create: true    # default

# Option A: set globally after gateway is created
aws:
  gatewayId: "gw-abc123"

# Option B: set per MCPServer CR
mcpServers:
  - name: my-server
    gatewayId: "gw-abc123"
    endpoint: https://mcp-server.example.com
    oauthProviderArn: arn:aws:bedrock-agentcore:us-west-2:123456789012:token-vault/default/oauth2credentialprovider/my-provider
    oauthScopes: [openid]
```

### Use existing gateway

Skip gateway creation and point to an existing one:

```yaml
agentcoreGateway:
  create: false

aws:
  gatewayId: "gw-existing-id"
```

## Configuration

Most values are auto-injected via `addons.yaml` from Argo CD cluster secret annotations:

| Value | Source |
|---|---|
| `aws.region` | `aws_region` annotation |
| `podIdentity.clusterName` | `aws_cluster_name` annotation |
| `podIdentity.accountId` | `aws_account_id` annotation |
| `oauth2Provider.discoveryUrl` | `ingress_domain_name` annotation |

## Sync-Wave Ordering

```
-5  ExternalSecret (Keycloak OIDC credentials) + Gateway IAM Role
-4  AgentCore Gateway + OAuth2 Credential Provider (Crossplane)
-3  Operator IAM Policy (ACK)
-2  Operator IAM Role (ACK)
-1  PodIdentityAssociation (ACK)
 0  Operator Deployment + RBAC + CRD + MCPServers
```

## Registering in addons.yaml

Already added to `gitops/agentic/addons/default/addons.yaml`. Label your cluster secret:

```bash
kubectl label secret <cluster-secret> -n argocd enable_mcp_gateway_operator=true
```

## Verification

```bash
# Check Crossplane resources
kubectl get gateway.bedrockagentcore.aws.upbound.io -n mcp-gateway-operator-system
kubectl get oauth2credentialprovider.bedrockagentcore.aws.upbound.io -n mcp-gateway-operator-system

# Check operator
kubectl get pods -n mcp-gateway-operator-system

# Check MCPServer status
kubectl get mcpservers -A
```
