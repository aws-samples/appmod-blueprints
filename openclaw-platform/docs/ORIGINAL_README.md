# EKS Platform for OpenClaw

**Production-grade AI agents with hardware-level sandbox isolation on Amazon EKS.**

Every agent conversation runs inside a Kata Containers QEMU virtual machine on bare-metal EC2. Not just a container — an actual VM with its own kernel. Agents connect to Slack, reason with Claude via AWS Bedrock, and are deployed entirely through GitOps.

![Architecture](generated-diagrams/openclaw-architecture.png)

---

## Why this architecture

### The problem with running AI agents in containers

AI agents execute code, browse the web, read files, and call external APIs. A compromised or misbehaving agent in a standard container can escape to the host kernel, access other workloads' memory, or pivot across the cluster. For production agent deployments, that's not acceptable.

### The solution: hardware VM isolation per agent

This platform runs each OpenClaw agent inside a **Kata Containers QEMU virtual machine** on bare-metal EC2 (`c5.metal` / `m5.metal`). The agent process is isolated at the hardware level — it has its own kernel, its own memory space, and cannot escape to the host regardless of what it executes. The VM boundary is enforced by the CPU, not by Linux namespaces.

This is the same isolation model used by AWS Fargate and AWS Lambda under the hood.

---

## Key design decisions

### 1. Kata Containers on bare-metal, not Fargate or Lambda

Fargate gives you VM isolation but no control over the runtime. Lambda gives you isolation but no persistent state or long-running processes. OpenClaw agents need persistent workspace, long-running sessions, and direct Kubernetes API access for tool use. Kata on bare-metal gives all of that with full control.

**Bare-metal matters**: Kata requires hardware virtualization (VT-x/AMD-V). Nested virtualization on regular EC2 instances adds overhead and instability. `c5.metal` and `m5.metal` give direct hardware access — no hypervisor layer between the VM and the CPU.

### 2. EKS Auto Mode for the control plane

EKS Auto Mode manages Karpenter, VPC CNI, EBS CSI, CoreDNS, and the load balancer controller automatically. The platform team doesn't maintain node AMIs, addon versions, or scaling configuration for the general-purpose workloads. Only the kata bare-metal nodes require explicit management — everything else is hands-off.

### 3. EKS Managed Node Group for kata nodes (not Karpenter)

Karpenter is great for dynamic scaling but adds complexity for bare-metal nodes that need specific instance types and a custom runtime. A managed node group with `c5.metal` / `m5.metal` is simpler, gets automatic AMI updates, and integrates cleanly with EKS addons. The node group is sized conservatively (1 desired, 3 max) — kata VMs are heavyweight by design.

### 4. LiteLLM as the model gateway

Direct Bedrock API calls from agents would require each agent pod to have AWS credentials and know Bedrock's API format. LiteLLM provides an OpenAI-compatible endpoint that:
- Abstracts the model provider (swap Bedrock for OpenAI or Anthropic without changing agent code)
- Centralizes API key management with PostgreSQL persistence
- Applies Bedrock Guardrails transparently to every request
- Exposes Prometheus metrics for observability

### 5. EKS Pod Identity instead of static keys

No IAM user keys, no environment variable secrets for AWS access. EKS Pod Identity binds an IAM role directly to the LiteLLM service account. Credentials are rotated automatically, scoped to the pod, and auditable via CloudTrail. The kata agent pods never touch AWS credentials directly.

### 6. Bedrock Guardrail at the proxy layer

Content filtering and PII anonymization happen at LiteLLM, not in the agent. This means:
- Every model call is filtered regardless of which agent makes it
- PII (email, phone, AWS keys) is anonymized before reaching the model
- Guardrail configuration is centralized and auditable
- Agents can't bypass filtering by calling Bedrock directly (they don't have credentials)

### 7. ArgoCD app-of-apps with sync waves

The platform has strict deployment ordering requirements: CNI must be ready before kata nodes join, kata runtime must be installed before agent pods schedule, LiteLLM must be up before agents start. ArgoCD sync waves enforce this:

```
Wave -1: aws-node-kata (VPC CNI for kata nodes)
Wave  0: kata (StorageClass)
Wave  1: kata-deploy (runtime installer) + monitoring
Wave  2: litellm
Wave  3: openclaw (operator + sandbox)
```

---

## What you get

| Capability | Detail |
|---|---|
| Agent isolation | Kata QEMU VM per agent — hardware boundary, own kernel |
| Model access | Claude Sonnet 4.6, Opus 4, Haiku 4.5 via Bedrock cross-region inference |
| Content safety | Bedrock Guardrail — PII anonymization + content filtering on every request |
| Credentials | EKS Pod Identity — no static keys anywhere |
| Deployment | ArgoCD app-of-apps — full GitOps, sync waves, self-healing |
| Observability | Prometheus + Grafana — LiteLLM request rate, latency, token usage |
| Slack integration | Socket Mode WebSocket — DMs and @mentions, no public endpoint needed |
| Persistence | PostgreSQL for LiteLLM key store, EmptyDir workspace per agent session |

---

## Prerequisites

- AWS CLI configured (`AdministratorAccess` or equivalent)
- Terraform >= 1.7.0
- kubectl
- Bedrock model access enabled in `us-west-2`:
  - `us.anthropic.claude-sonnet-4-6`
  - `us.anthropic.claude-opus-4-20250514-v1:0`
  - `us.anthropic.claude-3-5-haiku-20241022-v1:0`

---

## Deploy

```bash
# 1. Clone and configure
git clone https://github.com/YOUR_ORG/eks-platform-openclaw
cd eks-platform-openclaw

cat > terraform/terraform.tfvars <<EOF
gitops_repo_url = "https://github.com/YOUR_ORG/eks-platform-openclaw"
EOF

# 2. Deploy everything (~15 minutes)
chmod +x scripts/install.sh
./scripts/install.sh

# 3. Set up Slack tokens
kubectl create secret generic slack-tokens \
  --namespace openclaw \
  --from-literal=bot-token=xoxb-YOUR-BOT-TOKEN \
  --from-literal=app-token=xapp-YOUR-APP-TOKEN \
  --from-literal=signing-secret=YOUR-SIGNING-SECRET

# 4. Access ArgoCD
kubectl port-forward -n argocd svc/argo-cd-argocd-server 8080:443
# https://localhost:8080

# 5. Access Grafana
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# http://localhost:3000 (admin / prom-operator)
```

---

## Slack integration

Claw-bot connects to Slack via Socket Mode — no public endpoint or ingress required. Once deployed, you can interact with it directly from any Slack channel or DM.

![Claw-bot in Slack](generated-diagrams/claw-bot-Slack.png)

**How to interact:**
- **DM the bot** — send any message directly to Claw-bot for a private conversation
- **Mention in a channel** — `@Claw-bot <your prompt>` to invoke it in a shared channel
- The bot responds in-thread, keeping channels clean
- The bot runs inside a Kata QEMU VM — hardware-isolated from the host and other cluster workloads

---

## Slack app setup

1. Create a Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable **Socket Mode** → generate an App-Level Token (`xapp-...`)
3. Add Bot Token Scopes: `channels:history`, `channels:read`, `im:history`, `im:read`, `im:write`, `chat:write`, `app_mentions:read`
4. Install to your workspace → copy the Bot Token (`xoxb-...`)
5. Create the secret (step 3 above) — the sandbox connects automatically

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `region` | `us-west-2` | AWS region |
| `project_name` | `openclaw` | Resource name prefix |
| `cluster_version` | `1.32` | Kubernetes version |
| `enable_kata_nodes` | `true` | Deploy bare-metal Kata node group |
| `kata_instance_types` | `["c5.metal","m5.metal"]` | Bare-metal instance types |
| `gitops_repo_url` | — | Git repo ArgoCD watches |
| `bedrock_region` | `us-west-2` | Bedrock inference region |

---

## Project structure

```
terraform/
  eks.tf              # EKS Auto Mode + addons (vpc-cni, kube-proxy, ebs-csi)
  kata.tf             # Kata managed node group + kube-proxy affinity patch
  litellm.tf          # LiteLLM namespace, secrets, API key
  bedrock_guardrail.tf

gitops/
  apps/               # ArgoCD Applications (app-of-apps)
    aws-node-kata.yaml    # VPC CNI for kata nodes (wave -1)
    kata.yaml             # StorageClass (wave 0)
    kata-deploy.yaml      # Kata runtime installer (wave 1)
    litellm.yaml          # LiteLLM proxy (wave 2)
    openclaw.yaml         # OpenClaw operator + sandbox (wave 3)
    monitoring.yaml       # Prometheus + Grafana (wave 1)

  helm/
    kata-deploy/      # kata-deploy DaemonSet + kubelet-restart DaemonSet
    aws-node/         # VPC CNI DaemonSet for non-auto-mode kata nodes
    litellm/          # LiteLLM proxy with sitecustomize.py Bedrock patch
    openclaw/         # OpenClaw operator + Sandbox CRD

scripts/
  install.sh          # Full deploy: terraform + ArgoCD bootstrap
  cleanup.sh          # Full teardown
```

---

## How kata nodes bootstrap

EKS Auto Mode doesn't deploy `aws-node` (VPC CNI) to non-auto-mode nodes. Getting kata nodes to Ready requires a specific sequence:

1. **`vpc-cni` EKS addon** (terraform) — provides CNI before the node group creation times out. A DaemonSet can't solve this because it can't schedule until the node is Ready — a chicken-and-egg that only an EKS-managed addon breaks.

2. **`kube-proxy` affinity patch** (terraform `null_resource`) — by default kube-proxy only targets `eks.amazonaws.com/compute-type=auto` nodes. Kata nodes are a managed node group, not auto-mode. Without kube-proxy, `kata-deploy` can't reach the Kubernetes API to complete installation.

3. **`kata-deploy` DaemonSet** (ArgoCD wave 1) — installs kata-qemu runtime binaries. Targets `katacontainers.io/kata-runtime=true`, a label only applied *after* installation completes, so it never runs on uninitialized nodes.

4. **`kata-kubelet-restart` DaemonSet** (ArgoCD wave 1) — `kata-deploy` restarts containerd during installation, breaking the kubelet's CRI socket connection. This DaemonSet restarts kubelet after installation to reconnect it. Without this, the node goes NotReady ~4 minutes after kata-deploy finishes.

---

## Teardown

```bash
./scripts/cleanup.sh
```

---

## License

MIT
