# Hub Networking and VPC Ownership

## Status

**Proposed** — implementation pending. The current platform always creates a
new VPC for the hub; this document describes the customer-supplied-VPC option.

This document defines who owns the hub cluster's VPC (the platform vs. the
customer) and what the platform requires when the customer supplies one.
Spoke clusters are out of scope for now and will be addressed in a follow-up
once the hub story is settled.

Related:
- [`MULTI_CLUSTER_AUTH.md`](./MULTI_CLUSTER_AUTH.md) — multi-cluster authentication
- [`cluster-lifecycle.md`](./cluster-lifecycle.md) — spoke cluster prune safety

## Modes

The hub VPC can be owned in one of two ways, selected by the presence or
absence of `hub.vpcId` in `config.local.yaml`:

| Mode | When | Behavior |
|------|------|----------|
| **Platform-managed** (default) | `hub.vpcId` is unset/empty | Platform creates a VPC, subnets, NAT gateway, route tables via the `platform-cluster` Crossplane Composition (or its kro equivalent). |
| **Customer-supplied** | `hub.vpcId` is set | Platform attaches the hub EKS cluster to the supplied VPC and subnets. No VPC is created. |

The two modes are mutually exclusive. A customer who wants to run the hub on
their existing VPC switches to customer-supplied mode by adding the VPC ID
and subnet IDs to `config.local.yaml`; nothing else changes from the
customer's perspective.

## Customer-supplied mode

### `config.local.yaml` extension

```yaml
hub:
  clusterName: peeks-hub
  kubernetesVersion: "1.35"
  # Customer-supplied VPC. Leave empty to have the platform create a VPC.
  vpcId: "vpc-0123456789abcdef0"
  # Required when vpcId is set: at least 2 private subnets (across distinct
  # AZs) for the cluster control plane ENIs and node groups, and at least 2
  # public subnets for any internet-facing ALB/NLB the platform creates.
  subnets:
    private:
      - "subnet-0a1b2c3d"
      - "subnet-0e4f5g6h"
    public:
      - "subnet-0p1q2r3s"
      - "subnet-0t4u5v6w"
```

When `hub.vpcId` is empty or omitted, all `hub.subnets` fields are ignored
and the platform creates everything.

### What the platform expects of a customer-supplied VPC

Hard requirements (the platform fails fast if these are not met):

1. **At least 2 private subnets in different AZs** for the EKS cluster
   control plane ENIs and node groups. EKS requires 2+ AZs for control plane
   redundancy.
2. **At least 2 public subnets in different AZs** for internet-facing load
   balancers (Keycloak ingress, GitLab service, etc.). Required even if the
   customer fronts the platform with a CDN — the LBC needs public subnets to
   create the origin LB. May be relaxed in a future "private platform" mode.
3. **NAT gateway (or equivalent egress path) reachable from the private
   subnets.** Pulling addon container images, fetching Helm charts from
   public repositories, and any AWS API calls made by controllers require
   outbound internet egress.
4. **Subnets tagged for ALB discovery**:
   - Public subnets: `kubernetes.io/role/elb = 1`
   - Private subnets: `kubernetes.io/role/internal-elb = 1`
   - Both: `kubernetes.io/cluster/<hub-cluster-name> = shared` (or `owned`,
     but the platform won't manage tags on a customer VPC, so `shared` is
     the right value)

Soft requirements (the platform works without them but the customer should
plan for them):

5. **CIDR sizing**: at minimum a `/24` per private subnet so node groups can
   scale. The platform does not auto-provision EKS Pod Identity associations
   into the customer's IAM — those continue to be platform-managed.
6. **No overlapping CIDRs** with any other VPC the platform is expected to
   peer with later (e.g., spoke VPCs in customer-supplied mode in a future
   phase).
7. **Route tables include routes** for any custom egress paths (Transit
   Gateway, peered VPCs, on-prem VPN). The platform does not modify customer
   route tables.

### Verification checklist

Before running `task install` with `hub.vpcId` set, the customer can verify
their VPC is compatible:

```bash
VPC_ID=vpc-0123456789abcdef0
REGION=us-west-2

# 1. VPC exists and is in the expected region
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --region "$REGION" \
  --query 'Vpcs[0].{Id:VpcId,Cidr:CidrBlock,State:State}'

# 2. Subnets exist, span 2+ AZs each (private and public)
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --region "$REGION" \
  --query 'Subnets[].{Id:SubnetId,AZ:AvailabilityZone,Cidr:CidrBlock,Public:MapPublicIpOnLaunch,Tags:Tags}' \
  --output table

# 3. NAT gateway present
aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$VPC_ID" --region "$REGION" \
  --query 'NatGateways[?State==`available`].[NatGatewayId,SubnetId]' --output table

# 4. Required tags on subnets
for SUBNET in subnet-0a1b2c3d subnet-0e4f5g6h subnet-0p1q2r3s subnet-0t4u5v6w; do
  echo "=== $SUBNET ==="
  aws ec2 describe-subnets --subnet-ids "$SUBNET" --region "$REGION" \
    --query 'Subnets[0].Tags[?starts_with(Key, `kubernetes.io`)]' --output table
done
```

If any check fails, fix the VPC before running `task install`.

## Platform-managed mode (default)

No `config.local.yaml` change required. The Composition creates:

- One VPC with the configured CIDR (`hub.vpcCidr`, default `10.0.0.0/16`)
- 2 private subnets and 2 public subnets across 2 AZs
- 1 NAT gateway (single-AZ for cost; HA NAT is a future option)
- Internet gateway, route tables, route table associations
- All subnet tags required for ALB discovery

This continues to be the default for the workshop and for any customer who
wants the platform to "just work."

## Implementation Plan

Phase 1 is hub-only.

### Phase 1 — Hub VPC ownership

1. **Composition change** in `gitops/abstractions/crossplane/platform-cluster/`:
   - Add `hub.vpcId` and `hub.subnets.{private,public}` fields to the XRD
   - Add a `function-cel-filter` rule that gates the VPC + subnet + NAT +
     IGW resources on `vpcId` being unset/empty (skip them in
     customer-supplied mode)
   - Wire the EKS Cluster's `subnetIds` from either the platform-created
     subnets or the customer-supplied ones, depending on mode
2. **`config.local.yaml`** template: add the `hub.vpcId` and `hub.subnets`
   fields with comments explaining when to use them.
3. **Validation task**: a `task validate-hub-vpc` that runs the verification
   checklist above against `hub.vpcId`. Fails fast with a clear message if
   the VPC is incompatible. Runs as a precondition of `task install` when
   `hub.vpcId` is set.
4. **Documentation**: this doc + a short note in the install README pointing
   at it.

### Out of scope (deferred)

- **Customer-supplied VPC for spokes.** Same pattern but with per-spoke
  `vpcId`/`subnets` in `gitops/fleet/spoke-values/.../crossplane-clusters/values.yaml`
  (or the kro equivalent). Add when the hub story is proven.
- **Customer-managed Route 53 hosted zone.** Currently the platform assumes
  the hosted zone is platform-managed (or that the customer pre-creates one
  the platform can read). Decoupling this is a follow-up.
- **Private-only platform** (no public subnets, ingress via PrivateLink or
  a private ALB). Material design work; not Phase 1.
- **Hub-spoke connectivity options** (peering, Transit Gateway). Worth a
  separate document once spoke-side VPC ownership lands.
