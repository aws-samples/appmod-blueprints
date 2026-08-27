# EKS Cluster Upgrade Best Practices

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Upgrade planning, in-place and blue-green strategies, add-on management, API deprecation detection, and version support for Amazon EKS

---

## Table of Contents

1. [Upgrade Planning](#upgrade-planning)
2. [In-Place Upgrade Procedure](#in-place-upgrade-procedure)
3. [Blue-Green Cluster Upgrade](#blue-green-cluster-upgrade)
4. [Add-On Version Management](#add-on-version-management)
5. [API Deprecation Detection](#api-deprecation-detection)
6. [Data Plane Upgrades](#data-plane-upgrades)
7. [Version Support Policy](#version-support-policy)
8. [Bottlerocket-Specific Guidance](#bottlerocket-specific-guidance)
9. [Emergency Rollback Procedures](#emergency-rollback-procedures)

---

## Upgrade Planning

### Pre-Upgrade Checklist

| Step | Tool | Action |
|------|------|--------|
| 1. Check Cluster Insights | AWS Console / API | Review upgrade readiness insights |
| 2. Detect deprecated APIs | Pluto, kubent, metrics | Scan manifests and cluster for removed APIs |
| 3. Verify add-on compatibility | EKS add-on matrix | Check add-on versions support target K8s |
| 4. Verify infra requirements | AWS CLI | 5+ free IPs in cluster subnets, IAM role exists, KMS key accessible |
| 5. Enable control plane logging | EKS API | Capture logs/errors during upgrade |
| 6. Review version-specific changes | EKS release notes | Check for feature removals (PSP, Dockershim, in-tree storage) |
| 7. Test in non-prod | EKS | Upgrade staging/dev cluster first |
| 8. Verify PDB configuration | kubectl | Ensure PDBs won't block node drains |
| 9. Back up cluster state | Velero / GitOps | Full cluster backup before upgrade |
| 10. Review Karpenter compatibility | Release notes | Verify Karpenter supports target version |

### Verify Infrastructure Requirements

AWS requires these resources to complete the control plane upgrade:

```bash
# 1. Verify at least 5 free IPs in cluster subnets
CLUSTER=<cluster-name>
aws ec2 describe-subnets --subnet-ids \
  $(aws eks describe-cluster --name ${CLUSTER} \
  --query 'cluster.resourcesVpcConfig.subnetIds' --output text) \
  --query 'Subnets[*].[SubnetId,AvailabilityZone,AvailableIpAddressCount]' \
  --output table

# 2. Verify EKS IAM role exists with correct trust policy
ROLE_ARN=$(aws eks describe-cluster --name ${CLUSTER} \
  --query 'cluster.roleArn' --output text)
aws iam get-role --role-name ${ROLE_ARN##*/} \
  --query 'Role.AssumeRolePolicyDocument'
# Should show: Principal: eks.amazonaws.com, Action: sts:AssumeRole

# 3. If secret encryption is enabled, verify KMS key access
aws eks describe-cluster --name ${CLUSTER} \
  --query 'cluster.encryptionConfig'
```

If cluster subnets are running low on IPs, add new subnets in the same AZs via `UpdateClusterConfiguration` before upgrading. Consider associating additional CIDR blocks to expand the IP pool.

### Enable Control Plane Logging

Enable logging **before** the upgrade to capture any errors during the process:

```bash
aws eks update-cluster-config --name my-cluster \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'
```

### EKS Cluster Insights

```bash
# List upgrade insights with issues
aws eks list-insights \
  --cluster-name my-cluster \
  --filter 'statuses=ERROR,WARNING'

# Get detailed remediation advice for a specific insight
aws eks describe-insight \
  --cluster-name my-cluster \
  --id <insight-id>
# Returns: affected resources, deprecated APIs, recommended actions
```

Cluster Insights automatically detects:
- Deprecated API usage in your cluster (last 30 days)
- Add-on compatibility issues
- Known upgrade blockers

If an insight shows `"status": ERROR`, you **must** resolve it before upgrading.

### Upgrade Strategy Decision

| Factor | In-Place Upgrade | Blue-Green Upgrade |
|--------|-----------------|-------------------|
| **Downtime risk** | Minutes (control plane) | Near-zero |
| **Rollback** | Not possible for control plane | DNS/LB switch back |
| **Cost** | No extra cost | 2× cluster cost during migration |
| **Complexity** | Low-Medium | High |
| **State migration** | None needed | Must migrate PVs, DNS, state |
| **Version jump** | One minor at a time | Can skip versions (new cluster) |
| **Use when** | Most upgrades | Critical workloads, major version jumps |

---

## In-Place Upgrade Procedure

### Upgrade Sequence (Strict Order)

```
1. Control Plane    (AWS-managed, ~15-30 min)
     ↓
2. EKS Add-ons     (VPC CNI, CoreDNS, kube-proxy, EBS CSI)
     ↓
3. Data Plane       (Node groups, Karpenter nodes, or Fargate restart)
     ↓
4. Custom Add-ons   (Ingress controller, cert-manager, monitoring, etc.)
     ↓
5. Update kubectl   (Match client to cluster version)
```

### Step 1: Upgrade Control Plane

```bash
# Check current version
aws eks describe-cluster --name my-cluster \
  --query 'cluster.version'

# Upgrade control plane (one minor version at a time)
aws eks update-cluster-version \
  --name my-cluster \
  --kubernetes-version 1.31

# Monitor upgrade status
aws eks describe-update \
  --name my-cluster \
  --update-id <update-id>
```

**Key constraints:**
- Can only upgrade one minor version at a time (1.29 → 1.30, not 1.29 → 1.31)
- Control plane upgrade takes 15-30 minutes
- API server remains available during upgrade (brief API errors possible)
- Cannot rollback control plane version

### Step 2: Upgrade Add-ons

```bash
# Check current add-on versions
aws eks describe-addon --cluster-name my-cluster --addon-name vpc-cni
aws eks describe-addon --cluster-name my-cluster --addon-name coredns
aws eks describe-addon --cluster-name my-cluster --addon-name kube-proxy

# Upgrade each add-on
aws eks update-addon \
  --cluster-name my-cluster \
  --addon-name vpc-cni \
  --addon-version v1.18.0-eksbuild.1 \
  --resolve-conflicts OVERWRITE
```

**VPC CNI constraint:** When installed as an EKS managed add-on, VPC CNI can only be upgraded one minor version at a time (same as the cluster).

EKS add-ons are **not** automatically upgraded during a control plane upgrade — you must initiate each add-on update separately.

### Step 3: Upgrade Data Plane

**For Managed Node Groups:**

```bash
aws eks update-nodegroup-version \
  --cluster-name my-cluster \
  --nodegroup-name default \
  --kubernetes-version 1.31

# Monitor rolling update
aws eks describe-nodegroup \
  --cluster-name my-cluster \
  --nodegroup-name default \
  --query 'nodegroup.updateConfig'
```

**For EKS Auto Mode:** No action needed. After the control plane upgrade, Auto Mode incrementally updates managed nodes while respecting PDBs. Monitor to verify compliance with your operational requirements.

**For Karpenter:** See [Data Plane Upgrades](#data-plane-upgrades) section.

**For Fargate:** Redeploy workloads to pick up the new version. Identify Fargate pods:

```bash
kubectl get pods -A -o wide | grep fargate-
# Restart each deployment running on Fargate
kubectl rollout restart deployment <name> -n <namespace>
```

### Step 4: Update kubectl

After the cluster upgrade, update your kubectl client to match:

```bash
# Verify kubectl version matches cluster
kubectl version --short
```

### Ensure Availability During Upgrade

Configure PDBs and topology spread to prevent downtime during data plane rolling updates:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: myapp
spec:
  minAvailable: "80%"
  selector:
    matchLabels:
      app: myapp
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 10
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      topologySpreadConstraints:
      - maxSkew: 2
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: myapp
      - maxSkew: 2
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: myapp
```

Spreading across zones and hosts ensures pods migrate to new nodes automatically during rolling replacements.

---

## Blue-Green Cluster Upgrade

### When to Use Blue-Green

- Major version jumps (skipping multiple minor versions via new cluster)
- Zero-downtime requirement for the upgrade itself
- Significant architectural changes alongside version upgrade
- Compliance requirement for rollback capability

### Blue-Green Procedure

```
1. Create "green" cluster at target version
2. Deploy all workloads to green (via GitOps)
3. Run smoke tests on green cluster
4. Shift traffic gradually (DNS weighted / ALB weighted)
5. Monitor for issues
6. Decommission "blue" cluster after validation
```

### Traffic Shifting Patterns

| Method | Granularity | Rollback Speed |
|--------|------------|----------------|
| **Route 53 weighted routing** | Percentage-based | Fast (DNS TTL) |
| **ALB weighted target groups** | Percentage-based | Instant |
| **Global Accelerator** | Endpoint weights | Instant |
| **External DNS cutover** | All-or-nothing | DNS TTL dependent |

### Blue-Green Downsides to Consider

- **API endpoint and OIDC change** — all consumers (kubectl, CI/CD, IRSA trust policies) must be updated to the new cluster's endpoint
- **Load balancers and external DNS** cannot easily span both clusters simultaneously
- **2× cluster cost** during the migration period, which may also limit region EC2 capacity
- **Dependent workloads** need coordination to migrate together (e.g., services that call each other)
- **Stateful workloads** require backup/restore or shared storage (EFS, managed databases)

### Stateful Workload Migration

For workloads with PersistentVolumes:
1. Back up data with Velero or application-level backup
2. Restore in new cluster
3. For EBS: Snapshot → Create volume in new cluster's AZs
4. For EFS: Mount same file system from both clusters
5. For databases: Use managed service (RDS, DynamoDB) — no migration needed

**Note:** Velero backs up Kubernetes resources and PV data, but **not** AWS resources (IAM roles, security groups, VPC config). These must be recreated separately (Terraform/CloudFormation).

---

## Add-On Version Management

### Core EKS Add-Ons

| Add-On | Purpose | Update Priority |
|--------|---------|----------------|
| **vpc-cni** | Pod networking | High — update before node upgrade |
| **coredns** | Cluster DNS | High — update with control plane |
| **kube-proxy** | Service networking | High — update with control plane |
| **ebs-csi-driver** | EBS volumes | Medium — update after control plane |
| **efs-csi-driver** | EFS volumes | Medium — update after control plane |
| **eks-pod-identity-agent** | Pod Identity | Medium — update after control plane |

### Add-On Compatibility Matrix Check

```bash
# List compatible versions for an add-on
aws eks describe-addon-versions \
  --addon-name vpc-cni \
  --kubernetes-version 1.31 \
  --query 'addons[0].addonVersions[*].{Version:addonVersion,Default:compatibilities[0].defaultVersion}' \
  --output table
```

### Inventory All Components Using K8s API

Before upgrading, identify every component that uses the Kubernetes API directly:

```bash
# Find critical cluster components (often in *-system namespaces)
kubectl get ns | grep '-system'
```

Common components to verify compatibility: AWS LBC, Karpenter, Cluster Autoscaler, cert-manager, metrics-server, monitoring agents, ingress controllers, CSI drivers.

**Karpenter** is tightly coupled to the Kubernetes version — always check [Karpenter release notes](https://karpenter.sh/docs/upgrading/) for target version support.

**Cluster Autoscaler** must match the cluster minor version — upgrade it when you upgrade the cluster.

### Self-Managed Add-On Upgrades

For add-ons not managed by EKS (ingress controllers, cert-manager, etc.):
1. Check the add-on's compatibility matrix for the target K8s version
2. Upgrade the add-on before or after the control plane upgrade (per add-on docs)
3. Test in non-prod first

---

## API Deprecation Detection

### Detection Methods

| Method | Type | Best For |
|--------|------|----------|
| **EKS Cluster Insights** | AWS-managed | Live cluster — first check |
| **Prometheus metric** | Cluster metric | Continuous monitoring |
| **Audit log query** | CloudWatch Logs | Historical API usage |
| **Pluto** | CLI tool | CI/CD pipeline integration |
| **kube-no-trouble (kubent)** | CLI tool | Quick cluster scan |
| **kubectl convert** | Built-in | Manual manifest conversion |

### Monitor Deprecated API Usage (Prometheus)

The `apiserver_requested_deprecated_apis` metric (since K8s 1.19) tracks real-time usage of deprecated APIs:

```bash
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
# Example output:
# apiserver_requested_deprecated_apis{group="policy",removed_release="1.25",
#   resource="podsecuritypolicies",version="v1beta1"} 1
```

### Query Audit Logs for Deprecated API Calls

```bash
CLUSTER="<cluster_name>"
QUERY_ID=$(aws logs start-query \
  --log-group-name /aws/eks/${CLUSTER}/cluster \
  --start-time $(date -u --date="-30 minutes" "+%s") \
  --end-time $(date "+%s") \
  --query-string 'fields @message | filter `annotations.k8s.io/deprecated`="true"' \
  --query queryId --output text)

sleep 5
aws logs get-query-results --query-id $QUERY_ID
```

### Using Pluto

```bash
# Install
brew install FairwindsOps/tap/pluto

# Scan Helm releases in cluster
pluto detect-helm --target-versions k8s=v1.31

# Scan manifest files (more accurate — recommended for CI)
pluto detect-files -d manifests/ --target-versions k8s=v1.31

# Scan live cluster
pluto detect-api-resources --target-versions k8s=v1.31
```

### Using kube-no-trouble

```bash
sh -c "$(curl -sSL https://git.io/install-kubent)"
kubent --target-version 1.31
```

Scanning static manifests is generally more accurate than live cluster scanning (fewer false positives). Run `kubent`/`pluto` in CI pipelines to catch issues before deployment.

### Key API Removals by Version

| Version | Removed API | Replacement |
|---------|------------|-------------|
| **1.25** | PodSecurityPolicy | Pod Security Admission (PSA) |
| **1.25** | batch/v1beta1 CronJob | batch/v1 |
| **1.25** | Dockershim (CRI) | containerd (EKS Optimized AMI default) |
| **1.26** | flowcontrol.apiserver.k8s.io/v1beta1 | flowcontrol.apiserver.k8s.io/v1beta3 |
| **1.27** | storage.k8s.io/v1beta1 CSIStorageCapacity | storage.k8s.io/v1 |
| **1.29** | flowcontrol.apiserver.k8s.io/v1beta2 | flowcontrol.apiserver.k8s.io/v1 |
| **1.32** | flowcontrol.apiserver.k8s.io/v1beta3 | flowcontrol.apiserver.k8s.io/v1 |

### Feature-Specific Migration Guidance

**Dockershim removal (1.25):** EKS Optimized AMI for 1.25+ uses containerd, not Docker. If you mount the Docker socket (`/var/run/docker.sock`), detect dependencies with the [Detector for Docker Socket (DDS)](https://github.com/aws-containers/kubectl-detector-for-docker-socket) kubectl plugin before upgrading nodes.

**PodSecurityPolicy removal (1.25):** Migrate to built-in [Pod Security Standards (PSS)](https://docs.aws.amazon.com/eks/latest/userguide/pod-security-policy-removal-faq.html) or a policy-as-code solution (Kyverno, OPA/Gatekeeper) before upgrading to 1.25.

**In-tree storage driver deprecation (1.23):** Install the [Amazon EBS CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html) before upgrading to 1.23+ to avoid service interruption for EBS-backed workloads. The in-tree to CSI migration is enabled by default in EKS 1.23+.

### Convert Manifests

Use `kubectl convert` to automatically update API versions in manifest files:

```bash
kubectl-convert -f old-deployment.yaml --output-version apps/v1
```

---

## Data Plane Upgrades

### Version Skew Policy

| Control Plane Version | Supported kubelet Versions | Skew |
|----------------------|---------------------------|------|
| **≥ 1.28** | CP version minus 3 (e.g., 1.31 supports kubelet 1.28+) | n-3 |
| **< 1.28** | CP version minus 2 (e.g., 1.27 supports kubelet 1.25+) | n-2 |

This applies to MNG, self-managed nodes, and Fargate. However, keep AMI versions current for security — older kubelet versions may have unpatched CVEs.

### Karpenter Node Upgrades

**Automatic via drift detection:**

When you update the control plane version, Karpenter detects AMI drift and automatically replaces nodes:

1. Karpenter detects the node's AMI doesn't match the latest EKS-optimized AMI
2. Karpenter provisions a new node with the updated AMI
3. Karpenter cordons the old node
4. Karpenter drains the old node (respecting PDBs)
5. Pods reschedule on the new node
6. Old node is terminated

**Control drain speed with NodePool disruption settings:**

```yaml
spec:
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    budgets:
    - nodes: "10%"    # Max 10% of nodes disrupted at a time
    - nodes: "0"
      schedule: "0 9 * * 1-5"  # No disruptions during business hours
      duration: 8h
```

**Karpenter node expiry** as an alternative to drift — set `expireAfter` on the NodePool to automatically replace nodes after a time period, ensuring regular AMI refresh:

```yaml
spec:
  template:
    spec:
      expireAfter: 720h  # 30 days — nodes replaced with latest AMI
```

Karpenter does not add jitter to expiry — configure PDBs to prevent simultaneous expiration from disrupting workloads.

**Force immediate node replacement:**

```bash
kubectl annotate nodes --all karpenter.sh/voluntary-disruption=drifted --overwrite
```

### Managed Node Group Upgrades

```bash
# Rolling update (default strategy)
aws eks update-nodegroup-version \
  --cluster-name my-cluster \
  --nodegroup-name default

# Configure update behavior
aws eks update-nodegroup-config \
  --cluster-name my-cluster \
  --nodegroup-name default \
  --update-config '{"maxUnavailable": 1}'
  # Or: {"maxUnavailablePercentage": 33}
```

### Self-Managed Node Group Upgrades

For nodes deployed outside the EKS managed service, use your provisioning tool:

| Tool | Documentation |
|------|--------------|
| **eksctl** | [Nodegroup upgrade](https://eksctl.io/usage/nodegroup-upgrade/) — supports delete and drain |
| **Terraform (EKS Blueprints)** | [Self-managed node groups](https://aws-ia.github.io/terraform-aws-eks-blueprints/node-groups/#self-managed-node-groups) |
| **kOps** | [Updates and upgrades](https://kops.sigs.k8s.io/operations/updates_and_upgrades/) |

---

## Version Support Policy

### EKS Version Lifecycle

| Phase | Patching | Cost | Auto-upgrade? |
|-------|----------|------|----------------|
| **Standard support** | Security + bug fixes | Standard pricing | No |
| **Extended support** | Critical security only | Additional per-hour surcharge | No |
| **End of extended support** | None | N/A | Yes — AWS auto-upgrades at a time it chooses |

**Always get exact dates from the EKS API — do not compute them from release dates.** Standard and extended support windows have historically shifted; the API is the only trustworthy source.

```bash
aws eks describe-cluster-versions --region <region> \
  --query 'clusterVersions[*].[clusterVersion,status,endOfStandardSupportDate,endOfExtendedSupportDate]' \
  --output table
```

You can [disable extended support](https://docs.aws.amazon.com/eks/latest/userguide/disable-extended-support.html) so auto-upgrade happens at end of standard support instead.

### Planning Timeline

- **New K8s minor on EKS:** ~3 releases per year
- **End of standard support:** query the API per cluster version
- **End of extended support:** query the API per cluster version
- **After:** EKS auto-upgrades your cluster (may disrupt workloads)

**Recommendation:** Upgrade every 3-4 months to stay within standard support. Budget one upgrade cycle per quarter. Look beyond the next version — review upcoming K8s releases to identify major changes early (e.g., Dockershim removal was announced well before 1.25).

### Additional Upgrade Tools

| Tool | Purpose |
|------|---------|
| **[ClowdHaus eksup](https://clowdhaus.github.io/eksup/)** | CLI to analyze cluster for pre-upgrade issues |
| **[GoNoGo](https://github.com/FairwindsOps/GoNoGo)** | Determine upgrade confidence for cluster add-ons |
| **[eksctl](https://eksctl.io/usage/cluster-upgrade/)** | Manage CP, add-ons, and worker node upgrades |

✅ DO:
- Subscribe to EKS version release notifications
- Maintain a documented upgrade runbook
- Test upgrades in non-prod environments first
- Use Cluster Insights to validate readiness
- Enable control plane logging before upgrading
- Use Managed Node Groups, Karpenter, or Auto Mode to simplify data plane upgrades
- Review the [EKS release calendar](https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html#kubernetes-release-calendar)

❌ DON'T:
- Skip more than 2 minor versions behind current
- Rely on extended support as a permanent solution (extra cost, then auto-upgrade)
- Upgrade production without testing in staging first
- Ignore API deprecation warnings from Cluster Insights
- Forget to restart Fargate deployments after control plane upgrade

---

## Test Cluster Validation Phase

Before upgrading production, validate the target Kubernetes version in a dedicated test cluster.

### 9-Step Test Procedure

| Step | Action | Pass Criteria | What It Validates |
|------|--------|--------------|-------------------|
| 1. Deploy test cluster | Create EKS cluster at target K8s version with same config (VPC CNI mode, add-on set, Karpenter/MNG) | Cluster reaches `ACTIVE` status | Cluster provisioning and configuration compatibility |
| 2. Upgrade control plane (if testing in-place) | Initiate control plane upgrade on test cluster | Control plane upgrade completes without errors | Upgrade process for the specific version transition |
| 3. Verify control plane | Check node status, cluster info, API server responsiveness | All API endpoints healthy, no error responses | API server availability after upgrade |
| 4. Verify add-ons | Check all EKS add-ons and self-managed add-ons are running | All add-on pods Running/Ready, no CrashLoopBackOff | Add-on compatibility with new K8s version |
| 5. Verify workloads | Deploy representative workloads (same Helm charts, same configs) | All deployments reach desired replica count | Application manifest compatibility, scheduling |
| 6. Verify networking | Test ingress, service-to-service communication, DNS resolution, network policies | All connectivity tests pass, DNS resolves within SLA | CNI, CoreDNS, kube-proxy, ingress controller behavior |
| 7. Verify storage | Create PVCs, write/read data, test volume expansion | PVCs bind, data persists across pod restarts | CSI driver compatibility, StorageClass behavior |
| 8. Performance test | Run load test at expected production traffic levels | Latency and throughput within acceptable thresholds | No performance regressions from version change |
| 9. Document results | Record all findings, regressions, and workarounds | Test report reviewed and approved | Formal sign-off for production upgrade |

---

## Bottlerocket-Specific Guidance

### Bottlerocket Update Operator (BUO)

The Bottlerocket Update Operator automates OS-level updates for Bottlerocket nodes without requiring full node replacement. BUO runs as a DaemonSet (agent on each node) plus a controller that coordinates updates in waves to avoid disrupting too many nodes simultaneously.

| Component | Role |
|---|---|
| **brupop-agent** | DaemonSet on each Bottlerocket node; checks for updates, applies them |
| **brupop-controller** | Coordinates update waves, respects PDBs, manages rollout |

| Factor | BUO (OS Update) | Karpenter Drift (Node Replacement) |
|---|---|---|
| **What changes** | OS packages only | Entire node (new AMI) |
| **Disruption** | In-place reboot | Pod eviction + new node provisioning |
| **Speed** | Fast (reboot only) | Slower (provision + schedule + pull images) |
| **When to use** | Routine OS security patches | K8s version upgrade, AMI change |
| **PDB respect** | Yes (controller coordinates) | Yes (Karpenter respects PDBs) |

### SSM Connectivity Verification

Bottlerocket uses AWS Systems Manager (SSM) for administrative access — there is no SSH. Bottlerocket provides two special containers:

| Container | Purpose | Access Method |
|---|---|---|
| **Control container** | Limited admin tasks, enabled by default | SSM Session Manager |
| **Admin container** | Full root access, disabled by default | SSM Session Manager (must enable) |

To verify SSM connectivity: check that the SSM agent is running on the node, the node's IAM role has `AmazonSSMManagedInstanceCore` policy, and VPC endpoints for SSM are configured (if private subnets without NAT).

### OS Update vs K8s Version Upgrade

| Scenario | Action | Tool | Disruption |
|---|---|---|---|
| Security patch for Bottlerocket OS | OS update in-place | BUO | Reboot only |
| New Bottlerocket AMI (same K8s version) | Node replacement | Karpenter drift or MNG update | Pod eviction + reschedule |
| K8s minor version upgrade (e.g., 1.34 → 1.35) | Control plane + data plane upgrade | EKS API + Karpenter drift | Full upgrade sequence |
| Critical CVE requiring immediate patch | OS update (if BUO patch available) or node replacement | BUO or Karpenter | Depends on patch availability |

---

## Emergency Rollback Procedures

### Rollback Matrix

| Component | Can Rollback? | Method | Notes |
|---|---|---|---|
| **EKS control plane** | No | Cannot downgrade K8s version | Must rebuild cluster at previous version |
| **Data plane nodes** | Yes | Replace with previous AMI | Karpenter: update EC2NodeClass AMI; MNG: update launch template |
| **EKS managed add-ons** | Yes | Revert to previous version via API/Terraform | Some add-ons have minimum version requirements |
| **Helm-managed add-ons** | Yes | `helm rollback` or GitOps revert | Check CRD compatibility |
| **Application deployments** | Yes | `kubectl rollout undo` or GitOps revert | Verify DB schema compatibility |
| **CRD changes** | Partial | Can revert CRD spec, but data migration may not reverse | Test CRD rollback in non-prod first |
| **Network policies** | Yes | Revert via GitOps or kubectl apply | Immediate effect |
| **IAM changes** | Yes | Revert Terraform/CloudFormation | May take minutes to propagate |

### Full Cluster Rebuild from Backup

Use when: catastrophic cluster failure, corrupted etcd state, or failed upgrade with no rollback path.

**Prerequisites:**
- Velero backups (K8s resources + PV snapshots) in a separate account/region
- GitOps repository with all application and add-on manifests
- Terraform code for cluster infrastructure
- **Note:** Velero does not back up AWS resources (IAM roles, SGs, VPC config) — these must be recreated via IaC

**High-level steps:**

| Step | Action | Estimated Time |
|---|---|---|
| 1 | Provision new EKS cluster (Terraform apply) | 15-20 minutes |
| 2 | Install core add-ons (VPC CNI, CoreDNS, Karpenter) | 5-10 minutes |
| 3 | Restore Velero backup (K8s resources) | 10-30 minutes |
| 4 | Restore PV snapshots (EBS volumes) | 10-30 minutes |
| 5 | Reconcile GitOps repository | 5-15 minutes |
| 6 | Validate workloads healthy | 10-15 minutes |
| 7 | Switch DNS/traffic to new cluster | 5 minutes |
| **Total** | | **1-2 hours** |

✅ DO:
- Test full cluster rebuild quarterly in an isolated environment
- Keep Terraform state and Velero backups in a separate account
- Document the rebuild runbook with exact commands and validation steps

❌ DON'T:
- Attempt to repair a corrupted cluster for hours — rebuild is often faster
- Skip the validation step before switching traffic
- Forget to update DNS TTLs in advance (low TTL enables faster failover)

---

**Sources:**
- [AWS EKS Best Practices Guide — Cluster Upgrades](https://docs.aws.amazon.com/eks/latest/best-practices/cluster-upgrades.html)
- [EKS Version Lifecycle](https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions.html)
- [Karpenter Upgrade Guide](https://karpenter.sh/docs/upgrading/)
