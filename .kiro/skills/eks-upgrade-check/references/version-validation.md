# Version Validation & Upgrade Path

## Purpose
Validate the upgrade path, determine support status, and enforce EKS upgrade rules.

## EKS Version Support Calendar (fallback reference, as of June 2026)

> **Freshness gate — apply BEFORE using this table:**
> 1. If the cluster version or target version is **NOT in the table below** → fetch live
>    data from AWS docs (`search_documentation` for "EKS Kubernetes versions") before proceeding.
> 2. If today's assessment date is **past the "Extended Support Until" date** for the cluster's
>    current version → that version's status may have changed to UNSUPPORTED. Verify live before
>    reporting support status.
> 3. If live lookup fails or the MCP server is unavailable → use the table as fallback, but add
>    a note in the report: "Support status unverified — table data may be stale."

| Version | Standard Support Until | Extended Support Until | Status |
|---------|----------------------|----------------------|--------|
| 1.36 | August 2, 2027 | August 2, 2028 | ✅ STANDARD (latest in this table) |
| 1.35 | March 27, 2027 | March 27, 2028 | ✅ STANDARD |
| 1.34 | December 2, 2026 | December 2, 2027 | ✅ STANDARD |
| 1.33 | July 29, 2026 | July 29, 2027 | ✅ STANDARD |
| 1.32 | March 23, 2026 | March 23, 2027 | ⚠️ EXTENDED |
| 1.31 | November 26, 2025 | November 26, 2026 | ⚠️ EXTENDED |
| 1.30 | July 23, 2025 | July 23, 2026 | ⚠️ EXTENDED |

**CRITICAL:** The `upgradePolicy.supportType` field from the API is a CONFIGURATION PREFERENCE, not the current billing status. Always determine actual support status from the calendar above or from live AWS documentation.

**Cost impact:** Extended support costs $0.60/hr vs $0.10/hr for standard support.

**IMPORTANT — Cost Calculation Formula (do NOT estimate, always compute):**
```
extra_cost_per_month = (0.60 - 0.10) × 730 = $365/month per cluster
total_extended_cost  = 0.60 × 730 = $438/month per cluster
total_standard_cost  = 0.10 × 730 = $73/month per cluster
```
Always use this formula. Do NOT round, estimate, or hallucinate cost figures.
730 = average hours per month (365 days × 24 hours ÷ 12 months).

## Checks to Execute

### 1.0 — Target Version Existence (MUST run before other checks)

**Why:** EKS releases versions incrementally. A target version that doesn't exist on EKS yet
cannot be assessed. The arithmetic check (target - current == 1) is necessary but NOT sufficient.

**How to check:**
1. Confirm the target version exists in the calendar table above.
2. If NOT in the table → search AWS docs (`search_documentation` for "EKS Kubernetes versions")
   to confirm whether the version has been released on EKS.
3. If live lookup also finds no evidence the version exists on EKS → **ABORT the assessment.**

**If target version does not exist on EKS — STOP and report:**

```
## Assessment Cannot Proceed

**Target version <target> is not yet available on Amazon EKS.**

The latest supported EKS version is <latest_known>. Kubernetes <target> has not been
released on EKS as of this assessment date (<date>).

**What you can do:**
- Assess upgrade readiness to <latest_known> instead (if your cluster is on <latest - 1>)
- Monitor the EKS release calendar for <target> availability:
  https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html
```

Do NOT proceed with Steps 1-8. Do NOT produce a readiness score. End the assessment here.

### 1.1 — Current Version & Support Status

**How to check:**
1. Describe the cluster → get `version` and `platformVersion`
2. Match version against the calendar table above (applying the freshness gate)
3. Determine the support status. Possible states:
   - **STANDARD** — within standard support window
   - **EXTENDED** — past standard support, within extended support window
   - **UNSUPPORTED** — past extended support end date (see handling below)
4. Report: version, support status, when current support period ends (or already ended)

**UNSUPPORTED version handling:**

If the cluster version's Extended Support Until date has passed:
- Status = **UNSUPPORTED**
- Severity = **CRITICAL**
- Flag as a blocker in the report (see report-generation.md for template)
- The cluster no longer receives security patches or bug fixes from AWS
- AWS may force-upgrade the cluster with limited notice
- Extended support billing ($0.60/hr) still applies even past the end date until the cluster is upgraded
- Score impact: 15 pts deduction (see report-generation.md §Category 10)

**Output:** Current version, support tier, cost implications. If UNSUPPORTED, include urgency callout.

### 1.2 — Upgrade Path Validation

**Rules:**
- EKS requires upgrading **one minor version at a time** (e.g., 1.30 → 1.31, not 1.30 → 1.32)
- Downgrades are not supported
- Same-version "upgrades" are invalid

**How to check:**
1. Parse current version (from cluster describe) and target version (from user input)
2. Calculate version difference: `target_minor - current_minor`
3. If difference == 1: valid direct upgrade
4. If difference > 1: show required upgrade path (e.g., 1.29 → 1.30 → 1.31 → 1.32)
5. If difference <= 0: invalid (same version or downgrade)

**Output:** Valid/invalid path, required intermediate steps if multi-hop.

### 1.3 — Version Skew Policy Check

**Rules (Kubernetes version skew policy):**
- kubelet can be at most N-2 relative to the control plane
- If control plane is upgraded to target version, nodes must be within 2 minor versions

**How to check:**
1. List all node groups → describe each for Kubernetes version
2. List nodes via Kubernetes API → get kubelet versions from `status.nodeInfo.kubeletVersion`
3. For each node/node group version, calculate skew against the TARGET version (not current)
4. Skew > 2: **BLOCKER** — nodes must be upgraded first
5. Skew == 2: **WARNING** — at maximum skew, upgrade nodes promptly after control plane

**Output:** Per-node-group version, skew against target, blocker/warning status.

## Score Impact

> **Canonical scoring is defined in `references/report-generation.md` §Category 3 (Node Readiness) and §Category 10 (Unsupported Version).**

| Finding | Severity | Quick Reference |
|---------|----------|-----------------|
| On extended support | INFO | 0 pts |
| Version UNSUPPORTED | CRITICAL | 15 pts (Category 10) |
| Multi-hop upgrade needed | INFO | 0 pts |
| Target version unreleased | N/A | Assessment aborted — no score |
| Node skew == 2 (warning) | MEDIUM | 5 pts per node group |
| Node skew > 2 (blocker) | CRITICAL | 20 pts (caps category) |
