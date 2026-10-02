# eks-mcp

Packages the upstream **[awslabs eks-mcp-server](https://github.com/awslabs/mcp)**
(a stdio MCP server) behind **[supergateway](https://github.com/supercorp-ai/supergateway)**
so an AgentGateway can reach it over streamable-HTTP. Started **read-only**
(`--allow-sensitive-data-access --auth-mode iam`, no `--allow-write`); AWS auth
comes from the pod's IAM identity (EKS Pod Identity / IRSA).

## Transport: run STATEFUL

Unlike a self-contained FastMCP server, supergateway wrapping a **stdio** server
must run **stateful** (`--stateful` + gateway backend `sessionRouting: Stateful`):
the wrapped process is kept warm and requests are pinned to it by session. In
stateless mode each request spawns a fresh process that never received
`initialize`, so `tools/list` fails with "error reading a body from connection".

## Pins

- `supergateway@4.0.0`
- `awslabs.eks-mcp-server==0.2.1`
