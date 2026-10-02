# Integration test branch — tracked feature PRs

This is an **integration test branch** (not a release branch). It bundles the fork's
merged history plus the feature PRs under active integration test listed below. It is
disposable: rebuild it from the current PR heads when a PR moves, and never merge it
back to `main`.

## appmod-blueprints — feature PR under test
- **#926** — `peeks-agent`: read-only platform-engineering agent (OAP Strands agent +
  `eks-read` / `gitlab` MCP + chat-ui + autonomous AMP→SNS→SQS incident bridge). This
  branch carries the reviewed state:
  - generic chart (no deployment-prefix / region hardcodes; `REPLACE_CLUSTER_PREFIX` +
    `REPLACE_REGION` tokens injected from cluster-secret annotations),
  - agent uses the OAP base `agent` ComponentDefinition (not a `*-fixed` variant),
  - `eks-read-access` least-privilege IAM policy (eks:ListClusters/DescribeCluster/
    AccessKubernetesApi) attached to the agent role for live cluster discovery,
  - KRO capability RBAC for the AMP incident path (sns/sqs/prometheusservice ACK groups),
  - agent boot ordering (dependsOn the MCP servers).

## Companion OAP branch
- OAP fork branch `integration/peeks-e2e-2b` carries OAP PR
  **awslabs/open-agentic-platform#37** (`eks-read-access` ComponentDefinition + faster
  `langfuse-otel-auth` ExternalSecret self-heal, refreshInterval 1h→1m).

_Keep this list to the feature PRs deliberately under test; the branch also inherits the
fork's full merged history, which is not enumerated here._
