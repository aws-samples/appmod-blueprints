# Platform Documentation

The platform is bootstrapped through the root `Taskfile.yaml`, which delegates to a pluggable
**cluster provider** (`kind-crossplane`, `kind-kro-ack`, `terraform`, or `byoc`) selected via
`clusterProvider` in `config.local.yaml`. After the hub cluster is created and `root-appset.yaml`
is applied, ArgoCD takes over and the platform is fully self-managing via GitOps.

> The previous CNOE-style install flow (`platform/infra/terraform/setup-environments.sh`) has been
> removed. Use `task install` / `task status` / `task destroy` instead.

## Getting started

- [Root README](../../README.md) — quick start, workshop bootstrap, and platform URLs/credentials
- [Cluster Providers](../../cluster-providers/README.md) — the provider model, the provider contract, and how to add a provider
- [GitOps Platform](../../gitops/README.md) — ArgoCD ApplicationSets, addon registry, overlays, and fleet management

## Architecture and operations

- [GitOps Bridge Architecture](gitops-bridge-architecture.md) — how cluster metadata and addon enablement flow into cluster secrets
- [Spoke Cluster Lifecycle](cluster-lifecycle.md) — creating, enabling, and safely deleting spoke clusters
- [Hub Networking](HUB_NETWORKING.md)
- [ACK Pod Identity Design](ack-pod-identity-design.md)
- [Multi-Cluster Auth](MULTI_CLUSTER_AUTH.md) — and the [Consumer Guide](MULTI_CLUSTER_AUTH_CONSUMER_GUIDE.md)
- [EKS Capabilities: ArgoCD Setup](../EKS-Capabilities-ArgoCD-Setup.md) and [KRO/ACK Setup](../EKS-Capabilities-KRO-ACK-Setup.md)

## Troubleshooting

- [Troubleshooting guide](../Troubleshoot.md)
