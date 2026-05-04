# Architecture

## Cluster layout

- **1 EKS cluster** (`openclaw-eks`, Kubernetes 1.32) in a 3-AZ VPC (`10.0.0.0/16`).
- **Managed system nodegroup** — 2× m5.large. Runs ArgoCD, Karpenter, CoreDNS, EFS CSI, kube-proxy, VPC CNI, Pod Identity agent, monitoring, LiteLLM, session-router, finance-ui.
- **Karpenter** provisions workload nodes on demand. Two NodePools:
  - `kata-nested` — c8i/m8i nested-virt, spot + on-demand (default; cheaper)
  - `kata-metal` — c5.metal / i3.metal / m5.metal on-demand (fallback)
  Both labeled `katacontainers.io/kata-runtime=true`, tainted `kata=true:NoSchedule`.
- **No EKS Auto Mode.** Auto Mode's kata cross-node networking issues were the root cause of the previous incident.

## Waves

| Wave | Apps | What |
|---|---|---|
| -1 | karpenter, aws-node-kata, agent-sandbox | Prereqs: controller, VPC CNI overlay for kata nodes, Sandbox CRDs |
| 0 | karpenter-nodepools, kata StorageClass | NodePools + EC2NodeClass, kata-aware storage class |
| 1 | kata-deploy, monitoring | kata-qemu runtime install + kubelet-restart DS, Prometheus/Grafana |
| 2 | litellm | OpenAI-compat proxy to Bedrock with Guardrails + sitecustomize |
| 3 | openclaw, external-dns, ingressclass-alb | Operator (if any), DNS, ALB IngressClass |
| 4 | finance-assistant-sandbox, slack-sandbox | Sandbox CRs + NetworkPolicies + ConfigMaps + session-router |
| 5 | finance-assistant-ui | React UI + ALB Ingress + Cognito |

ArgoCD reconciles in wave order. Within a wave, Applications sync in parallel.

## Data flow

### Finance Assistant (web UI)

```
Browser ──HTTPS──▶ ALB ──HTTP──▶ finance-ui (Next.js)
                                   │  /api/auth/* → Cognito (direct API)
                                   │  /api/warmup → finance-session-router
                                   │  /api/chat   → finance-session-router (SSE)
                                   ▼
                            finance-session-router
                                   │ hash(sub) → user-suffix
                                   │ kubectl ensure PVC+Sandbox+Service (with retry)
                                   ▼
                       finance-sandbox-<suffix>
                       ┌─────────────────────────┐
                       │ openclaw (:18789)       │
                       │    ▲ loopback           │
                       │ adapter (:18790)        │
                       │    │ SSE               │
                       │    ▼                    │
                       └─────────────────────────┘
                                   │ HTTP :4000
                                   ▼
                            LiteLLM (Pod Identity)
                                   │
                                   ▼
                       Bedrock Guardrail + Claude Haiku 4.5

Auth: Cognito User Pool, direct API (not ALB OIDC). Pre-signup Lambda blocks
non-@amazon.com and auto-confirms amazon emails. Session cookie `fa_session`
is a JWT carrying only {sub, email} (under 1.5KB so Chromium doesn't drop it).

Warmup: finance-ui fires /api/warmup on sign-in success so the per-user Kata
pod is provisioned in the background while the user is deciding what to ask.
Three @amazon.com fences: Cognito pre-signup Lambda, client-side domain
check, server-side check in /api/warmup.

/workspace mounts from EFS subPath=<user-suffix>. Reaper deletes Sandbox
after 30m idle; EFS data persists; next sign-in triggers warmup → Sandbox
re-mounts the same subPath.
```

### Slack

```
Slack (user DM) ──Socket Mode──▶ openclaw-slack-sandbox ──▶ LiteLLM ──▶ Bedrock
                     (outbound WS, no public ingress)
```

## Secrets

| Secret | Source | Used by |
|---|---|---|
| `litellm-secrets` (master/api keys, Guardrail IDs) | Terraform `random_password` + kubernetes_secret | LiteLLM pod, LiteLLM consumers |
| `openclaw-litellm-key` | same api-key as above, projected to tmpfs | Sandbox pods |
| `openclaw-gateway-auth` | Terraform `random_password` | Gateway auth for session-router → sandbox |
| `slack-tokens` | User-created (`kubectl create secret`) | slack sandbox |
| `finance-litellm-key` | Copy of openclaw-litellm-key (ns-scoped) | finance-assistant pods |

Secrets mount as tmpfs files (mode 0400) under `/var/run/openclaw/`. No env vars.

## IAM (Pod Identity)

| Role | Pod | Privileges |
|---|---|---|
| `KarpenterControllerRole-*` | `kube-system/karpenter` | EC2 RunInstances + SQS + DescribeCluster |
| `KarpenterNodeRole-*` | EC2 nodes Karpenter launches | Worker, CNI, ECR read, SSM |
| `openclaw-eks-litellm-bedrock` | `litellm/litellm` | `bedrock:InvokeModel*`, `bedrock:ApplyGuardrail` |
| `openclaw-eks-ebs-csi` | `kube-system/ebs-csi-controller-sa` | EBS CSI (IRSA) |
| `openclaw-eks-efs-csi` | `kube-system/efs-csi-controller-sa` | EFS CSI (IRSA) |

## Storage

- **EBS gp3** for system workloads (ArgoCD, LiteLLM pg, monitoring) via `gp3` StorageClass.
- **EFS** for per-user workspaces via `efs-workspaces` StorageClass with dynamic access points. One PVC per user, `subPath=<user-suffix>`. Survives Sandbox deletion.

## Networking

- VPC CIDR `10.0.0.0/16`, 3 private + 3 public subnets across 3 AZs.
- Karpenter discovers subnets + SG by tag `karpenter.sh/discovery=openclaw-eks`.
- NetworkPolicies restrict sandbox egress to LiteLLM:4000 and kube-dns:53 only.
- ALB Ingress for finance-ui (Cognito-authed).
- EFS security group allows NFS (2049) only from the EKS node SG.

## AMI

Packer bakes `openclaw-kata-*` AMI on first `terraform apply`:
- Base: EKS-optimized AL2023
- Kata Containers 3.27.0 + QEMU + Cloud Hypervisor
- kata configuration at `/etc/kata-containers/configuration-qemu.toml`
- 250 GB gp3 EBS

Subsequent applies reuse the existing AMI (skip bake) unless `force_rebake=true` or install script changes.

## Teardown

```bash
cd openclaw-platform/scripts
./cleanup.sh   # terraform destroy
```
