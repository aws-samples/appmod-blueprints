# Breaking Changes Detection

## Purpose
Identify version-specific breaking changes that affect ACTUAL resources in the cluster. Only flag a breaking change if the cluster has resources that will be impacted.

## Principle
Every breaking change entry must be written in consultant-advisory style:
- **What we found** in YOUR cluster and why it matters
- **Real-world impact** if not addressed before upgrade
- **Concrete remediation** with commands where applicable

Do NOT list generic Kubernetes release notes. Only report changes that affect resources actually present in the cluster.

## Version-Specific Breaking Changes

### Target >= 1.25: PodSecurityPolicy Removed

**Check:** List PodSecurityPolicy resources via Kubernetes API
- If PSPs exist → HIGH severity. PSPs will cease to exist after upgrade.
- Remediation: Migrate to Pod Security Standards (PSS) by labeling namespaces: `kubectl label namespace <ns> pod-security.kubernetes.io/enforce=restricted`

### Target >= 1.29: FlowSchema API v1beta2 Removed

**Check:** Scan cluster resources for `apiVersion: flowcontrol.apiserver.k8s.io/v1beta2`
- Look at FlowSchema and PriorityLevelConfiguration resources
- If found → MEDIUM severity. Update to `flowcontrol.apiserver.k8s.io/v1`

### Target >= 1.32: FlowSchema API v1beta3 Removed

**Check:** Scan for `apiVersion: flowcontrol.apiserver.k8s.io/v1beta3`
- If found → HIGH severity. Update to `flowcontrol.apiserver.k8s.io/v1`

### Target >= 1.32: Anonymous Auth Restricted

**Always flag** (MEDIUM severity) — affects all clusters upgrading to 1.32+.
- Anonymous requests only allowed to /healthz, /livez, /readyz
- Check: `kubectl get clusterrolebindings -o json | jq '.items[] | select(.subjects[]?.name=="system:unauthenticated")'`
- Impact: Monitoring tools or LB health checks hitting non-health endpoints will get 401

### Target >= 1.33: Endpoints API Deprecated

**Check:** List Endpoints resources (exclude the default `kubernetes` endpoint)
- If custom Endpoints exist → MEDIUM severity
- Remediation: Migrate to EndpointSlices API (`discovery.k8s.io/v1`)

### Target >= 1.33: AL2 AMI Not Available

**Check:** List nodes → inspect `status.nodeInfo.kernelVersion` for `amzn2` or `osImage` for `Amazon Linux 2`
- If AL2 nodes found → HIGH severity. Cannot create new AL2 node groups for 1.33+
- Remediation: Migrate to AL2023 or Bottlerocket BEFORE upgrading control plane

### Target >= 1.34: AppArmor Deprecated

**Check:** Scan deployments/daemonsets/statefulsets for AppArmor annotations in pod template
- If found → MEDIUM severity
- Remediation: Migrate to seccomp profiles

### Target >= 1.35: Cgroup v1 Support Removed

**Always flag** (HIGH severity) for 1.35 targets.
- kubelet refuses to start on cgroup v1 nodes unless `failCgroupV1=false`
- AL2 uses cgroup v1 by default; AL2023 and Bottlerocket use cgroup v2
- Check node OS to determine impact

### Target >= 1.35: Containerd 1.x End of Support

**Check:** List nodes → inspect `status.nodeInfo.containerRuntimeVersion`
- If any node shows containerd 1.x → MEDIUM severity
- Last release supporting containerd 1.x; next version requires 2.0+

### Target >= 1.35: Ingress NGINX Retired

**Check:** List deployments/daemonsets with `ingress-nginx` or `nginx-ingress` in name
- If found → HIGH severity. No more security patches.
- Remediation: Migrate to Gateway API or AWS Load Balancer Controller

### Target == 1.35: IPVS Proxy Mode Deprecated

**Check:** Read kube-proxy ConfigMap → check `mode` field
- If `mode: ipvs` AND target is exactly 1.35 → MEDIUM severity. Deprecated; removed in 1.36.
- Remediation: Switch to iptables or nftables mode before upgrading to 1.36.

### Target >= 1.35: --pod-infra-container-image Flag Removed

**Always flag** (LOW severity) for 1.35 targets.
- Affects custom AMIs with this kubelet flag in bootstrap scripts
- EKS-managed AMIs are not affected

### Target >= 1.36: IPVS Proxy Mode Removed

**Check:** Read kube-proxy ConfigMap → check `mode` field
- If `mode: ipvs` → HIGH severity. IPVS mode is removed in 1.36 — kube-proxy will fail to
  start in this mode after the upgrade, breaking Service routing cluster-wide.
- Remediation: Switch to iptables or nftables mode BEFORE upgrading the control plane.

### Target >= 1.36: gitRepo Volume Removed

**Check:** Scan pod templates (Deployments, DaemonSets, StatefulSets, Jobs, CronJobs, bare Pods)
for `spec.volumes[].gitRepo`.
- If found → HIGH severity. The `gitRepo` volume type is permanently disabled in 1.36. The API
  still accepts the spec, but the kubelet refuses to run the pod and returns an error — so the
  workload will fail to start on 1.36 nodes.
- Remediation: Migrate to an initContainer that clones the repo, or a git-sync sidecar, before
  upgrading. See KEP-5040.

### Target >= 1.36: Strict IP/CIDR Validation

**Check:** Scan manifests/resources for IP or CIDR fields with non-canonical notation —
leading zeros (e.g., `010.000.000.005`) or ambiguous CIDR (e.g., `192.168.0.5/24` instead of
`192.168.0.0/24`). Common in Services, NetworkPolicies, and custom configs.
- If found → MEDIUM severity. The `StrictIPCIDRValidation` feature gate is on by default for
  built-in API kinds in 1.36. Existing stored objects are preserved (validation ratcheting),
  but new creates/updates with non-canonical values are rejected. Does NOT apply to custom
  resource kinds.
- Remediation: Update manifests, Helm charts, and automation to canonical IP/CIDR format before
  upgrading. See KEP-4858.

### Target >= 1.36: SELinux Volume Labeling GA

**Check:** Only relevant on SELinux-enforcing nodes. Look for pods sharing a single volume
between privileged and unprivileged containers.
- If SELinux is enforced AND shared volumes exist → MEDIUM severity. Faster SELinux volume
  labeling now defaults to all volumes (using `mount -o context` instead of recursive
  relabeling). Sharing a volume between privileged and unprivileged pods on the same node may
  break.
- Remediation: Audit clusters and set the `seLinuxChangePolicy` field and SELinux volume labels
  correctly on affected pods before upgrading.

### Target >= 1.36: Service externalIPs Deprecated

**Check:** Scan Services for a non-empty `spec.externalIPs` field.
- If found → LOW severity. `externalIPs` is deprecated in 1.36 (full removal planned for 1.43).
  Creating/updating such Services produces deprecation warnings but still works.
- Remediation: Plan migration to LoadBalancer Services, NodePort, or Gateway API. See KEP-5707.

### Target > 1.36: Live Lookup Required

This file does not cover breaking changes for versions beyond 1.36. If the target version
is > 1.36, you MUST perform a live lookup before reporting "no breaking changes found."

**How to check:**
1. Search AWS docs: `search_documentation` for "EKS Kubernetes <target> breaking changes"
2. Search AWS docs: `search_documentation` for "Kubernetes <target> removed APIs"
3. Fetch the Kubernetes changelog: `read_documentation` on the K8s CHANGELOG for the target
   minor version (e.g., CHANGELOG-1.37.md)
4. Check for EKS-specific changes: `search_documentation` for "EKS <target> release notes"

**If no breaking changes are found after live lookup:** Report "No breaking changes identified
for <target> based on available documentation" with a note that the user should re-check closer
to their upgrade date as documentation may be updated.

**If live sources are unreachable:** Report "Breaking changes for <target> could not be verified —
AWS documentation unavailable" with MEDIUM severity. Do NOT assume no breaking changes exist.

## Score Impact

> **Canonical scoring is defined in `references/report-generation.md` §Category 1 (Breaking Changes).**

| Severity | Per-item Deduction | Max Category |
|----------|-------------------|--------------|
| HIGH | 10 pts | 25 pts total |
| MEDIUM | 4 pts | |
| LOW | 2 pts | |
