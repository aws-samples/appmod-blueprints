---
name: eks-cost-intelligence
description: Run a live EKS cluster cost efficiency assessment — analyze spending across 6 dimensions (compute efficiency, Spot/Graviton adoption, networking, storage, observability, idle resources), calculate a weighted 0-100 Cost Score, and generate a prioritized report with dollar-quantified findings and ready-to-apply remediation snippets. Use this skill when someone asks "how much am I wasting on EKS?", "run a cost audit on my cluster", "what's my biggest cost driver?", "analyze my cluster's cost efficiency", or needs dollar-denominated findings for a FinOps review — even if they don't say "cost intelligence" or "score". Combines live Cost Explorer data, CloudWatch utilization metrics, and Kubernetes resource analysis. Falls back to AWS CLI and kubectl when the EKS MCP server is unavailable. Distinct from eks-best-practices (static advisory guidance), eks-operation-review (operational health), and eks-recon (cluster discovery).
---

# EKS Cost Intelligence

## Overview

This skill performs a live cost efficiency assessment of your EKS cluster. It connects via AWS CLI and kubectl, analyzes cost signals across 6 dimensions, calculates a weighted Cost Score (0–100), and produces a detailed report with dollar-quantified findings, prioritized recommendations, and pre-filled remediation snippets.

This skill is focused on **live cost assessment** — answering the question: "Where is this cluster wasting money, and how much can I save?"

## When to Use

**Activate when the user:**
- Asks "how much am I wasting?" or "what's my biggest cost driver?"
- Requests a cost audit, cost review, or spending assessment on a live cluster
- Needs dollar-denominated findings to justify optimization work to leadership
- Wants cost attribution by namespace, team, or workload
- Is preparing a FinOps review or cost reduction initiative
- Asks which workloads are over-provisioned relative to actual usage
- Wants to know their cluster's cost efficiency score

**Do NOT activate when the user:**
- Asks general cost optimization best practices → use `eks-best-practices` (static advisory)
- Asks "how should I design my cluster for cost efficiency?" → use `eks-best-practices`
- Requests an operational review or health check → use `eks-operation-review`
- Wants cluster discovery or reconnaissance → use `eks-recon`
- Asks about upgrade readiness → use `eks-upgrade-check`
- Asks to set up the EKS MCP server → use `eks-mcp-server`

### Sibling Skill Disambiguation

| User Intent | Correct Skill | Why |
|---|---|---|
| "How should I optimize EKS costs?" | `eks-best-practices` | Advisory/design question — no live cluster needed |
| "Analyze my cluster's cost efficiency" | `eks-cost-intelligence` | Live assessment against a specific cluster |
| "Run an operational review" | `eks-operation-review` | Operational health, not cost-specific |
| "What version am I running?" | `eks-recon` | Cluster discovery, not cost analysis |
| "Is my cluster ready to upgrade?" | `eks-upgrade-check` | Upgrade readiness, not cost posture |

## Prerequisites

1. **AWS credentials configured** — `aws configure` or `~/.aws/credentials` with EKS access
2. **kubectl access** to the target cluster (for Kubernetes API queries)
3. **Required AWS Permissions (minimum):**
   - `eks:DescribeCluster`, `eks:ListClusters`, `eks:ListNodegroups`, `eks:DescribeNodegroup`
   - `ec2:DescribeInstances`, `ec2:DescribeVolumes`, `ec2:DescribeSubnets`, `ec2:DescribeVpcEndpoints`
   - `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTargetHealth`
4. **Optional permissions (enable richer analysis):**
   - `ce:GetCostAndUsage` — enables dollar-accurate spend data from Cost Explorer
   - `cloudwatch:GetMetricData` — enables utilization-based analysis from Container Insights

### Data Sources

| Source | Access Method | What It Provides |
|--------|--------------|-----------------|
| **AWS Cost Explorer** | `aws ce get-cost-and-usage` or MCP | Actual spend by service/tag |
| **CloudWatch Container Insights** | `aws cloudwatch get-metric-data` or MCP | CPU/memory utilization per pod/node |
| **Kubernetes API** | `kubectl` or MCP `list_k8s_resources` | Resource requests, limits, replica counts, PVCs |
| **EC2 API** | `aws ec2 describe-instances` | Instance types, pricing tier, Spot vs On-Demand |

If Cost Explorer is unavailable, the skill falls back to node-based cost estimation (see `references/cost-estimation-fallback.md`).

### MCP Server Setup

This skill works **without** any MCP server — it falls back to AWS CLI and kubectl commands. That fallback path is the default.

For richer operations (live cluster reads, CloudWatch metrics), enable the EKS MCP server via the `eks-mcp-server` skill. Once configured, this skill will prefer MCP tools over CLI for EKS operations.

### Getting Started

Invoke the skill or simply ask: *"Run a cost analysis on my EKS cluster"*

The skill will discover your clusters, confirm which one to assess, then run the full 6-dimension assessment.

---

## Assessment Workflow

### Step 0: Pre-flight — Cluster Discovery

**Action 1 — List clusters (test connectivity & discover clusters)**

Run `aws eks list-clusters` to discover available clusters.

- ✅ Success → Show the cluster list. Ask which cluster to assess. If only one cluster, confirm it.
- ❌ Failure → STOP. Do NOT retry more than once. Show:

> **Cannot access EKS clusters.** Try these steps:
> 1. Check that AWS credentials are configured: `aws sts get-caller-identity`
> 2. Check your region: `aws eks list-clusters --region <region>`
> 3. Verify permissions: `eks:ListClusters` is required

Wait for the user to resolve the issue.

**Action 2 — Describe the selected cluster**

Run `aws eks describe-cluster --name <cluster>` and show: cluster name, Kubernetes version, platform version, region, status, account ID.

**Action 3 — Validate cluster status**

Check the `status` field. If status is NOT `ACTIVE`:
- **CREATING/UPDATING/DELETING** → STOP. Show: "Cluster is currently in `<status>` state. Wait for the operation to complete, then re-run this assessment."
- **FAILED** → STOP. Show: "Cluster is in FAILED state. The cluster must be recovered before a cost assessment can be performed."

Do NOT proceed if cluster status is not ACTIVE.

**Action 4 — Gather cluster context**

Collect:
- Kubernetes version and platform version
- Node groups: `aws eks list-nodegroups --cluster-name <cluster>`
- Node group details: instance types, scaling config, capacity type (ON_DEMAND/SPOT)
- Add-ons: `aws eks list-addons --cluster-name <cluster>`
- Node inventory: `kubectl get nodes -o wide`

**Action 5 — Confirm and proceed**

Show the cluster summary and ask: *"Ready to start the cost assessment on [cluster-name] (v[version], [N] nodes)?"*

Proceed only after the user confirms.

### Step 1: Compute Efficiency Assessment

Read `references/compute-efficiency.md` before executing checks.

Checks:
- CPU and memory request-to-utilization ratios across non-system namespaces
- Over-provisioned workloads (requests exceed utilization by threshold)
- Low-utilization nodes indicating consolidation opportunities
- Karpenter consolidation effectiveness (where installed)
- Workloads without resource requests or limits

If metrics-server or Container Insights is unavailable, mark utilization checks as SKIPPED and proceed with request-only analysis.

### Step 2: Spot/Graviton Adoption Assessment

Read `references/spot-graviton-adoption.md` before executing checks.

Checks:
- Graviton (arm64) adoption percentage vs x86 (amd64)
- Node groups/NodePools without arm64 in allowed architectures
- Workloads with explicit amd64 affinity that could run on arm64
- Spot vs On-Demand capacity percentage
- Stateless multi-replica workloads on On-Demand only
- Instance type diversity for Spot availability
- Node Termination Handler or Karpenter interruption handling

### Step 3: Networking Cost Assessment

Read `references/networking-costs.md` before executing checks.

Checks:
- Topology-aware routing configuration on cross-AZ services
- Instance mode vs IP mode on load balancers
- VPC endpoints for ECR, S3, STS
- Cross-AZ traffic potential based on pod distribution
- NAT Gateway cost estimation

### Step 4: Storage Cost Assessment

Read `references/storage-costs.md` before executing checks.

Checks:
- PersistentVolumes using gp2 (flag for gp3 migration)
- PVCs bound but not mounted by any running pod
- Over-provisioned volumes (used vs provisioned capacity)
- EFS Intelligent-Tiering and lifecycle policies

### Step 5: Observability Cost Assessment

Read `references/observability-costs.md` before executing checks.

Checks:
- EKS control plane logging configuration (all log types enabled unnecessarily)
- High-cardinality metric sources (Prometheus scrape configs, CloudWatch agent)
- DEBUG/TRACE log levels in production namespaces
- Log filtering/sampling configurations (FluentBit, CloudWatch agent)

### Step 6: Idle Resource Detection

Read `references/idle-resources.md` before executing checks.

Checks:
- Deployments scaled to zero replicas for extended periods
- LoadBalancer Services with no healthy backend endpoints
- Namespaces with no running workloads but allocated quotas
- Orphaned ConfigMaps and Secrets not referenced by running workloads

### Step 7: Score Calculation

Read `references/report-generation.md` for the scoring algorithm.

Apply the scoring model:
- Start at 100 points
- Apply severity-weighted deductions per dimension (capped at dimension maximum)
- Skipped dimensions contribute zero deduction
- Classify final score: OPTIMIZED (90–100), GOOD (75–89), FAIR (60–74), NEEDS_WORK (40–59), CRITICAL (0–39)

### Step 8: Report Generation

Read `references/report-generation.md` for the report template.

Generate the report:
1. Build master finding list sorted by severity then savings
2. Generate markdown report using the template
3. Save with filename pattern: `EKS-Cost-Intelligence-{cluster}-{YYYY-MM-DD}-{HHMM}.md`
4. Offer HTML conversion via `tools/report_to_html.py`

---

## Cost Score

The skill calculates a weighted cost efficiency score:

| Dimension | Max Deduction | What It Measures |
|-----------|--------------|-----------------|
| Compute Efficiency | 25 pts | CPU/memory waste, over-provisioning, missing requests |
| Spot/Graviton Adoption | 20 pts | Spot percentage, Graviton eligibility, instance diversity |
| Networking Costs | 15 pts | Cross-AZ traffic, VPC endpoints, topology routing |
| Storage Costs | 15 pts | gp2→gp3, unused PVCs, oversized volumes |
| Observability Costs | 10 pts | Control plane logging, metric cardinality, log levels |
| Idle Resources | 15 pts | Zero-scale deploys, orphaned LBs, empty namespaces |

**Score Classification:**
- 90–100: **OPTIMIZED** — Excellent cost efficiency
- 75–89: **GOOD** — Minor optimization opportunities
- 60–74: **FAIR** — Several areas need attention
- 40–59: **NEEDS_WORK** — Significant waste detected
- 0–39: **CRITICAL** — Major cost inefficiencies across multiple dimensions

**Key differences from eks-upgrade-check scoring:**
- No hard-blocker override (cost issues don't prevent cluster operation)
- Severity-weighted deductions within each dimension
- Skipped dimensions excluded entirely (not penalized)

---

## Out of Scope (v1)

The following are intentionally excluded from the initial release and may be added in future versions:

| Area | Rationale |
|------|-----------|
| **Savings Plans / RI coverage scoring** | Data is collected (see `cost-data-collection.md`) but not scored as a dimension. SP/RI decisions are account-level purchasing decisions, not cluster-level configuration. Findings are surfaced as informational notes when coverage < 70%, but do not contribute to the Cost Score. |
| **Namespace/team cost attribution as a scored dimension** | The skill reports namespace cost allocation (via Split Cost Allocation Data or request-based estimation) in the report's methodology section, but does not score attribution quality. Attribution is an observability concern, not a waste indicator. |
| **GPU utilization efficiency** | Only relevant for ML-heavy clusters. Deferred to a future enhancement. |
| **Non-prod time-based downscaling** | High-ROI quick win but requires time-series analysis beyond a point-in-time assessment. Planned for Idle Resources dimension enhancement. |
| **Internet egress optimization** | Covered partially by NAT Gateway analysis; full egress optimization is out of scope. |

---

## Tool Usage Rules

1. **Do NOT call any tools when this skill is first activated.** Wait for the user to explicitly ask for a cost assessment.
2. **Do NOT hardcode or guess cluster names.** Always discover clusters by listing them first.
3. **Do NOT retry a failed command more than once.** If it fails twice, log the failure, skip that check, and continue.
4. **Always read the relevant reference file before executing checks for that dimension.**
5. **Use `aws` CLI and `kubectl` for cluster queries.** If MCP servers are available, prefer them for EKS operations.
6. **Do NOT duplicate advisory content from eks-best-practices.** Reference it in recommendations where relevant.

---

## Steering File Map

Before executing checks for any dimension, read the corresponding reference file from `skills/eks-cost-intelligence/references/`.

| User Request | Reference File(s) to Load |
|---|---|
| Full cost assessment / audit / review | ALL dimension files in order (Steps 1–6), then `report-generation.md` |
| Compute efficiency / over-provisioning / CPU waste | `references/compute-efficiency.md` |
| Spot / Graviton / instance types / arm64 | `references/spot-graviton-adoption.md` |
| Networking costs / cross-AZ / NAT / VPC endpoints | `references/networking-costs.md` |
| Storage costs / gp2 / PVC / EBS | `references/storage-costs.md` |
| Observability / logging / metrics / cardinality | `references/observability-costs.md` |
| Idle resources / unused / orphaned / zero-scale | `references/idle-resources.md` |
| Score calculation / scoring algorithm | `references/report-generation.md` |
| Generate report / produce report | `references/report-generation.md` |
| Cost data collection / API calls | `references/cost-data-collection.md` |
| Waste formulas / dollar calculation | `references/waste-calculation.md` |
| Fallback estimation / no Cost Explorer | `references/cost-estimation-fallback.md` |
| Finding format / output schema | `references/findings-format.md` |

---

## Report Output

- **Markdown:** `EKS-Cost-Intelligence-{cluster}-{YYYY-MM-DD}-{HHMM}.md`
- **HTML:** Run `python3 ${SKILL_DIR}/tools/report_to_html.py <report>.md` to convert

Do NOT generate HTML manually. Always use the conversion script.

The report includes:
- Executive summary with total estimated spend and projected savings
- Cost Score with classification and per-dimension breakdown
- Prioritized recommendations sorted by savings impact
- Per-dimension findings with remediation snippets
- Methodology and confidence notes
- Disclaimer footer

---

*This skill is provided as sample code for educational and demonstration purposes only. Findings should be reviewed and validated before acting on them. See the project's README and LICENSE for full terms.*
