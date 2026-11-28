# network-flow-monitor

Amazon CloudWatch **Network Flow Monitor** agent on a fleet cluster, as the EKS managed
add-on `aws-network-flow-monitoring-agent` plus the IAM role it publishes with.

Network Flow Monitor reports per-flow TCP health (retransmissions, retransmission
timeouts, round-trip time) between workloads, which is the one signal VPC Flow Logs and
container metrics do not carry: it distinguishes "the network degraded" from "the
application slowed down".

Gate: `enable_network_flow_monitor` (default `false`), registry entry
`network-flow-monitor` in `registry/observability.yaml`.

## What it renders

Two ACK CRs, on the **hub**, in a namespace named after the **target** cluster:

| Wave | Kind | Purpose |
|---|---|---|
| -2 | `iam.services.k8s.aws/Role` | `<cluster>-NetworkFlowMonitorAgentRole`, trusted by `pods.eks.amazonaws.com`, carrying `CloudWatchNetworkFlowMonitorAgentPublishPolicy` |
| -1 | `eks.services.k8s.aws/Addon` | the managed add-on, with an add-on-owned Pod Identity association resolving the role by `roleRef` |

Nothing is rendered **into** the target cluster: EKS installs the agent DaemonSet on
every node itself.

## Why no PodIdentityAssociation CR

`Addon.spec.podIdentityAssociations` makes the association **add-on-owned** — EKS
creates it, picks the add-on's own namespace, and removes it with the add-on. Shipping a
separate `PodIdentityAssociation` CR as well would put two owners on one
`(namespace, serviceAccount)` pair, which is the 409 `ResourceInUseException` failure
mode that `pod_identities` and `ack_pod_identities` are mutually exclusive to avoid.

For the same reason this chart does **not** add an identity to `ack-pod-identity`.

## Values that matter

| Value | Default | Note |
|---|---|---|
| `addon.version` | `''` | Empty = EKS picks the version compatible with the cluster. **Not pinned on purpose**: the default build differs per region, so a hard pin breaks every cluster whose region has not received it. Pin from an overlay when needed. |
| `addon.serviceAccount` | `aws-network-flow-monitor-agent-service-account` | Read from `describe-addon-configuration`, not guessed. A mismatch produces an association no pod uses, and the agent silently falls back to the node role. |
| `addon.resolveConflicts` | `OVERWRITE` | Adopts a self-managed or console-installed agent instead of failing on create. |
| `addon.configurationValues` | `{}` | Rendered as the `configurationValues` JSON string. Its documented use is the OpenMetrics endpoint (`OPEN_METRICS`, add-on v1.1.0+) for Prometheus scraping. |

Both CRs carry `adoption-policy: adopt-or-create`, and the Role also
`deletion-policy: retain`, so enabling the gate on a cluster that already has the add-on
adopts it in place, and disabling the gate never deletes a live IAM role.

## Validated on EKS Auto Mode

Installed and removed on a live Auto Mode cluster (k8s 1.37, us-west-2) by driving the
same two AWS calls the CRs above produce — `CreateRole` + `AttachRolePolicy`, then
`CreateAddon` with `--pod-identity-associations`. Results:

| Check | Result |
|---|---|
| Add-on reaches `ACTIVE` | yes, ~30 s, `health.issues: []` |
| Version chosen with `addonVersion` omitted | `v1.1.9-eksbuild.2`, i.e. leaving it empty works |
| Namespace the add-on creates | `amazon-network-flow-monitor` |
| **Runs on an Auto Mode node** | **yes** — agent pod `1/1 Running` on a Bottlerocket `aws-k8s-1.37-standard` node (`compute-type=auto`) |
| Credentials reaching the pod | Pod Identity, `AWS_CONTAINER_CREDENTIALS_FULL_URI=http://169.254.170.23/v1/credentials` |
| Publishing to the ingestion endpoint | `publisher_endpoint` logs `HTTP request complete status=200`, no `AccessDenied` |
| Association ownership | `ownerArn` is the **add-on** ARN, confirming EKS owns it and this chart must not ship its own CR |

The Auto Mode result is not an accident of configuration: the add-on's DaemonSet excludes
only `compute-type NotIn [fargate, hybrid]` and tolerates every taint
(`{operator: Exists}`). It does **not** exclude `auto`, unlike `vpc-cni`, whose exclusion
list is `[fargate, hybrid, auto]`. Sibling agents are less lucky — the EKS node
monitoring agent's DaemonSet [is excluded from Auto Mode nodes by design](https://github.com/aws/containers-roadmap/issues/2872) —
so this was worth proving rather than assuming.

Expect one benign log line on an IPv4-only VPC: the agent logs `ERROR` for an IMDS 404 on
`.../vpc-ipv6-cidr-blocks`, then continues normally (`Loaded VPC CIDRs for NAT
resolution`). It is not a failure, but a workshop participant will see it.

## Scraping it into Prometheus / AMP instead of the console

The add-on can expose an OpenMetrics endpoint (v1.1.0+), which is the route to flow
metrics in Grafana without creating a CloudWatch monitor. It needs **no scrape-config
change**: `observability-aws/files/scraper-config.yaml` already ships a generic
`kubernetes-pods` job that keeps pods annotated `prometheus.io/scrape=true` and
rewrites the target from `prometheus.io/port`, and the add-on schema does expose
`podAnnotations` (confirmed against `describe-addon-configuration`, whose schema is
closed — `additionalProperties: false`). The whole recipe:

```yaml
addon:
  configurationValues:
    env:
      OPEN_METRICS: "on"
      OPEN_METRICS_ADDRESS: 0.0.0.0
      OPEN_METRICS_PORT: 9109
    podAnnotations:
      prometheus.io/scrape: "true"
      prometheus.io/port: "9109"
```

`0.0.0.0` is required rather than lazy: the agent runs with `hostNetwork: true`, so its
pod IP **is** the node IP and the scrape target resolves to `<nodeIP>:9109`. A
`127.0.0.1` bind answers nothing from the collector. The flip side is a port open on the
node's own interfaces, so gate it with a security group or NetworkPolicy admitting only
the scraper.

This does not make the add-on CloudWatch-free. The agent publishes to the Network Flow
Monitor ingestion endpoint regardless — no schema knob disables publishing — so the IAM
role and its publish policy stay required. `env.CUSTOM_INGESTION_ENDPOINT` exists and
redirects that destination, but redirecting is not disabling and its accepted targets
are untested here. What the console adds over the raw agent metrics is the service-side
aggregation: Workload insights / top contributors, and attribution of flows to an AZ, a
VPC, another Region or an AWS service.

## Scope and open points

- **kro-ack only.** The registry selector requires `provider In ["kro-ack"]`. A
  crossplane twin (`eks.aws.upbound.io/Addon`, `iam.aws.upbound.io/Role`) is a
  mechanical port if a crossplane cluster ever needs it.
- **One gap left: ACK adoption.** A second `CreateAddon` returns
  `ResourceInUseException: Addon already exists`, which is exactly what
  `adoption-policy: adopt-or-create` has to absorb — but that the ACK controller resolves
  an existing `Addon` by `(clusterName, name)` **without** `adoption-fields` is still
  unproven, because the validation cluster had no EKS ACK capability. It needs one run on
  a hub. If adoption turns out to need `adoption-fields`, the fix is local to
  `templates/addon.yaml`.
- Kubernetes 1.25+ is required by the add-on, which every cluster in this repo exceeds.

## References

- [Install the EKS AWS Network Flow Monitor Agent add-on](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-NetworkFlowMonitor-agents-kubernetes-eks.html)
- [Configure the add-on for third party monitoring tools](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-NetworkFlowMonitor-agents-kubernetes-eks-third-party.html)
- [ACK `eks.services.k8s.aws/Addon` reference](https://aws-controllers-k8s.github.io/community/reference/eks/v1alpha1/addon/)
