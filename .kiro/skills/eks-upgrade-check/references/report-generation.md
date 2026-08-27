# Report Generation

## Purpose
After all assessment checks are complete, calculate the readiness score and generate the upgrade assessment report.

## Step 1: Calculate Readiness Score

You MUST follow this algorithm exactly. Do NOT interpret loosely. Every rule below is deterministic.

### 1.1 — Scoring Algorithm (Pseudocode)

```
score = 100

# --- Category 1: Breaking Changes (max deduction: 25) ---
# COUNTING UNIT: each distinct breaking change TYPE that affects at least one resource.
# Example: "FlowSchema v1beta2 removed" = 1 item (even if 17 FlowSchema resources use it).
# Example: "PSP removed" = 1 item (even if 5 PSPs exist).
breaking_changes_deduction = 0
for each breaking_change_type found in cluster:
    if severity == HIGH:   breaking_changes_deduction += 10
    if severity == MEDIUM: breaking_changes_deduction += 4
    if severity == LOW:    breaking_changes_deduction += 2
breaking_changes_deduction = min(breaking_changes_deduction, 25)

# --- Category 2: Deprecated APIs (max deduction: 20) ---
# COUNTING UNIT: each distinct API path (e.g., flowschemas and prioritylevelconfigurations
# are 2 separate API paths even though they share the same API group).
# Count API paths, NOT individual resources using that path.
#
# An API path is "found in cluster" if surfaced by EITHER Step 2a (live object
# apiVersion) OR Step 2b (any entry in metadata.managedFields[].apiVersion) in
# references/deprecated-apis.md. A path is counted ONCE regardless of step.
deprecated_apis_deduction = 0
for each deprecated_api_path found in cluster:
    if removed_in_target_version:    deprecated_apis_deduction += 5
    if deprecated_but_still_served:  deprecated_apis_deduction += 1
deprecated_apis_deduction = min(deprecated_apis_deduction, 20)

# --- Category 3: Node Readiness (max deduction: 20) ---
# Includes version skew, subnet IP capacity, AND containerd runtime.
# COUNTING UNIT: each node group (skew) + each subnet (IP check) + containerd runtime.
node_skew_deduction = 0
for each node_group:
    skew = target_minor_version - node_group_minor_version
    if skew > 2:  node_skew_deduction += 20   # blocker — immediately caps
    if skew == 2: node_skew_deduction += 5
for each subnet in cluster_subnets:
    if subnet.available_ips < 5:   node_skew_deduction += 5   # hard blocker
    elif subnet.available_ips <= 15: node_skew_deduction += 2  # warning
# Containerd 1.x runtime (see node-readiness.md 5.3 for node-type classification):
if any node on containerd 1.x:
    if target >= 1.36 and any such node is self-managed/custom-AMI:
        node_skew_deduction += 5   # hard blocker (managed nodes exempt — they self-heal)
    else:
        node_skew_deduction += 2   # warning (pre-1.36, or managed node that auto-upgrades)
node_skew_deduction = min(node_skew_deduction, 20)

# --- Category 4: Add-on Compatibility (max deduction: 15) ---
# COUNTING UNIT: each add-on (by name) + each unidentified workload.
# CLASSIFICATION RULES:
#   - "critical add-on" = vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver
#   - "optional add-on" = all other managed add-ons and identified OSS add-ons
#   - Status DEGRADED or FAILED with correct version = treat as critical/optional
#     incompatible (same deduction as version incompatibility)
#   - Status ACTIVE but version behind = "update recommended"
#   - UNKNOWN_VERIFIABLE = identified but upstream compat source unreachable/ambiguous
#   - UNKNOWN_UNIDENTIFIED = workload looks like an add-on but couldn't be identified
addon_deduction = 0
for each addon:
    if addon.verdict == "INCOMPATIBLE" or addon.status in [DEGRADED, FAILED]:
        if addon.name in [vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver]:
            addon_deduction += 5   # critical add-on
        else:
            addon_deduction += 3   # optional add-on
    elif addon.verdict == "UNKNOWN_VERIFIABLE":
        addon_deduction += 2       # identified, compatibility unverified
    elif addon.verdict == "UPDATE_RECOMMENDED":
        addon_deduction += 1       # version behind but compatible
for each unidentified_workload:
    addon_deduction += 2           # UNKNOWN_UNIDENTIFIED
addon_deduction = min(addon_deduction, 15)

# --- Category 5: Karpenter (max deduction: 10) ---
# COUNTING UNIT: binary — installed and incompatible, or not.
karpenter_deduction = 0
if karpenter_installed and karpenter_version_incompatible_with_target:
    karpenter_deduction = 10

# --- Category 6: Workload Risks (max deduction: 10) ---
# COUNTING UNIT: each individual Deployment/StatefulSet/DaemonSet affected.
# Only count workloads in non-system namespaces (exclude: kube-system, kube-public,
# kube-node-lease, karpenter, amazon-cloudwatch, amazon-guardduty).
# A single workload can trigger MULTIPLE risk types — count each risk separately.
#
# HIGH-severity risks (3 pts each, sub-cap 8 pts):
#   - Deployment with replicas == 1
#   - Deployment with strategy.type == Recreate
#
# MEDIUM-severity risks (1 pt each unless noted, sub-cap 4 pts):
#   - Deployment missing readinessProbe on ANY container (1 pt)
#   - Deployment missing resources.requests (cpu or memory) on ANY container (1 pt)
#   - Multi-replica Deployment without a matching PodDisruptionBudget (1 pt)
#   - Drain-blocking PDB (disruptionsAllowed == 0) (2 pts each)
#
# IMPORTANT: If one workload has BOTH single-replica AND missing probes,
# that is 1 HIGH (3 pts) + 1 MEDIUM (1 pt) = 4 pts for that workload.
workload_high = 0
workload_medium = 0
for each workload in non_system_namespaces:
    if workload.replicas == 1:                workload_high += 3
    if workload.strategy == "Recreate":       workload_high += 3
    if workload.missing_readiness_probe:      workload_medium += 1
    if workload.missing_resource_requests:    workload_medium += 1
    if workload.replicas > 1 and no_matching_pdb: workload_medium += 1
for each pdb where disruptionsAllowed == 0:
    workload_medium += 2                      # drain-blocking PDB
workload_high = min(workload_high, 8)
workload_medium = min(workload_medium, 4)
workload_deduction = min(workload_high + workload_medium, 10)

# --- Category 7: AWS Upgrade Insights (max deduction: 10) ---
# COUNTING UNIT: each insight ID from the EKS Insights API.
# Map insight status to severity:
#   FAILING → 5 pts
#   WARNING → 2 pts
#   ERROR   → 3 pts
#   PASSING → 0 pts
#   UNKNOWN → 0 pts
insights_deduction = 0
for each insight:
    if insight.status == "FAILING":  insights_deduction += 5
    if insight.status == "WARNING":  insights_deduction += 2
    if insight.status == "ERROR":    insights_deduction += 3
insights_deduction = min(insights_deduction, 10)

# --- Category 8: AL2 Nodes (max deduction: 5) ---
# COUNTING UNIT: count of individual AL2 nodes.
al2_deduction = 0
al2_node_count = count of nodes where osImage contains "Amazon Linux 2" (not "2023")
                 or kernelVersion contains "amzn2"
if al2_node_count > 0:
    al2_deduction = 2 + (al2_node_count // 3)   # integer division
al2_deduction = min(al2_deduction, 5)

# --- Category 9: Behavioral Changes (max deduction: 5) ---
# COUNTING UNIT: each distinct behavioral change TYPE that applies to the target version.
behavioral_deduction = 0
for each behavioral_change applicable to target:
    if severity == MEDIUM: behavioral_deduction += 2
    if severity == LOW:    behavioral_deduction += 1
behavioral_deduction = min(behavioral_deduction, 5)

# --- Category 10: Unsupported Version (max deduction: 15) ---
# TRIGGER: cluster's current version has passed its Extended Support Until date.
# This is a binary check — either the version is unsupported or it isn't.
# NOTE: If the target version does not exist on EKS, the assessment is ABORTED
# in Step 1.0 (version-validation.md) — no score is produced at all.
unsupported_deduction = 0
if cluster_version_extended_support_end_date < assessment_date:
    unsupported_deduction = 15

# --- Final Score ---
total_deductions = (breaking_changes_deduction + deprecated_apis_deduction
                    + node_skew_deduction + addon_deduction + karpenter_deduction
                    + workload_deduction + insights_deduction + al2_deduction
                    + behavioral_deduction + unsupported_deduction)
score = max(0, 100 - total_deductions)

# --- Hard Blocker Override (apply AFTER arithmetic) ---
# If ANY hard blocker is present, the upgrade CANNOT proceed safely.
# Cap score at 59 (NOT READY) regardless of the arithmetic result.
#
# Hard blockers (exhaustive list):
#   1. Node version skew > 2 (K8s API server rejects the upgrade)
#   2. Karpenter version incompatible with target (node provisioning breaks)
#   3. Critical add-on INCOMPATIBLE with target version (networking/storage breaks)
#   4. Critical add-on DEGRADED or FAILED (node drain stalls — volumes, DNS, or
#      networking broken during reschedule)
#   5. API removed in target version AND actively used in cluster (workloads fail)
#   6. Cluster status != ACTIVE (EKS API rejects update-cluster-version)
#   7. AL2-only node groups AND target >= 1.33 (no AL2 AMI available for target)
#   8. Any cluster subnet has < 5 available IPs (EKS API rejects update-cluster-version)
#   9. Self-managed / custom-AMI node on containerd 1.x AND target >= 1.36 (1.36 kubelet
#      won't run on containerd 1.x). Managed node groups / Bottlerocket are EXEMPT —
#      their node-group upgrade pulls containerd 2.0+ automatically.
#
# NOTE: "Critical add-on" = vpc-cni, coredns, kube-proxy, aws-ebs-csi-driver
has_hard_blocker = False
if node_skew_any_group > 2:                           has_hard_blocker = True
if karpenter_installed and karpenter_incompatible:    has_hard_blocker = True
if any critical_addon.verdict == "INCOMPATIBLE":      has_hard_blocker = True
if any critical_addon.status in [DEGRADED, FAILED]:   has_hard_blocker = True
if any api_removed_in_target_and_in_use:              has_hard_blocker = True
if cluster_status != "ACTIVE":                        has_hard_blocker = True
if al2_only_node_groups and target >= 1.33:           has_hard_blocker = True
if any subnet.available_ips < 5:                      has_hard_blocker = True
if any (node.containerd_major == 1 and node.is_self_managed) and target >= 1.36:
    has_hard_blocker = True

if has_hard_blocker:
    score = min(score, 59)
```

### 1.2 — Score Interpretation

| Score | Rating | Meaning |
|-------|--------|---------|
| 90-100 | READY | Safe to proceed with upgrade |
| 80-89 | GOOD | Minor issues, can proceed with caution |
| 70-79 | FAIR | Several issues need attention before upgrade |
| 60-69 | RISKY | Significant issues, upgrade not recommended yet |
| 0-59 | NOT READY | Critical blockers, must resolve before upgrade |

### 1.3 — Worked Example

Cluster: `example-cluster`, upgrading 1.30 → 1.31

**Findings:**
- EBS CSI driver DEGRADED (IAM issue) → critical add-on, status DEGRADED → 5 pts
- 17 FlowSchema resources using `flowcontrol.apiserver.k8s.io/v1beta3` (2 API paths: flowschemas + prioritylevelconfigurations, deprecated but available in 1.31) → 1 + 1 = 2 pts
- 1 AWS Insight WARNING (deprecated APIs for v1.32) → 2 pts
- `legacy-app`: 1 replica (HIGH=3) + Recreate strategy (HIGH=3) + missing probes (MED=1) + missing requests (MED=1) = 8 pts
- `single-replica-app`: 1 replica (HIGH=3) + missing probes (MED=1) + missing requests (MED=1) = 5 pts
- `recreate-app`: Recreate strategy (HIGH=3) + missing probes (MED=1) = 4 pts
- `no-resources-app`: missing probes (MED=1) + missing requests (MED=1) = 2 pts
- `insufficient-replicas-app`: missing probes (MED=1) = 1 pt
- `karpenter-test-app`: missing probes (MED=1) = 1 pt

**Workload risk calculation:**
- HIGH sub-total: 3+3+3+3 = 12 → capped at 8
- MEDIUM sub-total: 1+1+1+1+1+1+1+1+1+1 = 10 → capped at 4
- Workload total: 8+4 = 12 → capped at 10

**Score (arithmetic):**
```
100 - 0 (breaking) - 2 (deprecated) - 0 (skew) - 5 (addon) - 0 (karpenter)
    - 10 (workload) - 2 (insights) - 0 (AL2) - 0 (behavioral) - 0 (unsupported)
= 100 - 19 = 81%
```

**Hard blocker override:**
```
EBS CSI driver DEGRADED → critical add-on DEGRADED → has_hard_blocker = True
score = min(81, 59) = 59% → NOT READY
```

**Final score: 59% — NOT READY** (hard blocker: critical add-on DEGRADED)

## Step 2: Build Master Finding List (MANDATORY — do this BEFORE calculating the score)

Before calculating the score, you MUST compile a complete finding table. This table is the single source of truth for scoring. Every row must map to exactly one line in the pseudocode above.

```
| # | Category | Finding | Counting Unit | Severity | Pts | Rule Applied |
|---|----------|---------|---------------|----------|-----|--------------|
| 1 | Deprecated APIs | flowschemas v1beta3 | API path | LOW | 1 | deprecated_but_still_served |
| 2 | Deprecated APIs | prioritylevelconfigurations v1beta3 | API path | LOW | 1 | deprecated_but_still_served |
| 3 | Add-on | aws-ebs-csi-driver DEGRADED | add-on | HIGH | 5 | critical addon DEGRADED |
| ... | ... | ... | ... | ... | ... | ... |
```

After building this table:
1. Sum each category column
2. Apply the per-category cap from the pseudocode
3. Sum all capped category totals
4. Subtract from 100

Include this table in the report under "Score Breakdown" so users can audit the math.

## Step 3: Consistency Checks (MANDATORY)

### 3.1 Structural contract (check FIRST, before content checks)

Before returning the report, verify it contains exactly these top-level sections
in this order:

1. `# EKS Upgrade Readiness Assessment`
2. `## Readiness Score: ...`
3. `## Blockers & Critical Actions`
4. `## Recommended Actions`
5. `## Informational Findings`
6. `## Evidence`
7. `## Upgrade Plan`
8. `## AWS Reference Links`

If ANY of sections 3, 4, 5, 7, or 8 is missing, the report is invalid — add the
missing section (with "No blockers identified." / "No recommended actions." /
"None." placeholder text if empty) before returning it to the user.

Sections 3, 4, and 5 MUST appear before section 6 (Evidence). If they appear
after Evidence, the report is invalid — reorder before returning.

### 3.2 Content checks

1. Every HIGH/CRITICAL finding must appear in "Blockers & Critical Actions"
2. Every MEDIUM finding must appear in "Recommended Actions"
3. Every LOW finding must appear in "Informational Findings"
4. The executive summary must match the findings — don't call something critical if it's medium
5. Score components must add up correctly
6. **CROSS-CHECK RULE:** Before writing any count (e.g., "5 deployments missing probes"),
   go back to the raw data and list the names. If the count of names doesn't match the number
   in your heading, fix it. Never write a count from memory.
7. **NO HALLUCINATED NUMBERS:** For any dollar amount, percentage, or numeric claim, show the
   arithmetic inline or in a comment. If you can't show the math, don't state the number.
8. **WORKLOAD TABLE REQUIRED:** The master workload table from `workload-risks.md` Step A
   MUST be produced before any workload risk findings are written. All workload counts in the
   report must be traceable to rows in that table.

## Step 4: Write the Report

### Filename Format
`EKS-Upgrade-Assessment-<cluster>-<current>-to-<target>-<YYYY-MM-DD>-<HHMM>.md`

Example: `EKS-Upgrade-Assessment-my-cluster-1.30-to-1.31-2026-03-26-1430.md`

### Report Template

**The report structure is a contract, not a suggestion.** Every report MUST contain
the sections below, in exactly this order, with exactly these headings. Do not
reorder, rename, or omit required sections. Sections marked OPTIONAL are included
only when their condition is met; if the condition isn't met, omit the section
entirely (do not leave it as "N/A" or "None found").

**Required section order (every report, every time):**

1. `# EKS Upgrade Readiness Assessment` — title + metadata table
2. `## Readiness Score: XX% — [LEVEL]` — summary sentence + Score Breakdown table
3. `## Blockers & Critical Actions` — MUST appear even if empty (write "No blockers identified.")
4. `## Recommended Actions` — MUST appear even if empty (write "No recommended actions.")
5. `## Informational Findings` — MUST appear even if empty (write "None.")
6. `## Evidence` — container for the detailed tables below
   - `### Add-on Inventory`
   - `### Unknown & Unidentified Add-ons` — OPTIONAL (only if any UNKNOWN_* verdicts exist)
   - `### Node Group Summary`
   - `### Workload Risk Summary`
7. `## Upgrade Plan` — always required
8. `## AWS Reference Links` — always required

The three action sections (Blockers, Recommended, Informational) come BEFORE the
Evidence tables. This is intentional — readers open the report to answer "what do
I need to do?", not "what did the tool find?". Evidence supports the action items;
it doesn't precede them.

```markdown
# EKS Upgrade Readiness Assessment

| Field | Value |
|-------|-------|
| Cluster | [name] |
| Region | [region] |
| Account | [account-id] |
| Current Version | [current] |
| Target Version | [target] |
| Assessment Date | [YYYY-MM-DD HH:MM] |

---

## Readiness Score: [XX]% — [READY/GOOD/FAIR/RISKY/NOT READY]

[2-3 sentence summary. What's the bottom line? Can they upgrade safely?]

### Score Breakdown

| Category | Status | Deduction | Details |
|----------|--------|-----------|---------|
| Breaking Changes | ✅/⚠️/❌ | -X pts | [summary] |
| Deprecated APIs | ✅/⚠️/❌ | -X pts | [summary] |
| Node Readiness | ✅/⚠️/❌ | -X pts | [summary] |
| Add-on Compatibility | ✅/⚠️/❌ | -X pts | [summary] |
| Karpenter | ✅/⚠️/❌/N/A | -X pts | [summary] |
| Workload Risks | ✅/⚠️/❌ | -X pts | [summary] |
| AWS Upgrade Insights | ✅/⚠️/❌ | -X pts | [summary] |
| AL2 / AMI | ✅/⚠️/❌ | -X pts | [summary] |
| Behavioral Changes | ✅/⚠️/❌ | -X pts | [summary] |
| Unsupported Version | ✅/❌/N/A | -X pts | [summary — omit row if version is supported] |
| **Total** | | **-X pts** | **Score: XX%** |

---

## Blockers & Critical Actions

[Items that MUST be resolved before upgrading. If none, write: "No blockers identified."]

### [Finding Title]
- **Severity:** HIGH/CRITICAL
- **What we found:** [specific to this cluster]
- **Impact if not addressed:** [real-world consequence]
- **Remediation:**
  ```bash
  [pre-filled command with actual cluster name and region]
  ```
- **Reference:** [AWS doc link]

---

## Recommended Actions

[Items that SHOULD be addressed but won't block the upgrade. If none, write: "No recommended actions."]

### [Finding Title]
- **Severity:** MEDIUM
- **What we found:** [details]
- **Remediation:** [steps]

---

## Informational Findings

[LOW severity items and behavioral changes — awareness only. If none, write: "None."]

---

## Evidence

### Add-on Inventory

| Add-on | Type | Version | Status | Verdict | Source |
|--------|------|---------|--------|---------|--------|
| [name] | Managed/Self-managed/OSS | [ver] | [health] | COMPATIBLE/UPDATE_RECOMMENDED/INCOMPATIBLE/UNKNOWN_VERIFIABLE | [URL or "managed"] |

### Unknown & Unidentified Add-ons

Include this subsection only if ANY add-on has verdict `UNKNOWN_VERIFIABLE` or
`UNKNOWN_UNIDENTIFIED`. Omit it entirely if everything was resolved.

#### Compatibility Unverified (UNKNOWN_VERIFIABLE)

Add-ons the skill identified but could not verify against the target Kubernetes
version. The user must check these manually before upgrading.

| Add-on | Version | URL(s) Consulted | Why Unverified |
|--------|---------|------------------|----------------|
| [name] | [ver] | [url] | [e.g., page 404, no compat matrix found, ambiguous wording] |

#### Unidentified Workloads (UNKNOWN_UNIDENTIFIED)

Workloads that appear to be add-ons (based on namespace or shape) but could not be
identified. The user likely knows what these are — please review and confirm
compatibility with the target version manually.

| Kind | Name | Namespace | Image | Labels |
|------|------|-----------|-------|--------|
| [Deployment/DaemonSet/StatefulSet] | [name] | [ns] | [full image:tag] | [key labels present] |

### Node Group Summary

| Node Group | Version | AMI Type | Instances | Skew | Status |
|------------|---------|----------|-----------|------|--------|
| [name] | [ver] | [ami] | [min/max] | [N] | ✅/⚠️/❌ |

### Workload Risk Summary

| Risk | Severity | Count | Details |
|------|----------|-------|---------|
| Single replica deployments | HIGH | [N] | [names] |
| Missing PDBs | MEDIUM | [N] | [names] |
| Missing readiness probes | MEDIUM | [N] | [names] |
| Missing resource requests | HIGH | [N]% | [percentage] |

---

## Upgrade Plan

[Step-by-step upgrade sequence with pre-filled commands.]

### Pre-Upgrade Checklist
- [ ] All blockers resolved
- [ ] Add-ons updated to compatible versions
- [ ] Node groups ready (AL2023/Bottlerocket)
- [ ] PDBs in place for critical workloads
- [ ] Backup/snapshot taken

### Step 1: Update Add-ons (if needed)
```bash
aws eks update-addon --cluster-name [CLUSTER] --addon-name [ADDON] --addon-version [VERSION] --region [REGION]
```

### Step 2: Upgrade Control Plane
```bash
aws eks update-cluster-version --name [CLUSTER] --kubernetes-version [TARGET] --region [REGION]
```

### Step 3: Monitor Upgrade Progress
```bash
aws eks describe-update --name [CLUSTER] --update-id [UPDATE_ID] --region [REGION]
```

### Step 4: Upgrade Node Groups
```bash
aws eks update-nodegroup-version --cluster-name [CLUSTER] --nodegroup-name [NODEGROUP] --region [REGION]
```

### Step 5: Verify
```bash
kubectl get nodes
kubectl get pods -A | grep -v Running | grep -v Completed
```

---

## AWS Reference Links

[All links verified via web search or AWS documentation. Do NOT fabricate URLs.]
```

## Step 5: Look Up AWS References

Use web search or AWS documentation to find verified URLs. Prefer:
- `https://docs.aws.amazon.com/eks/latest/best-practices/`
- `https://docs.aws.amazon.com/eks/latest/userguide/`
- `https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html`

Do NOT fabricate deep-link URLs. When in doubt, link to the broad section page.

## Step 6: Write the Report File

Write to the workspace root.

## Step 7: Offer HTML Conversion

After writing the markdown report, ask:
*"Would you like me to convert the report to HTML? Run: `python3 tools/md_to_html.py <report-filename>.md`"*

Do NOT generate HTML manually. Always use the conversion script.
