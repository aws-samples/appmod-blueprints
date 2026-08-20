---
name: eks-recon
description: "EKS cluster reconnaissance and environment discovery. Detects compute strategy (Karpenter, MNG, Auto Mode, Fargate), IaC tooling (Terraform, CloudFormation, CDK, eksctl), CI/CD pipelines (GitHub Actions, GitLab, ArgoCD, Flux), add-on inventory, networking, security posture, and observability. Use this skill whenever someone asks about their EKS cluster, wants to understand their setup, is planning an upgrade or migration, needs cluster context for any reason, asks what version am I running, mentions wanting to review or document their cluster, or is about to make any EKS-related decision - even if they don't explicitly say reconnaissance or discovery. When in doubt about cluster state, run recon first. Skip for upgrade readiness scoring or deprecated API checks (eks-upgrade-check), operational audits with GREEN/AMBER/RED ratings (eks-operation-review), and architecture design documents or Mermaid diagrams (eks-design)."
---

# EKS Reconnaissance

Discover everything about an EKS cluster environment. Run this skill to gather comprehensive cluster context before making any decisions, changes, or recommendations.

## When to Use This Skill

**Run this skill when the user:**
- Asks about their EKS cluster ("what's my cluster running?", "tell me about my setup")
- Plans an upgrade, migration, or architecture change
- Needs cluster context before any EKS-related decision
- Wants to document or review their cluster state
- Asks questions like "what version am I on?" or "am I using Karpenter?"
- Is about to modify their cluster (recon first to understand current state)

**Also trigger this skill when:**
- User mentions an EKS cluster name and seems to need context
- Another workflow needs cluster information as input
- You need to understand the cluster before giving recommendations

**Do NOT use this skill for:**
- **Upgrade readiness scoring or deprecated API checks** — questions like "score my upgrade readiness", "are there deprecated APIs blocking my upgrade", "can I safely upgrade to 1.33", "readiness score", or "breaking changes that would block a version bump" belong to `eks-upgrade-check`. Recon discovers *what version you're on*; it does NOT assess whether you're *ready* to move to the next version.
- **Operational audits with maturity ratings** — questions like "run an operational excellence audit", "rate each area GREEN/AMBER/RED", or "audit my cluster's operational posture" belong to `eks-operation-review`. Recon inventories what exists; it does NOT score operational maturity or produce rated assessments.
- **Architecture design documents or Mermaid diagrams** — questions like "create a security architecture document", "generate Mermaid diagrams for our EKS cluster", or "design document" belong to `eks-design`. Recon discovers current state; it does NOT produce design artifacts or architectural diagrams.
- Creating or modifying cluster resources (this is read-only)
- Troubleshooting specific issues (use `eks-best-practices`)
- Learning about EKS concepts (use `eks-best-practices`)

## Prerequisites

### MCP Server (Preferred)

This skill works best with the **EKS MCP Server** configured. Check if MCP tools are available:

```
If tools like `list_eks_resources`, `describe_eks_resource`, `list_k8s_resources` are available:
  -> MCP Mode: Use MCP tools (pre-authorized, richer output)
  
If MCP tools are NOT available:
  -> CLI Mode: Fall back to AWS CLI + kubectl (requires explicit permission)
```

**MCP Mode benefits:**
- Pre-authorized read-only operations (no permission prompts)
- Richer output with better formatting
- Single tool call instead of piped commands

**CLI Mode limitations:**
- Requires user permission for each command
- May need kubeconfig setup
- Some detection patterns are less reliable

### Required for CLI Mode

| Tool | Required For |
|------|-------------|
| `aws` CLI | Cluster-level detection (describe-cluster, list-nodegroups, list-addons) |
| `kubectl` | K8s resource detection (deployments, CRDs, service accounts) |
| `helm` | Helm release inventory (optional) |

### MCP Troubleshooting

**401 Unauthorized on K8s API calls** (`list_k8s_resources`, `read_k8s_resource`):

The MCP server can access EKS APIs (clusters, nodegroups, addons) but may lack Kubernetes API access. This happens when the MCP server's IAM role doesn't have an EKS access entry.

**Solutions (choose one):**

1. **Grant MCP access**: Create an EKS access entry for the MCP server's IAM role.

   **Surface these commands to the user — do NOT execute them. These are persistent IAM writes and violate the read-only contract of this skill.**

   ```bash
   aws eks create-access-entry \
     --cluster-name <cluster> \
     --region <region> \
     --principal-arn <mcp-server-role-arn> \
     --type STANDARD
   aws eks associate-access-policy \
     --cluster-name <cluster> \
     --region <region> \
     --principal-arn <mcp-server-role-arn> \
     --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy \
     --access-scope type=cluster
   ```

   If the user confirms and has permission, they can run these themselves out-of-band.

2. **Fall back to kubectl**: If user has local kubectl access, use CLI commands instead:
   > "MCP K8s access returned 401. I'll use kubectl instead if you have it configured locally."

**Empty results from EKS API calls**:
- Verify cluster name and region are correct
- Check if the cluster exists: `aws eks list-clusters --region <region>`

---

## Reconnaissance Modes

| Mode | When to Use | What Happens |
|------|-------------|--------------|
| **Full Recon** | First engagement with cluster | Runs all modules, generates complete report |
| **Selective Recon** | Know what you need | Run specific modules (e.g., compute + iac) |
| **Targeted Query** | Quick answer | "Is this cluster using Karpenter?" |

### How to Invoke

**Full reconnaissance:**
> "Run EKS reconnaissance on cluster `my-cluster` in `us-west-2`"

**Selective reconnaissance:**
> "Run EKS recon but only check compute and IaC"

**Targeted query:**
> "What IaC tool manages cluster `my-cluster`?"

---

## Modules and Reference Loading

Load only the references needed for the user's request — this keeps context focused. `references/cluster-basics.md` is **always loaded first** by every module; it provides the shared cluster context all other modules depend on. For targeted queries, load only the matching row(s); for full recon, load all references in parallel. When uncertain, ask the user or default to full recon.

| Module | Intent / when to use | Reference file | Agent file |
|--------|----------------------|----------------|------------|
| Cluster Basics | Always loaded first by every module (name, region, version, platform version, endpoint) | [cluster-basics.md](references/cluster-basics.md) | — |
| Compute | Karpenter, nodes, scaling, Auto Mode, node groups, Fargate, self-managed | [compute.md](references/compute.md) | [compute-recon.md](agents/compute-recon.md) |
| Networking | VPC, ingress, CNI, service mesh, load balancer, connectivity | [networking.md](references/networking.md) | [networking-recon.md](agents/networking-recon.md) |
| Security | IAM, IRSA, Pod Identity, RBAC, policies, encryption, secrets, webhooks | [security.md](references/security.md) | [security-recon.md](agents/security-recon.md) |
| Add-ons | EKS-managed add-ons, Helm releases, plugins, "what's installed?" | [addons.md](references/addons.md) | [addons-recon.md](agents/addons-recon.md) |
| Observability | Logging, metrics, monitoring, Container Insights, Prometheus | [observability.md](references/observability.md) | [observability-recon.md](agents/observability-recon.md) |
| Workloads | Deployments, pods, services, ingresses, "what's running?" | [workloads.md](references/workloads.md) | [workloads-recon.md](agents/workloads-recon.md) |
| Storage | PVCs, EBS, EFS, StorageClasses, CSI drivers, volumes, snapshots | [storage.md](references/storage.md) | [storage-recon.md](agents/storage-recon.md) |
| IaC | Terraform, CloudFormation, CDK, eksctl, Pulumi, "how is it managed?" | [iac.md](references/iac.md) | [iac-recon.md](agents/iac-recon.md) |
| CI/CD | GitHub Actions, GitLab CI, Jenkins, ArgoCD, Flux, GitOps, pipelines | [cicd.md](references/cicd.md) | [cicd-recon.md](agents/cicd-recon.md) |

---

## Quick Detection Reference

### MCP Commands (Preferred)

| Detection | MCP Tool |
|-----------|----------|
| Cluster info | `describe_eks_resource(resource_type="cluster", cluster_name="<name>")` |
| Node groups | `list_eks_resources(resource_type="nodegroup", cluster_name="<name>")` |
| EKS add-ons | `list_eks_resources(resource_type="addon", cluster_name="<name>")` |
| Karpenter | `list_k8s_resources(cluster_name="<name>", kind="NodePool", api_version="karpenter.sh/v1")` |
| Deployments | `list_k8s_resources(cluster_name="<name>", kind="Deployment", api_version="apps/v1")` |
| VPC config | `get_eks_vpc_config(cluster_name="<name>")` |
| Insights | `get_eks_insights(cluster_name="<name>")` |

### CLI Fallbacks

| Detection | CLI Command |
|-----------|-------------|
| Cluster info | `aws eks describe-cluster --name <name> --region <region>` |
| Node groups | `aws eks list-nodegroups --cluster-name <name> --region <region>` |
| EKS add-ons | `aws eks list-addons --cluster-name <name> --region <region>` |
| Fargate profiles | `aws eks list-fargate-profiles --cluster-name <name> --region <region>` |
| Auto Mode | `aws eks describe-cluster --name <name> --region <region> --query 'cluster.computeConfig'` |
| Karpenter | `kubectl get nodepools.karpenter.sh 2>/dev/null` |
| Helm releases | `helm list -A` |

---

## Running Reconnaissance

> **IMPORTANT: Load Reference Files**
> 
> Before running each module, you MUST read its reference file (e.g., `references/compute.md`).
> References contain:
> - Detection order and rationale (why check Auto Mode before Karpenter)
> - Edge cases and how to handle them
> - CLI fallback commands when MCP fails
> - Output schema for structured reporting
> 
> Skipping references produces shallow results. The main skill provides orchestration;
> the references provide detection intelligence.

### Step 1: Gather Prerequisites

```
Required:
- Cluster name (or auto-discover — see below)
- AWS region (or detect from context/kubeconfig/CLI)

Optional:
- Specific modules to run (default: all)
- Output file path (default: .eks-recon-report.yaml)
```

**Auto-discovery when cluster name is not explicit:**

When the user says "my cluster", "current cluster", or does not name a specific cluster, discover it:

1. `kubectl config current-context` — if set, extract cluster name from the context ARN
2. If no kubeconfig context, try **AWS CLI directly** (credentials may come from `~/.aws/` config files, instance profile, or env vars — don't assume env vars are the only source):
   ```bash
   aws sts get-caller-identity  # verify we have working AWS access
   aws eks list-clusters --region ${AWS_DEFAULT_REGION:-us-west-2}
   ```
3. If exactly one cluster is found, use it. If multiple clusters across regions, try common regions (us-west-2, us-east-1, the region in any ARN visible in kubeconfig).
4. Only ask the user to specify a cluster if discovery yields multiple candidates and the prompt is ambiguous.

**IMPORTANT:** Never give up after checking only environment variables. AWS credentials can come from `~/.aws/credentials`, `~/.aws/config`, instance metadata, or ECS task roles — none of which appear in `env | grep AWS_`. Always try `aws sts get-caller-identity` before concluding credentials are unavailable.

### Step 2: Check MCP Availability

If MCP tools are available, use them. Otherwise, inform the user:

> "EKS MCP Server not detected. I'll use CLI commands instead, which will require your permission for each command. For a smoother experience, consider setting up the EKS MCP Server."

### Step 3: Run Selected Modules

Determine which modules to run based on user intent (see [Modules and Reference Loading](#modules-and-reference-loading)).

For each selected module:
1. **Load the reference file** (e.g., `references/compute.md`) - REQUIRED
   - For targeted queries: load only the required reference(s) per decision matrix
   - For full recon: load all references in parallel
2. Run detection commands following the reference's guidance:
   - Try MCP tool first
   - If MCP returns error (401, empty), fall back to CLI from reference
   - If CLI unavailable, note the limitation in report
3. Collect output into report section using the reference's output schema

### Step 4: Generate Report

Write report to `.eks-recon-report.yaml` and present summary:

```yaml
# EKS Reconnaissance Report
# Generated: 2026-04-22T14:30:00Z
# Cluster: my-cluster
# Region: us-west-2
# Modules: cluster-basics, compute, iac, cicd, addons

cluster:
  name: my-cluster
  region: us-west-2
  version: "1.31"
  platform_version: eks.5
  endpoint: https://<cluster-id>.gr7.us-west-2.eks.amazonaws.com
  arn: arn:aws:eks:us-west-2:<account-id>:cluster/my-cluster
  status: ACTIVE
  created_at: "2024-09-10T12:00:00Z"

compute:
  strategy: Karpenter
  auto_mode:
    enabled: false
  karpenter:
    detected: true
    version: "1.0.5"
    nodepools: 2
    nodepool_names: [default, gpu]
  mng:
    detected: true
    count: 1
    groups:
      - name: system
        status: ACTIVE
        instance_types: [m6i.large]
        desired_size: 2
  fargate:
    detected: false
    profiles: 0
  self_managed:
    detected: false
    node_count: 0

iac:
  tool: Terraform
  confidence: high
  evidence:
    type: workspace_files
    details: "./infrastructure/eks/main.tf contains aws_eks_cluster"

cicd:
  workspace:
    github_actions:
      detected: true
      workflows: [.github/workflows/deploy.yml]
    gitlab_ci:
      detected: false
    jenkins:
      detected: false
      jenkinsfile: false
    other: null
  gitops:
    argocd:
      detected: true
      namespace: argocd
      applications: 12
      app_projects: 3
    flux:
      detected: false
      namespace: null
      kustomizations: 0
      helm_releases: 0
      git_repositories: 0

addons:
  eks_managed:
    count: 2
    list:
      - name: vpc-cni
        version: v1.18.1-eksbuild.1
        status: ACTIVE
        configuration: null
      - name: coredns
        version: v1.11.1-eksbuild.8
        status: ACTIVE
        configuration: null
  helm_releases:
    count: 1
    list:
      - name: karpenter
        namespace: kube-system
        chart: karpenter
        version: 1.0.5
        status: deployed
```

---

## Subagent Mode

When running full reconnaissance, delegate each module to a specialized subagent. This keeps each module's context isolated and enables true parallel execution.

### When to Use Subagents

| Scenario | Mode | Reason |
|----------|------|--------|
| Any recon (1+ modules) | **USE subagents** | Isolated context, cleaner main conversation |
| No Agent tool available | Inline | Subagents not supported |

> **IMPORTANT:** If the Agent tool is available, you MUST use subagent mode for ALL reconnaissance — even single-module targeted queries. Subagents keep detection context isolated from the main conversation. Do not fall back to inline mode just because "it's only one module" or "MCP tools work" — always delegate to subagents.

### Subagent Files

Each module has a corresponding subagent prompt in `agents/`:

| Subagent | File | Purpose |
|----------|------|---------|
| Compute | `agents/compute-recon.md` | Detect compute strategy |
| Networking | `agents/networking-recon.md` | Detect network config |
| Security | `agents/security-recon.md` | Detect security posture, secrets, webhooks |
| Add-ons | `agents/addons-recon.md` | Detect installed components |
| Observability | `agents/observability-recon.md` | Detect monitoring/logging |
| Storage | `agents/storage-recon.md` | Detect CSI, StorageClasses, PVCs |
| Workloads | `agents/workloads-recon.md` | Detect running workloads |
| IaC | `agents/iac-recon.md` | Detect IaC tooling |
| CI/CD | `agents/cicd-recon.md` | Detect deployment pipelines |

### Orchestration Steps

**Step 1: Check subagent availability**
```
If Agent tool is available:
  → MUST use subagent mode for ALL recon (full or targeted)
  → Even single-module queries use subagents to isolate context
Else:
  → Use inline mode (load references directly)
```

**Step 2: Spawn module subagents in parallel**

Spawn ALL module subagents in a SINGLE message for parallel execution:

```
Agent(
  description: "EKS compute recon",
  prompt: "Recon compute for cluster {cluster_name} in {region}. 
           Read agents/compute-recon.md and references/compute.md.
           Return YAML output only.",
  subagent_type: "general-purpose"
)

Agent(
  description: "EKS networking recon",
  prompt: "Recon networking for cluster {cluster_name} in {region}.
           Read agents/networking-recon.md and references/networking.md.
           Return YAML output only.",
  subagent_type: "general-purpose"
)

... (spawn all 9 in parallel)
```

**Step 3: Aggregate results**

When all subagents complete:
1. Collect each subagent's YAML output
2. Merge into single report structure, applying these normalization rules:
   - Every subagent emits its own top-level `cluster:` block. Merge into a single top-level `cluster:` by deduplicating exact-match blocks (all subagents report the same cluster); if any field mismatches across subagents, flag it rather than silently picking one.
   - Module outputs are already in their canonical agent-defined shapes. Preserve them verbatim under the matching top-level key: `compute:`, `iac:`, `cicd:`, `addons:`, `networking:`, `observability:`, `security:`, `storage:`, `workloads:`. Do not reshape, flatten, or rename keys.
   - If a subagent fails to respond or errors out, set its key to `unavailable: true` with a short `reason:` string; do not omit the key.
3. Add cross-module insights (e.g., "Karpenter detected but no IRSA for controller")
4. Generate recommendations based on combined findings
5. Write final report to `.eks-recon-report.yaml`
6. Present summary to user

---

## Integration with Other Workflows

### Upgrade Workflow

The upgrade workflow can invoke eks-recon to gather Phase 1 context:

```
1. Run eks-recon modules: cluster-basics, compute, iac, addons
2. Extract:
   - cluster.version -> Current version
   - compute.strategy -> Determines upgrade approach
   - iac.tool -> Terraform vs CLI upgrade path
   - addons -> Compatibility matrix input
```

### Design Workflow

The design workflow can use eks-recon for existing clusters:

```
1. Run eks-recon modules: all
2. Pre-populate questionnaire from detected values
3. Ask user: "I detected Karpenter + Terraform + ArgoCD. Correct?"
4. Only ask questions for undetected values
```

