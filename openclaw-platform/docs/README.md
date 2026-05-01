# OpenClaw Agent Platform on EKS

A production-grade AI agent platform running on Amazon EKS with hardware-level sandbox isolation via Kata Containers. One sandbox per user, GitOps-managed via ArgoCD, Karpenter-driven node provisioning, persistent per-user workspaces on EFS.

> **No EKS Auto Mode.** System nodegroup (managed, 2× m5.large) + Karpenter for all workload nodes.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Terraform (openclaw-platform/infra/terraform/)          │
│  VPC, EKS cluster, system MNG, Karpenter IAM + SQS,     │
│  Pod Identity (LiteLLM→Bedrock), ArgoCD via addons,     │
│  Packer AMI bake, Bedrock Guardrail, Cognito, ECR, EFS  │
└──────────────────────────────────────────────────────────┘
                         ↓ ArgoCD bootstraps from repo
┌──────────────────────────────────────────────────────────┐
│ GitOps (openclaw-platform/gitops/)                      │
│                                                          │
│  W-1 karpenter (controller via Helm)                    │
│       aws-node-kata, agent-sandbox (Sandbox CRDs)       │
│  W0   karpenter-nodepools (kata-nested + kata-metal)    │
│       kata StorageClass                                  │
│  W1   kata-deploy DaemonSet + kubelet-restart           │
│       monitoring (Prometheus + Grafana)                 │
│  W2   litellm (proxy + pg + Bedrock Guardrail)          │
│  W3   openclaw operator, external-dns, ALB IngressClass │
│  W4   finance-assistant + slack usecases                │
│  W5   finance-assistant-ui (React + Cognito)            │
└──────────────────────────────────────────────────────────┘
```

## Usecases

- **[Finance Assistant](usecases/finance-assistant.md)** — per-user financial reasoning assistant. ALB + Cognito auth, SSE chat, persistent /workspace on EFS.
- **[Slack](usecases/slack.md)** — openclaw agent exposed to Slack via Socket Mode. No public ingress.

## Key design decisions

| # | Decision | Why |
|---|---|---|
| 1 | No EKS Auto Mode | Broke kata cross-node networking in practice |
| 2 | Managed system nodegroup (2× m5.large) | Runs ArgoCD, Karpenter, CoreDNS, system pods |
| 3 | Karpenter v1.9.0 for all workload nodes | Cheap, fast scale-up, spot-aware |
| 4 | Packer-baked kata AMI (Kata 3.27 + QEMU) | Faster cold-start than kata-deploy DS install |
| 5 | Two kata NodePools: nested (c8i/m8i default) + metal (c5.metal fallback) | Nested cheaper & more reliable than metal spot |
| 6 | ArgoCD via `aws-ia/eks-blueprints-addons` | AWS-maintained bootstrap |
| 7 | LiteLLM → Bedrock via Pod Identity | No static IAM keys in cluster |
| 8 | /workspace on EFS (ReadWriteMany, per-user subPath) | User context survives reaper deletion |
| 9 | Adapter sidecar kept | SSE streaming + secret redaction + cold-start bridge (~0 latency) |
| 10 | One sandbox per user via session-router | Strong isolation, predictable blast radius |

## Chat latency

Bedrock → LiteLLM → openclaw gateway → adapter (loopback) → router → ALB → browser. Added latency excluding Bedrock: ~15 ms per token. Streaming is SSE end-to-end.

## Getting started

```bash
cd openclaw-platform
./scripts/install.sh
```

See [architecture.md](architecture.md) for the full detail.
