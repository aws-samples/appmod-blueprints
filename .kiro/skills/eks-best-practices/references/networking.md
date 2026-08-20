# EKS Networking — VPC CNI & IP Management

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** VPC CNI configuration, subnet/CIDR planning, IPv4 vs IPv6, custom networking, Security Groups for Pods, and IP address management

**For ingress, load balancing, DNS, and private clusters, see:** [Networking — Ingress & DNS](networking-ingress-dns.md)
**For network policies and east/west traffic control, see:** [Security — Runtime & Network](security-runtime-network.md)

---

## Table of Contents

1. [VPC CNI Deep Dive](#vpc-cni-deep-dive)
2. [VPC CNI Operations](#vpc-cni-operations)
3. [Subnet Planning](#subnet-planning)
4. [IPv4 vs IPv6](#ipv4-vs-ipv6)
5. [Security Groups for Pods](#security-groups-for-pods)

---

## VPC CNI Deep Dive

The Amazon VPC CNI assigns pods real VPC IP addresses, enabling native VPC networking (security groups, NACLs, flow logs all work). It has two components:
- **CNI binary** — invoked by kubelet on pod add/remove, wires up pod networking
- **ipamd (aws-node DaemonSet)** — long-running IPAM daemon that manages ENIs and maintains a warm pool of IPs or prefixes

### Mode Decision Matrix

| Mode | IP Usage | Pod Density | Best For |
|------|----------|-------------|----------|
| **Secondary IP** (default) | 1 IP per pod from subnet | Limited by ENI × IPs per ENI | Most workloads, simplest setup |
| **Prefix Delegation** | /28 prefix per ENI slot | ~4-16× more pods per node | High pod density, IP-constrained VPCs |
| **Custom Networking** | Pods use different subnet/CIDR | Same as mode used | Separate pod CIDR from node CIDR |

### Secondary IP Mode (Default)

Each pod receives one secondary private IP from an ENI attached to the node. The warm pool pre-allocates IPs for fast pod startup.

**Max pods per node** = (Number of ENIs × IPs per ENI) - 1

ENI counts and IPs-per-ENI vary by instance type and change over time — use the live [max-pods-calculator.sh](https://github.com/awslabs/amazon-eks-ami/blob/main/templates/al2/runtime/max-pods-calculator.sh) script as the source of truth rather than relying on a static table:

```bash
./max-pods-calculator.sh --instance-type m5.large --cni-version 1.9.0
```

**IP cooldown:** When a pod is deleted, its IP enters a 30-second cooldown cache before returning to the warm pool. This prevents premature IP recycling while kube-proxy updates iptables rules on all nodes.

### Prefix Delegation Mode

Instead of assigning individual IPs, the CNI assigns /28 prefixes (16 IPs each) to ENI slots — dramatically increasing pod density without additional ENIs.

**Enable prefix delegation:**

```bash
kubectl set env daemonset aws-node \
  -n kube-system \
  ENABLE_PREFIX_DELEGATION=true
```

**Max pods with prefix mode** = (ENIs × (IPs per ENI - 1) × 16) + 2

```bash
# Calculate for prefix mode
./max-pods-calculator.sh --instance-type m5.large --cni-version 1.9.0 \
  --cni-prefix-delegation-enabled
# Result: 110 (vs 29 in secondary IP mode)
```

You must update the max-pods setting on nodes when enabling prefix mode — the default reflects secondary IP mode limits:

```bash
# In managed node group launch template user data:
--use-max-pods false --kubelet-extra-args '--max-pods=110'
```

**Prefix allocation is faster than ENI attachment.** Attaching a prefix to an existing ENI completes in under a second vs ~10 seconds for a new ENI. In most cases, the CNI only needs a single ENI per node in prefix mode.

✅ DO:
- Use prefix delegation when running >30 pods per node
- Set `WARM_PREFIX_TARGET=1` (default) — good balance of fast startup and IP efficiency
- Use `WARM_IP_TARGET` (set <16) if you need tighter IP conservation per node
- Use [VPC Subnet CIDR reservations](https://docs.aws.amazon.com/vpc/latest/userguide/subnet-cidr-reservation.html) to ensure contiguous /28 blocks are available
- Use similar instance types in the same node group — the **lowest** max-pods value applies to all nodes in the group
- Update max-pods on nodes when enabling prefix mode

❌ DON'T:
- Enable prefix delegation on fragmented subnets without reservations — prefix attachment will fail with `InsufficientCidrBlocks`
- Mix secondary IP and prefix delegation modes in the same cluster
- Downgrade VPC CNI below v1.9.0 after enabling prefix mode — you must delete and recreate nodes if you downgrade
- Do rolling replacement of existing nodes — create new node groups, cordon/drain old ones, then delete them

### Custom Networking

Assigns pod IPs from a different CIDR than node IPs, typically using a secondary VPC CIDR from CG-NAT space (100.64.0.0/10):

```bash
# Enable custom networking
kubectl set env daemonset aws-node -n kube-system \
  AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG=true
```

```yaml
# Create ENIConfig per AZ
apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name: us-east-1a
spec:
  subnet: subnet-0123456789abcdef0  # Pod subnet in us-east-1a
  securityGroups:
  - sg-0123456789abcdef0
```

**Automate AZ-based ENIConfig selection** — name ENIConfigs after AZs and set:

```bash
kubectl set env daemonset aws-node -n kube-system \
  ENI_CONFIG_LABEL_DEF=topology.kubernetes.io/zone
```

Kubernetes labels nodes with `topology.kubernetes.io/zone` automatically, so the CNI picks the right ENIConfig per AZ without manual node labeling.

**Max pods with custom networking** is lower because the primary ENI is not used for pod IPs:

```
# Without prefix: (3 ENIs - 1) * (10 IPs/ENI - 1) + 2 = 20  (m5.large)
# With prefix:    (3 ENIs - 1) * ((10 - 1) * 16) + 2 = 290   (m5.large)
# Recommended:    110 (CPU/memory typically exhausted before IPs)
```

**Use custom networking when:**
- Node subnet CIDR is exhausted but you have other available CIDRs
- Pod traffic must appear from a different CIDR (for firewall rules)
- Deploying multiple EKS clusters connecting to on-premise datacenters (CG-NAT space avoids RFC1918 conflicts)

**Avoid custom networking when:**
- **Ready for IPv6** — IPv6 eliminates IP exhaustion without the operational overhead
- **CG-NAT space already in use** — consider an alternate CNI or IPv6
- **Overlapping CIDRs** — custom networking alone can't solve this; use a [private NAT gateway](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html) with transit gateway instead

### VPC CNI Configuration Tuning

| Setting | Default | Recommended | Purpose |
|---------|---------|-------------|---------|
| `WARM_IP_TARGET` | N/A | 2-5 | Pre-allocated IPs for fast pod startup |
| `MINIMUM_IP_TARGET` | N/A | 5-10 | Minimum IPs to keep available |
| `WARM_ENI_TARGET` | 1 | 0 (if using IP targets) | Pre-allocated ENIs |
| `WARM_PREFIX_TARGET` | 1 | 1 | Pre-allocated prefixes (prefix mode) |
| `POD_SECURITY_GROUP_ENFORCING_MODE` | strict | standard (for NLB/NodeLocal DNS) | SG for Pods traffic mode |

`WARM_IP_TARGET` and `MINIMUM_IP_TARGET` override `WARM_PREFIX_TARGET` when set. Use `WARM_IP_TARGET` for fine-grained control; use `WARM_PREFIX_TARGET` for simplicity.

**Warm pool trade-off:** Warm ENIs still consume IPs from your subnet CIDR. In secondary IP mode on a 3-node cluster with `WARM_ENI_TARGET=1`, the CNI can consume 43+ IPs just for warm pools before any application pods are scheduled.

---

## VPC CNI Operations

### Use Managed Add-On

Deploy VPC CNI as an [EKS managed add-on](https://docs.aws.amazon.com/eks/latest/userguide/eks-add-ons.html) rather than self-managed. Managed add-ons provide:
- Validated compatibility with your EKS version
- Automatic drift prevention — EKS reconciles managed fields every 15 minutes
- Simpler upgrades via EKS API/Console/CLI

Frequently-used fields like `WARM_ENI_TARGET`, `WARM_IP_TARGET`, and `MINIMUM_IP_TARGET` are **not** managed and won't be overwritten by drift prevention.

### EKS Auto Mode

With [EKS Auto Mode](https://docs.aws.amazon.com/eks/latest/userguide/automode.html), AWS fully manages VPC CNI configuration. You don't install or upgrade networking add-ons. Use Auto Mode when you want AWS to handle CNI operations entirely.

### Use Separate IAM Role for CNI

By default, VPC CNI inherits the node IAM role. This gives the CNI (and potentially compromised pods on the node) access to all permissions on the node role.

**Strongly recommended:** Create a dedicated IAM role for the CNI with only `AmazonEKS_CNI_Policy` attached. Use IRSA or Pod Identity to bind it to the `aws-node` service account:

```bash
# Specify CNI role when creating managed add-on
aws eks create-addon --cluster-name my-cluster \
  --addon-name vpc-cni \
  --service-account-role-arn arn:aws:iam::123456789012:role/eks-cni-role
```

Then remove `AmazonEKS_CNI_Policy` from the node role. For IPv6 clusters, create a custom IAM policy — the managed `AmazonEKS_CNI_Policy` only covers IPv4.

### Backup CNI Settings Before Update

VPC CNI runs on the data plane, so EKS does not auto-upgrade it. Before updating:

```bash
# Backup current settings
kubectl get daemonset aws-node -n kube-system -o yaml > aws-k8s-cni-backup.yaml
```

**Upgrade one minor version at a time** (e.g., 1.9 → 1.10 → 1.11). Never delete the DaemonSet during upgrade — that causes application downtime.

### Handle Liveness/Readiness Probe Failures

On data-intensive clusters, high CPU usage can cause aws-node probe health failures, leaving pods stuck in `containerCreating`. Increase the probe timeout:

```yaml
# Default timeoutSeconds: 10 — increase if experiencing probe failures
livenessProbe:
  timeoutSeconds: 30
readinessProbe:
  timeoutSeconds: 30
```

Also ensure `cpu` resource requests for aws-node are appropriate (default `25m` may be too low under heavy load).

### IPTables Forward Policy (Custom AMIs)

If using custom AMIs (not EKS Optimized), ensure the iptables forward policy is set to `ACCEPT` in kubelet.service. Many systems default to `DROP`, which breaks pod networking.

---

## Subnet Planning

### EKS Cluster Architecture

An EKS cluster spans two VPCs:
- **AWS-managed VPC** — hosts the Kubernetes control plane (not visible in your account)
- **Customer-managed VPC** — hosts nodes, pods, load balancers, and other infrastructure

Nodes connect to the control plane through **cross-account ENIs (X-ENIs)** that EKS places in your cluster subnets. EKS creates up to 4 X-ENIs across the subnets you specify at cluster creation.

### Control Plane Endpoint Access

| Mode | Node → API Server Path | External Access | Use When |
|------|----------------------|----------------|----------|
| **Public only** (default) | Leaves VPC via NAT/IGW → public endpoint | Yes | Dev/test, simplest setup |
| **Public + Private** | Stays in VPC via X-ENIs | Yes | Production with external CI/CD access |
| **Private only** | Stays in VPC via X-ENIs | No (VPC/connected networks only) | High-security, regulated environments |

With public-only, nodes need a public IP or NAT gateway to reach the API server. With private enabled, traffic stays within the VPC via X-ENIs — lower latency and no internet dependency.

### Recommended Subnet Architecture

```
VPC CIDR: 10.0.0.0/16 (65,536 IPs)
├── Cluster Subnets (X-ENIs only — NOT for nodes)
│   ├── 10.0.0.0/28   (16 IPs) — us-east-1a
│   ├── 10.0.0.16/28  (16 IPs) — us-east-1b
│   └── 10.0.0.32/28  (16 IPs) — us-east-1c
├── Public Subnets (load balancers, NAT gateways)
│   ├── 10.0.1.0/20   (4,096 IPs) — us-east-1a
│   ├── 10.0.16.0/20  (4,096 IPs) — us-east-1b
│   └── 10.0.32.0/20  (4,096 IPs) — us-east-1c
├── Private Subnets (nodes + pods)
│   ├── 10.0.64.0/18  (16,384 IPs) — us-east-1a
│   ├── 10.0.128.0/18 (16,384 IPs) — us-east-1b
│   └── 10.0.192.0/18 (16,384 IPs) — us-east-1c
└── (Optional) Pod-only Subnets (with custom networking)
    └── 100.64.0.0/16 (secondary CIDR, 65,536 IPs)
```

**Dedicated cluster subnets (/28)** prevent X-ENI IP consumption from competing with node/pod IPs. During cluster upgrades, EKS provisions additional ENIs in cluster subnets — if nodes share these subnets, IP contention can block upgrades.

### Subnet Tagging Requirements

```
# Public subnets (for internet-facing ALB/NLB)
kubernetes.io/role/elb = 1

# Private subnets (for internal ALB/NLB)
kubernetes.io/role/internal-elb = 1

# All subnets used by EKS
kubernetes.io/cluster/<cluster-name> = shared  # or "owned"
```

### IP Exhaustion Strategies

| Strategy | Complexity | IP Gain | Trade-offs |
|----------|-----------|---------|------------|
| **Prefix delegation** | Low | 4-16× | Requires contiguous /28 blocks; use subnet reservations |
| **Secondary CIDR** | Medium | Up to /16 | 100.64.0.0/10 (CG-NAT) recommended |
| **Custom networking** | Medium | Separate CIDR | More ENIConfig management; primary ENI unused for pods |
| **IPv6** | High | Unlimited | Irreversible; dual-stack complexity |
| **Private NAT gateway** | Medium | N/A | Solves overlapping CIDRs; adds NAT GW cost |

---

## IPv4 vs IPv6

### Decision Guide

| Factor | IPv4 | IPv6 |
|--------|------|------|
| **IP availability** | Limited — plan for exhaustion | Virtually unlimited (/80 prefix per node ≈ 10¹⁴ addresses) |
| **Setup complexity** | Standard | Requires dual-stack VPC with /56 CIDR |
| **Reversibility** | Can switch modes | **Irreversible** — IPv6 is for the cluster's lifetime |
| **Instance requirement** | Any | **Nitro-based instances only** |
| **CNI mode** | Secondary IP or prefix delegation | **Prefix mode only** (auto-enabled) |
| **WARM_IP/ENI tuning** | Required for optimization | **Not needed** — prefix assigned at bootstrap |
| **AWS service support** | Full | Most services (verify specific ones) |
| **Network policy** | Full support | Full support (VPC CNI 1.14+) |
| **Load balancers** | ALB/NLB full support | ALB/NLB dual-stack (requires LBC, in-tree controller doesn't support IPv6) |
| **Recommendation** | Default choice | Use when IPv4 exhaustion is a real concern |

### IPv6 Technical Details

**Services get ULA addresses:** Kubernetes services receive IPv6 addresses from Unique Local Address (ULA) space, auto-assigned at cluster creation and not modifiable.

**Private subnets use EIGW:** In IPv6, every address is internet-routable. Private subnets use [egress-only internet gateways](https://docs.aws.amazon.com/vpc/latest/userguide/egress-only-internet-gateway.html) (EIGW) — allows outbound traffic while blocking all inbound.

**Private IPv6 addressing (since August 2024):** You can now use private IPv6 addresses via [VPC IPAM](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-ip-addressing.html#vpc-ipv6-addresses) instead of public GUA addresses.

### IPv4 Egress from IPv6 Pods

IPv6 pods can still reach IPv4 endpoints. The VPC CNI uses a host-local secondary plugin that assigns each pod a non-routable IPv4 address from `169.254.172.0/22` (node-unique, up to 1024 addresses). Outbound IPv4 traffic is SNATed to the node's primary IPv4 address.

```
Pod (169.254.172.x) → SNAT to Node Primary IPv4 → NAT Gateway → Internet
```

**DNS64 warning:** Disable DNS64 on subnets where IPv6 pods run. When DNS64 is enabled, DNS returns synthesized IPv6 addresses for IPv4-only endpoints, routing traffic through NAT64 via the NAT gateway instead of direct SNAT — causing unexpected NAT gateway costs.

### IPv6 Operational Considerations

**Max pods formula for IPv6:**

```
(ENIs × (IPs per ENI - 1) × 16) + 2
# m5.large: (3 × 9 × 16) + 2 = 434
```

In practice, CPU and memory exhaust before IPs. Managed node groups calculate max pods automatically — don't override unless using self-managed nodes.

**Fargate in IPv6 clusters:** Fargate pods consume **both** an IPv4 and IPv6 address from the VPC. Size dual-stack subnets for growth — new Fargate pods cannot be scheduled if the subnet has no available IPv4 addresses, regardless of IPv6 availability.

**Load balancers:** Use the AWS Load Balancer Controller (not the in-tree controller) with dual-stack annotations:

```yaml
annotations:
  alb.ingress.kubernetes.io/ip-address-type: dualstack
  alb.ingress.kubernetes.io/target-type: ip
```

**Re-evaluate custom networking:** If you enabled custom networking to solve IPv4 exhaustion, it's no longer necessary with IPv6. Remove the overhead unless you have a separate security requirement for it.

---

## Security Groups for Pods

Security Groups for Pods assigns AWS security groups directly to individual pods via branch ENIs, rather than sharing the node's security group. This enables AWS-level network isolation per pod — useful for controlling pod access to AWS services like RDS, ElastiCache, and other VPC resources.

**For network policy vs SG for Pods comparison, and policy enforcement details, see:** [Security — Runtime & Network](security-runtime-network.md#security-groups-for-pods)

### When to Use

- Pods need direct access to AWS services (RDS, ElastiCache) and you want to reuse existing SG rules
- You need AWS-native audit trail (VPC Flow Logs per pod)
- Migrating from EC2 instances to EKS and preserving existing SG-based access controls

### Enforcing Modes

| Mode | Behavior | Use When |
|------|----------|----------|
| **`strict`** (default) | Only branch ENI SG applies; SNAT disabled; all traffic leaves node via VPC | Complete pod-to-AWS isolation needed |
| **`standard`** | Both node SG and branch ENI SG apply | Using with Network Policy, NodeLocal DNSCache, or need `externalTrafficPolicy: Local` |

**Strict mode impact:** All pod traffic — even pod-to-pod on the same node — traverses the VPC network. This increases VPC traffic and breaks NodeLocal DNSCache.

### Operational Requirements

**Disable TCP early demux** for liveness/readiness probes in strict mode:

```bash
kubectl edit daemonset aws-node -n kube-system
# Under initContainer, set:
#   DISABLE_TCP_EARLY_DEMUX=true
```

**Branch ENI capacity is additive** to the existing secondary IP limit per instance type. A m5.large supports up to 9 branch ENIs in addition to its standard 29 secondary IPs. However, pods using SG for Pods are still counted toward max-pods — consider increasing max-pods.

**Tag a single SG** with `kubernetes.io/cluster/$name` when multiple SGs are assigned to a pod. This allows the AWS Load Balancer Controller to find and update rules for routing traffic to the pod.

**NAT for outbound:** Source NAT is disabled for pods with security groups. Deploy these pods on **private subnets** with a NAT gateway and enable external SNAT:

```bash
kubectl set env daemonset -n kube-system aws-node AWS_VPC_K8S_CNI_EXTERNALSNAT=true
```

**terminationGracePeriodSeconds** must be non-zero (default 30s is fine). When set to zero, the CNI doesn't clean up the pod network, leaving branch ENIs unreclaimed.

**Fargate:** SG for Pods works on Fargate. Without a SecurityGroupPolicy, Fargate pods get the cluster security group. Include the cluster SG in your SecurityGroupPolicy for simplicity, otherwise add all minimum required rules manually:

```bash
# Find cluster security group
aws eks describe-cluster --name CLUSTER_NAME \
  --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId'
```

**Requirements not supported:**
- Windows nodes and non-Nitro instances
- NodeLocal DNSCache in strict mode
- SG for Pods with custom networking uses the SG from SecurityGroupPolicy, **not** from ENIConfig

---

## Multus CNI

Multus enables multiple network interfaces on pods, required for workloads such as telco, DPDK, and SR-IOV applications.

### How It Works

Multus acts as a meta-plugin that delegates to the primary CNI (VPC CNI) for the default interface and to additional CNI plugins for secondary interfaces. Pods define their network attachments through annotations referencing NetworkAttachmentDefinition CRDs.

### Enabling Multus

> **WARNING:** The thick-plugin variant has a known pod-lookup race condition that can break ALL pod creation cluster-wide. Only enable Multus after verifying your version includes the fix (v4.1.1+), or use thin-plugin mode instead.

Deploy Multus as a DaemonSet using the upstream manifests into `kube-system`:

```yaml
multus:
  # WARNING: thick-plugin has a pod-lookup race that breaks ALL pod creation.
  # Only enable after verifying your Multus version includes the fix,
  # or use thin-plugin mode instead.
  enabled: false
  image: ghcr.io/k8snetworkplumbingwg/multus-cni:v4.1.0-thick
```

Multus is deployed via `kubectl_manifest` resources that apply the upstream thick-plugin DaemonSet manifests directly into `kube-system` (not via Helm). The only config keys that matter are `enabled` and `image`.

**When it is safe to enable:**
- You are using thin-plugin mode (`multus-cni:v4.1.0-thin` or later) which avoids the race entirely
- You have confirmed your thick-plugin version includes the pod-lookup race fix (v4.1.1+)
- You have tested in a non-production cluster first and validated pod creation is not affected

### NetworkAttachmentDefinition Example

After Multus is installed, create NetworkAttachmentDefinitions for secondary interfaces:

```yaml
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: macvlan-conf
  namespace: my-app
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "type": "macvlan",
      "master": "eth1",
      "mode": "bridge",
      "ipam": {
        "type": "host-local",
        "subnet": "10.10.0.0/16"
      }
    }
```

Reference it in a pod annotation:

```yaml
metadata:
  annotations:
    k8s.v1.cni.cncf.io/networks: macvlan-conf
```

### Node Security Group for Multus

If Multus secondary interfaces need access to specific network resources, add additional node security group rules:

```yaml
node_sg_additional_rules:
  multus_traffic:
    description: "Allow Multus secondary interface traffic"
    protocol: -1
    from_port: 0
    to_port: 0
    type: ingress
    cidr_blocks: ["10.10.0.0/16"]
```

---

**Sources:**
- [AWS EKS Best Practices Guide — Amazon VPC CNI](https://docs.aws.amazon.com/eks/latest/best-practices/vpc-cni.html)
- [AWS EKS Best Practices Guide — Prefix Mode](https://docs.aws.amazon.com/eks/latest/best-practices/prefix-mode-linux.html)
- [AWS EKS Best Practices Guide — Custom Networking](https://docs.aws.amazon.com/eks/latest/best-practices/custom-networking.html)
- [AWS EKS Best Practices Guide — Subnets](https://docs.aws.amazon.com/eks/latest/best-practices/subnets.html)
- [AWS EKS Best Practices Guide — IPv6](https://docs.aws.amazon.com/eks/latest/best-practices/ipv6.html)
- [AWS EKS Best Practices Guide — Security Groups Per Pod](https://docs.aws.amazon.com/eks/latest/best-practices/sgpp.html)
