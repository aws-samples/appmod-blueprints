# Workload Risks

## Purpose
Assess workload resilience during the upgrade process. These are not upgrade blockers but affect the safety and smoothness of the upgrade.

## CRITICAL: Systematic Enumeration Rule

You MUST follow this process to avoid miscounting. Do NOT count from memory.

### Step A: Build the Master Workload Table

Before checking ANY risk, build a single table of ALL workloads in non-system namespaces.

**Non-system namespaces to EXCLUDE:** kube-system, kube-public, kube-node-lease, karpenter,
amazon-cloudwatch, amazon-guardduty, aws-observability.

**Workload types to INCLUDE:** Deployments, StatefulSets, DaemonSets.

**How to build the table:**
1. List ALL Deployments across all namespaces
2. List ALL StatefulSets across all namespaces
3. List ALL DaemonSets across all namespaces
4. Filter out workloads in system namespaces listed above
5. For EACH remaining workload, extract from its spec:
   - `name`, `namespace`, `kind` (Deployment/StatefulSet/DaemonSet)
   - `replicas` (for Deployments/StatefulSets; DaemonSets run on all nodes)
   - `strategy.type` (Deployments only: RollingUpdate or Recreate)
   - For EACH container: `readinessProbe` (present/absent), `livenessProbe` (present/absent),
     `resources.requests.cpu` (value or absent), `resources.requests.memory` (value or absent)

**Output format — you MUST produce this table before proceeding:**

```
| # | Name | Kind | NS | Replicas | Strategy | Probes | Requests | Notes |
|---|------|------|----|----------|----------|--------|----------|-------|
| 1 | app-a | Deployment | default | 3 | RollingUpdate | ✅ readiness+liveness | ✅ cpu+mem | |
| 2 | app-b | Deployment | default | 1 | Recreate | ❌ none | ❌ none | single-replica, recreate |
| 3 | mon-agent | DaemonSet | default | N/A | N/A | ❌ none | ✅ cpu+mem | |
```

### Step B: Check Each Risk Against the Table

Walk through each check below. For every finding, reference the row number from the table.
This prevents miscounting and ensures no workload is missed.

## Checks to Execute

### 6.1 — Single Replica Deployments

**Why this matters:** Node drains during upgrade will cause downtime for single-replica workloads.

**How to check:** From the master table, filter for `kind == Deployment AND replicas == 1`.

**Rating:** Each match = HIGH severity (3 pts in score).

### 6.2 — Missing Pod Disruption Budgets

**Why this matters:** Without PDBs, node drain can evict all pods simultaneously.

**How to check:**
1. List PodDisruptionBudgets across all namespaces
2. From the master table, filter for `kind == Deployment AND replicas > 1` in non-system namespaces
3. Cross-reference: which multi-replica deployments have NO matching PDB?
4. Check for **drain-blocking PDBs** (see 6.2b below)

**IMPORTANT:** Only flag missing PDBs for workloads with replicas > 1. A PDB on a single-replica
deployment is meaningless — do NOT flag single-replica workloads for missing PDBs.

**Rating:** Each missing PDB on multi-replica deployment = MEDIUM severity (1 pt).

### 6.2b — Drain-Blocking PDBs (upgrade stall risk)

**Why this matters:** A PDB that allows zero disruptions will cause `kubectl drain` to hang
indefinitely during node group upgrades. The node group upgrade will eventually time out
(typically after 1+ hours), failing the rolling update. This is the #1 cause of "upgrade stuck"
support tickets.

**How to check:**
1. For each PDB found in step 6.2, inspect:
   - `status.disruptionsAllowed` == 0, OR
   - `spec.maxUnavailable` == 0, OR
   - `spec.minAvailable` == total replicas of the target workload
2. If any of the above conditions is true AND the target workload has pods running on
   nodes that will be drained during the upgrade → flag it.

**Report message (use this exact framing):**

> **⚠️ PDB may stall node group upgrade**
>
> `<pdb-name>` in namespace `<ns>` currently allows 0 disruptions for `<workload-name>`.
> During a node group rolling update, EKS drains each node before replacing it. If this PDB
> cannot be satisfied (e.g., not enough capacity on remaining nodes to reschedule pods), the
> drain will hang until the node group upgrade times out (~1 hour).
>
> **Before upgrading:**
> 1. Verify sufficient cluster capacity exists for pods to reschedule to other nodes
> 2. Consider temporarily relaxing the PDB: `kubectl patch pdb <name> -n <ns> -p '{"spec":{"maxUnavailable":1}}'`
> 3. Or ensure the workload has enough replicas spread across multiple nodes
>
> **If you skip this:** The node group upgrade will likely time out and require manual
> intervention. The control plane upgrade itself will succeed, but node rotation will stall.

**Rating:** Each drain-blocking PDB = MEDIUM severity (2 pts).

**This is NOT a hard blocker** because:
- The control plane upgrade itself will succeed
- The issue only manifests during node group rolling update
- It can be resolved mid-upgrade by patching the PDB
- But it WILL cause significant delay and potential manual intervention if not addressed

### 6.3 — Missing Health Probes

**Why this matters:** Without readiness probes, traffic is sent to pods before they're ready.

**How to check:** From the master table, filter for workloads where ANY container is missing
a `readinessProbe`. Count ALL workload types (Deployments, StatefulSets, AND DaemonSets).

**Rating:** Each workload missing probes = MEDIUM severity (1 pt).

### 6.4 — Missing Resource Requests

**Why this matters:** Without resource requests, pods can't be properly rescheduled during node drains.

**How to check:** From the master table, filter for workloads where ANY container is missing
`resources.requests.cpu` OR `resources.requests.memory`.

**IMPORTANT:** Check the ACTUAL spec data. Do NOT assume a workload has or lacks requests
without verifying. If the deployment spec shows `requests: {cpu: "100m", memory: "128Mi"}`,
that workload HAS requests — do not flag it.

**Rating:** Each workload missing requests = MEDIUM severity (1 pt).

### 6.5 — Recreate Update Strategy

**Why this matters:** Recreate strategy causes full downtime during any rollout.

**How to check:** From the master table, filter for `kind == Deployment AND strategy == Recreate`.

**Rating:** Each match = HIGH severity (3 pts in score).

### 6.6 — Graceful Shutdown Configuration

**Why this matters:** Without preStop hooks, there's a race condition during node drain.

**How to check:**
1. From the master table, identify workloads exposed via Services (especially LoadBalancer type)
2. Check if those workloads have `lifecycle.preStop` hooks
3. Check `terminationGracePeriodSeconds`

**Rating:** Missing preStop on externally-facing workloads = MEDIUM severity (1 pt).

## Step C: Compile Findings with Row References

After all checks, produce a findings list that references the master table row numbers:

```
| Finding | Severity | Workloads (by row #) | Count |
|---------|----------|---------------------|-------|
| Single replica | HIGH | #2, #7 | 2 |
| Recreate strategy | HIGH | #2, #5 | 2 |
| Missing probes | MEDIUM | #2, #3, #5, #6, #8 | 5 |
| Missing requests | MEDIUM | #2, #6 | 2 |
```

This makes the count verifiable. If the count doesn't match the listed row numbers, something is wrong.

## Score Impact

> **Canonical scoring is defined in `references/report-generation.md` §Category 6 (Workload Risks).**

| Finding | Deduction |
|---------|-----------|
| High-severity workload risk (single replica, Recreate) | 3 pts each (sub-cap 8) |
| Medium-severity workload risk (missing probes, requests, PDBs) | 1 pt each (sub-cap 4) |
| Drain-blocking PDB (disruptionsAllowed == 0) | 2 pts each (sub-cap 4) |
| Max category | 10 pts |
