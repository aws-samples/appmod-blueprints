---
name: eks-upgrade-check
description: Assess EKS cluster upgrade readiness — run automated checks across 8 areas (version, breaking changes, deprecated APIs, add-on compatibility, node readiness, workload risks, AWS Insights, upgrade plan), calculate a 0-100 readiness score with a hard-blocker override, and generate a markdown/HTML report with prioritized remediation. Use this skill whenever someone asks "can I upgrade my cluster?", "is my cluster ready for 1.32?", "are we good to go to 1.33?", "what is blocking my upgrade?", or "should we move to the next version?" — even if they do not say "readiness" or "score". Falls back to AWS CLI and kubectl when the EKS MCP server is unavailable.
allowed-tools: Bash, Read, Write, Grep, Glob, WebFetch, WebSearch
---

# EKS Upgrade Readiness Skill

## Overview

This skill assesses your live EKS cluster's readiness for a Kubernetes version upgrade. It connects to your cluster via AWS CLI and kubectl, runs automated checks across 8 assessment areas, calculates a readiness score (0-100%), and produces a detailed report with prioritized remediation steps and pre-filled AWS CLI commands.

This skill is laser-focused on **upgrade safety** — answering the question: "Is it safe to upgrade this cluster to the next version?"

## What Gets Assessed

| # | Section | Key Checks |
|---|---------|------------|
| 01 | Version Validation | Upgrade path validity, version skew policy, support status |
| 02 | Breaking Changes | Version-specific API removals, behavioral changes, resource impact |
| 03 | Deprecated API Detection | Live scan of cluster resources for deprecated/removed APIs |
| 04 | Add-on Compatibility | Core add-on versions, OSS add-on matrix, Karpenter compatibility |
| 05 | Node Readiness | Node version skew, AL2→AL2023 migration, AMI compatibility |
| 06 | Workload Risks | Single replicas, missing PDBs, health probes, resource requests |
| 07 | AWS Upgrade Insights | Official EKS pre-upgrade checks and recommendations |
| 08 | Upgrade Plan | Pre-filled CLI commands, step-by-step upgrade sequence |

## Readiness Score

The skill calculates a weighted readiness score:

| Category | Max Deduction | Rationale |
|----------|--------------|-----------|
| Breaking Changes | 25 pts | Highest risk — can break apps |
| Deprecated APIs | 20 pts | Actionable, fixable pre-upgrade |
| Node Readiness (skew + subnet IPs) | 20 pts | Can block upgrade entirely |
| Unsupported Version | 15 pts | No security patches, urgent upgrade needed |
| Add-on Compatibility | 15 pts | Critical > optional add-ons |
| Karpenter | 10 pts | Only if installed |
| Workload Risks | 10 pts | Best-practice, not blockers |
| AWS Upgrade Insights | 10 pts | Official AWS checks |
| AL2 Nodes / Behavioral | 10 pts | Informational |

**Hard Blocker Override:** If any hard blocker is detected (e.g., incompatible Karpenter, critical
add-on DEGRADED, subnet IPs < 5, cluster not ACTIVE), the score is capped at ≤ 59% (NOT READY)
regardless of other findings. See `references/report-generation.md` for the full list.

**Score Interpretation:**
- 90-100: **READY** — Safe to proceed
- 80-89: **GOOD** — Minor issues, can proceed with caution
- 70-79: **FAIR** — Several issues need attention first
- 60-69: **RISKY** — Significant issues, not recommended yet
- 0-59: **NOT READY** — Critical blockers, must resolve first

## Prerequisites

1. **AWS credentials configured** — `aws configure` or `~/.aws/credentials` with EKS access
2. **kubectl access** to the target cluster (for Kubernetes API queries)
3. **Required AWS Permissions:**
   - `eks:DescribeCluster`, `eks:ListClusters`, `eks:ListNodegroups`, `eks:DescribeNodegroup`
   - `eks:ListAddons`, `eks:DescribeAddon`, `eks:ListInsights`, `eks:DescribeInsight`
   - `ec2:DescribeSubnets`
   - `iam:GetRole`, `iam:ListAttachedRolePolicies`, `iam:ListRolePolicies`, `iam:GetRolePolicy`

### MCP Server Setup

This skill works without any MCP server — it falls back to AWS CLI and kubectl commands. That fallback path is the default in apex.

For richer EKS operations (live cluster reads, upgrade insights, K8s resource introspection), enable the EKS MCP server via the apex `eks-mcp-server` skill — it walks you through both AWS-hosted and self-hosted setup options. Once configured, this skill will prefer MCP tools over CLI for EKS operations.

Note: Apex does NOT ship a project-root `.mcp.json`. MCP setup is opt-in and user-driven through the `eks-mcp-server` skill.

### Configuration

The skill uses your existing AWS credentials. No additional configuration needed if `aws eks list-clusters` works from your terminal.

To use a specific profile or region, set environment variables:
```bash
export AWS_PROFILE=your-profile-name
export AWS_REGION=your-region
```

### Getting Started

Invoke the skill: `/eks-upgrade-check`

Or simply ask: *"Run an EKS upgrade readiness assessment"*

The skill will discover your clusters, ask which one to assess and what target version, then run the full assessment.

---

## Assessment Workflow

### Step 0: Pre-flight

**Action 1 — List clusters (test connectivity & discover clusters)**

Run `aws eks list-clusters` to discover available clusters.

- ✅ Success → Show the cluster list. Ask which cluster to assess. If only one cluster, confirm it.
- ❌ Failure → STOP. Do NOT retry more than once. Show:

> **Cannot access EKS clusters.** Try these steps:
> 1. Check that AWS credentials are configured: `aws sts get-caller-identity`
> 2. Check your region: `aws eks list-clusters --region <region>`
> 3. Check that MCP servers are enabled in Claude Code

Wait for the user to resolve the issue.

**Action 2 — Describe the selected cluster**

Run `aws eks describe-cluster --name <cluster>` and show: cluster name, Kubernetes version, platform version, region, status, account ID.

**Action 2b — Validate cluster status**

Check the `status` field from the cluster description. If status is NOT `ACTIVE`:
- **CREATING/UPDATING/DELETING** → STOP. Show: "Cluster is currently in `<status>` state. The EKS API will reject an upgrade request. Wait for the operation to complete, then re-run this assessment."
- **FAILED** → STOP. Show: "Cluster is in FAILED state. This is a hard blocker — the cluster must be recovered before an upgrade can be attempted. Contact AWS Support if the cluster is stuck in FAILED."

Do NOT proceed with the assessment if cluster status is not ACTIVE. This is a hard blocker (see report-generation.md).

**Action 3 — Validate permissions**

After describing the cluster, verify key permissions by attempting:
1. `aws eks list-nodegroups --cluster-name <cluster>`
2. `aws eks list-addons --cluster-name <cluster>`
3. `aws eks list-insights --cluster-name <cluster>`

If any fail with AccessDenied, show the user exactly which permission is missing and list the required IAM actions. Do NOT proceed until permissions are confirmed.

**Action 4 — Determine target version**

Ask: *"Your cluster is on v[current]. The next version is v[current+1]. Shall I assess upgrade readiness to v[current+1]?"*

If the user specifies a version more than 1 minor version ahead, explain that EKS requires one-version-at-a-time upgrades and show the required path (e.g., 1.29 → 1.30 → 1.31 → 1.32). Offer to assess the first hop.

**Action 5 — Confirm and proceed**

### Steps 1-8: Run Assessment

Read each steering file in order from `${CLAUDE_SKILL_DIR}/references/`. For each section:
1. Read the steering file
2. Execute the checks described in it using AWS CLI and kubectl commands
3. Collect findings with severity ratings

**Steering file loading guide:**

| User Request | Steering File(s) |
|---|---|
| Full upgrade assessment | ALL files in order |
| Version / upgrade path | `references/version-validation.md` |
| Breaking changes / API removals | `references/breaking-changes.md` |
| Deprecated APIs | `references/deprecated-apis.md` |
| Add-on compatibility / Karpenter | `references/addon-compatibility.md` |
| Node readiness / AL2 / AMI | `references/node-readiness.md` |
| Workload risks / PDB / probes | `references/workload-risks.md` |
| AWS Insights | `references/upgrade-insights.md` |
| Generate report | `references/report-generation.md` |

### Step 9: Calculate Score & Generate Report

Read `${CLAUDE_SKILL_DIR}/references/report-generation.md` and produce the report.

---

## Tool Usage Rules

1. **Do NOT call any tools when this skill is first activated.** Wait for the user to ask.
2. **Do NOT hardcode or guess cluster names.** Always discover by listing first.
3. **Do NOT retry a failed command more than once.**
4. **Always read the relevant steering file before executing checks for that section.**
5. **Use `aws` CLI and `kubectl` for cluster queries.** If MCP servers are available, prefer them for EKS operations.

## Data Files

- **OSS Add-on Registry:** `${CLAUDE_SKILL_DIR}/data/oss_addon_registry.json` — identifiers and authoritative upstream URLs for common OSS add-ons. This file does NOT contain compatibility data. Compatibility is always verified live via the registry's `compatibility_url` and `releases_url` fields. If an add-on is not in the registry or the upstream source is unreachable, report UNKNOWN — never guess.
- **HTML Converter:** `${CLAUDE_SKILL_DIR}/tools/md_to_html.py` — converts markdown reports to HTML

## Report Output

- **Markdown:** `EKS-Upgrade-Assessment-<cluster>-<version>-<YYYY-MM-DD>-<HHMM>.md`
- **HTML:** Run `python3 ${CLAUDE_SKILL_DIR}/tools/md_to_html.py <report>.md` to convert

Do NOT generate HTML manually. Always use the conversion script.
