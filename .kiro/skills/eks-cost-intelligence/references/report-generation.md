# Report Generation

> **Part of:** [eks-cost-intelligence](../SKILL.md)
> **Purpose:** Deterministic scoring algorithm, dimension weights, classification bands, SKIPPED dimension handling, and the complete markdown report template

---

## Scoring Algorithm

The Cost Score starts at 100 and applies severity-weighted deductions per dimension. The algorithm is deterministic: the same set of findings always produces the same score.

### Dimension Weights (Max Deductions)

| Dimension | Weight (Max Deduction) |
|-----------|----------------------|
| Compute Efficiency | 25 |
| Spot/Graviton Adoption | 20 |
| Networking Costs | 15 |
| Storage Costs | 15 |
| Observability Costs | 10 |
| Idle Resources | 15 |
| **Total** | **100** |

### Severity-Weighted Deduction Formulas

Each finding contributes a deduction based on its severity and the dimension's max deduction:

| Severity | Deduction per Finding | Formula |
|----------|----------------------|---------|
| CRITICAL | 60% of max_deduction | `dimension.max_deduction × 0.6` |
| HIGH | 30% of max_deduction | `dimension.max_deduction × 0.3` |
| MEDIUM | 15% of max_deduction | `dimension.max_deduction × 0.15` |
| LOW | 5% of max_deduction | `dimension.max_deduction × 0.05` |

**Concrete examples by dimension:**

| Dimension | Max | CRITICAL | HIGH | MEDIUM | LOW |
|-----------|-----|----------|------|--------|-----|
| Compute Efficiency | 25 | 15.0 | 7.5 | 3.75 | 1.25 |
| Spot/Graviton Adoption | 20 | 12.0 | 6.0 | 3.0 | 1.0 |
| Networking Costs | 15 | 9.0 | 4.5 | 2.25 | 0.75 |
| Storage Costs | 15 | 9.0 | 4.5 | 2.25 | 0.75 |
| Observability Costs | 10 | 6.0 | 3.0 | 1.5 | 0.5 |
| Idle Resources | 15 | 9.0 | 4.5 | 2.25 | 0.75 |

### Deduction Cap Rule

Each dimension's actual deduction is **capped** at its max_deduction. Multiple findings within a dimension accumulate but cannot exceed the cap:

```
actual_deduction = min(sum_of_finding_deductions, dimension.max_deduction)
```

### SKIPPED Dimension Handling

When a dimension cannot be assessed (missing data source, insufficient permissions):

- The dimension's status is set to `SKIPPED`
- The dimension contributes **zero deduction** to the total score
- The dimension is **excluded from scoring** entirely (not penalized)
- The report notes the exclusion with the reason and remediation steps

### Complete Pseudocode

```
score = 100

for each dimension in [compute, spot_graviton, networking, storage, observability, idle]:
    if dimension.status == SKIPPED:
        dimension.actual_deduction = 0
        continue
    
    deduction = 0
    for each finding in dimension.findings:
        if finding.severity == CRITICAL: deduction += dimension.max_deduction * 0.6
        if finding.severity == HIGH:     deduction += dimension.max_deduction * 0.3
        if finding.severity == MEDIUM:   deduction += dimension.max_deduction * 0.15
        if finding.severity == LOW:      deduction += dimension.max_deduction * 0.05
    
    dimension.actual_deduction = min(deduction, dimension.max_deduction)

total_deductions = sum(d.actual_deduction for d in dimensions)
score = max(0, 100 - total_deductions)
```

---

## Classification Bands

| Score Range | Classification | Meaning |
|-------------|---------------|---------|
| 90–100 | OPTIMIZED | Cluster is well-optimized; minimal waste detected |
| 75–89 | GOOD | Minor optimization opportunities exist |
| 60–74 | FAIR | Moderate waste; several actionable improvements available |
| 40–59 | NEEDS_WORK | Significant cost inefficiencies across multiple dimensions |
| 0–39 | CRITICAL | Severe waste; immediate action recommended |

### Classification Logic

```
if score >= 90: classification = "OPTIMIZED"
elif score >= 75: classification = "GOOD"
elif score >= 60: classification = "FAIR"
elif score >= 40: classification = "NEEDS_WORK"
else:            classification = "CRITICAL"
```

### Status Icons for Report

| Classification | Icon | Color |
|---------------|------|-------|
| OPTIMIZED | ✅ | Green |
| GOOD | ✅ | Blue |
| FAIR | ⚠️ | Yellow |
| NEEDS_WORK | ⚠️ | Orange |
| CRITICAL | ❌ | Red |

### Dimension Status Icons

| Actual Deduction | Icon | Meaning |
|-----------------|------|---------|
| 0 | ✅ | No issues found |
| 1 – 50% of max | ⚠️ | Minor issues |
| > 50% of max | ❌ | Significant issues |
| SKIPPED | ⏭️ | Not assessed |

---

## Report Filename Pattern

```
EKS-Cost-Intelligence-{cluster}-{YYYY-MM-DD}-{HHMM}.md
```

- `{cluster}` — the EKS cluster name as returned by `aws eks describe-cluster`
- `{YYYY-MM-DD}` — assessment date in ISO format
- `{HHMM}` — assessment time in 24-hour format (hours and minutes, no separator)

**Examples:**
- `EKS-Cost-Intelligence-prod-api-2024-11-15-0930.md`
- `EKS-Cost-Intelligence-staging-cluster-2024-12-01-1445.md`

---

## Recommendation Sort Order

Recommendations in the report are sorted by:

1. **Severity** (descending): CRITICAL → HIGH → MEDIUM → LOW
2. **Monthly savings** (descending within each severity level): highest savings first

---

## Complete Report Template

```markdown
# EKS Cost Intelligence Report

| Field | Value |
|-------|-------|
| Cluster | {cluster_name} |
| Region | {region} |
| Assessment Date | {YYYY-MM-DD HH:MM} |
| Total Estimated Spend | ${total_spend}/month |
| Data Sources | {data_sources_list} |

---

## Cost Score: {score}/100 — {classification}

{executive_summary: 2-3 sentences summarizing the cluster's cost posture, top waste
areas, and projected total savings if all recommendations are implemented.}

### Score Breakdown

| Dimension | Max | Deduction | Status | Top Finding |
|-----------|-----|-----------|--------|-------------|
| Compute Efficiency | 25 | -{compute_deduction} | {status_icon} | {top_finding_summary} |
| Spot/Graviton Adoption | 20 | -{spot_graviton_deduction} | {status_icon} | {top_finding_summary} |
| Networking Costs | 15 | -{networking_deduction} | {status_icon} | {top_finding_summary} |
| Storage Costs | 15 | -{storage_deduction} | {status_icon} | {top_finding_summary} |
| Observability Costs | 10 | -{observability_deduction} | {status_icon} | {top_finding_summary} |
| Idle Resources | 15 | -{idle_deduction} | {status_icon} | {top_finding_summary} |
| **Total** | **100** | **-{total_deduction}** | | **Score: {score}** |

---

## Prioritized Recommendations

| # | Finding | Dimension | Resource | Monthly Savings | Effort | Severity |
|---|---------|-----------|----------|-----------------|--------|----------|
| 1 | {description} | {dimension} | {resource} | ${savings} | {effort} | {severity} |
| 2 | {description} | {dimension} | {resource} | ${savings} | {effort} | {severity} |
| ... | ... | ... | ... | ... | ... | ... |

**Total projected savings: ${total_monthly_savings}/month (${total_annual_savings}/year)**

---

## Findings by Dimension

### Compute Efficiency

{If ASSESSED:}

| Finding | Resource | Monthly Waste | Savings | Effort | Severity |
|---------|----------|---------------|---------|--------|----------|
| {finding_description} | {resource} | ${waste} | ${savings} | {effort} | {severity} |

#### Remediation

**{finding_title}**
{remediation_snippet}

---

{If SKIPPED:}

### {Dimension Name} — SKIPPED

**Reason:** {specific error message, e.g., "metrics-server not available"}
**Impact:** {what findings are missing, e.g., "CPU/memory utilization analysis unavailable"}
**Remediation:** {how to enable the missing data source}

---

### Spot/Graviton Adoption

{Same structure as Compute Efficiency}

### Networking Costs

{Same structure as Compute Efficiency}

### Storage Costs

{Same structure as Compute Efficiency}

### Observability Costs

{Same structure as Compute Efficiency}

### Idle Resources

{Same structure as Compute Efficiency}

---

## Methodology & Confidence Notes

### Data Sources Used

| Source | Status | Impact |
|--------|--------|--------|
| Cost Explorer | {Available/Unavailable} | {Dollar-accurate spend data / Node-based estimation used} |
| Container Insights | {Available/Unavailable} | {Utilization-based analysis / Request-only analysis} |
| Kubernetes API | {Available/Unavailable} | {Resource inventory and configuration} |
| EC2 API | {Available/Unavailable} | {Instance types and pricing} |

### Estimation Methods

- **Cost attribution:** {method used — Cost Explorer tags, Split Cost Allocation, or node-based estimation}
- **Utilization data:** {source — Container Insights metrics, metrics-server, or request-only}
- **Savings estimates:** Conservative projections with {X}% confidence buffer applied

### Confidence Level

| Level | Meaning |
|-------|---------|
| High | Cost Explorer + Container Insights available; dollar-accurate findings |
| Medium | Partial data; some estimates based on node-level pricing |
| Low | Node-based estimation only; findings are directional |

---

*This report was generated by a Kiro skill provided as sample code for educational
and demonstration purposes only. Findings should be reviewed and validated before
acting on them. See the project's README and LICENSE for full terms.*
```

---

## Worked Example

### Scenario: Production cluster with moderate waste

**Findings collected:**
- Compute: 1 HIGH (over-provisioned pods, $847/mo waste)
- Spot/Graviton: 1 HIGH (no Spot usage, $380/mo), 1 MEDIUM (low Graviton, $200/mo)
- Networking: 1 MEDIUM (missing VPC endpoints, $150/mo)
- Storage: 1 MEDIUM (gp2 volumes, $36/mo)
- Observability: SKIPPED (Container Insights not enabled)
- Idle: 1 HIGH (orphaned LB, $432/mo)

**Score calculation:**

```
Compute:
  deduction = 25 × 0.3 = 7.5 (one HIGH finding)
  actual_deduction = min(7.5, 25) = 7.5

Spot/Graviton:
  deduction = 20 × 0.3 + 20 × 0.15 = 6.0 + 3.0 = 9.0 (one HIGH + one MEDIUM)
  actual_deduction = min(9.0, 20) = 9.0

Networking:
  deduction = 15 × 0.15 = 2.25 (one MEDIUM finding)
  actual_deduction = min(2.25, 15) = 2.25

Storage:
  deduction = 15 × 0.15 = 2.25 (one MEDIUM finding)
  actual_deduction = min(2.25, 15) = 2.25

Observability:
  status = SKIPPED → actual_deduction = 0

Idle:
  deduction = 15 × 0.3 = 4.5 (one HIGH finding)
  actual_deduction = min(4.5, 15) = 4.5

Total deductions = 7.5 + 9.0 + 2.25 + 2.25 + 0 + 4.5 = 25.5
Score = max(0, 100 - 25.5) = 74.5 → rounds to 74
Classification: FAIR (60–74)
```

### Scenario: Deduction cap in action

If Compute has 1 CRITICAL + 1 HIGH + 2 MEDIUM findings:

```
deduction = 25 × 0.6 + 25 × 0.3 + 25 × 0.15 + 25 × 0.15
          = 15.0 + 7.5 + 3.75 + 3.75
          = 30.0

actual_deduction = min(30.0, 25) = 25  ← capped at max_deduction
```

The dimension cannot lose more than its weight regardless of how many findings exist.
