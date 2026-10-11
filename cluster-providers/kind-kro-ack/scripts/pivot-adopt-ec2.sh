#!/usr/bin/env bash
# pivot-adopt-ec2.sh — generate ACK ec2 adoption manifests for the hub pivot (#775).
#
# WHY: ec2 resources (VPC, Subnet, InternetGateway, NATGateway, ElasticIPAddress,
# RouteTable) are "Class 2" — keyed by an AWS-generated ID (vpc-…, subnet-…), NOT by
# a name/attribute in spec. ACK can only ADOPT them (instead of creating a duplicate)
# when the live ID is supplied in `services.k8s.aws/adoption-fields`. That ID is
# unknown at RGD-authoring time, so it CANNOT be baked into rg-vpc.yaml — it must be
# read from the SOURCE (kind) cluster's live `Vpc` kro CR `.status` at pivot time and
# emitted here, to be applied on the TARGET (hub) context.
#
# SCOPE: only needed on the EksclusterWithVpc fallback path (no pre-created VPC). On
# the PEEKS/CDK path the hub VPC is pre-created (.hub.network.vpcId) and NOT ACK-managed,
# so there is nothing to adopt and this helper is a no-op (it exits 0 with a note).
#
# OUTPUT: ACK ec2 CRs on stdout, each annotated:
#   services.k8s.aws/adoption-policy: adopt
#   services.k8s.aws/adoption-fields: {"<idKey>":"<live-id>"}
# Apply with:  pivot-adopt-ec2.sh | KUBECONFIG=<hub> kubectl apply -f -
#
# This script is READ-ONLY against the source cluster and WRITES NOTHING itself.
set -euo pipefail

SRC_KUBECONFIG="${SRC_KUBECONFIG:?set SRC_KUBECONFIG to the kind kubeconfig path}"
VPC_CR_NAME="${VPC_CR_NAME:?set VPC_CR_NAME (the kro Vpc CR metadata.name, e.g. peeks-hub)}"
VPC_CR_NS="${VPC_CR_NS:-$VPC_CR_NAME}"
REGION="${REGION:?set REGION}"

kc() { KUBECONFIG="$SRC_KUBECONFIG" kubectl "$@"; }

# A kro Vpc CR is the sentinel for the EksclusterWithVpc (ACK-managed VPC) path.
if ! kc -n "$VPC_CR_NS" get vpc.kro.run "$VPC_CR_NAME" >/dev/null 2>&1; then
  echo "# [pivot-adopt-ec2] no kro Vpc/$VPC_CR_NAME in ns $VPC_CR_NS — EksCluster" \
       "(pre-created VPC) path, nothing to adopt. No-op." >&2
  exit 0
fi

# Emit one adoption CR. $1=ACK kind, $2=CR name, $3=namespace, $4=idKey, $5=live id.
emit() {
  local kind="$1" name="$2" ns="$3" idkey="$4" id="$5"
  [ -z "$id" ] || [ "$id" = "null" ] && { echo "# skip $kind/$name — empty $idkey" >&2; return; }
  cat <<YAML
---
apiVersion: ec2.services.k8s.aws/v1alpha1
kind: ${kind}
metadata:
  name: ${name}
  namespace: ${ns}
  annotations:
    services.k8s.aws/region: ${REGION}
    services.k8s.aws/adoption-policy: adopt
    services.k8s.aws/adoption-fields: '{"${idkey}":"${id}"}'
spec: {}
YAML
}

# Pull every live ec2 ID from the ACK ec2 CRs in the source namespace. ACK stores the
# AWS ID in .status.<field>; we read the CRs the kro Vpc graph created (rg-vpc.yaml).
jget() { kc -n "$VPC_CR_NS" get "$1" "$2" -o jsonpath="{$3}" 2>/dev/null || true; }

VPC_ID=$(jget vpc.ec2.services.k8s.aws "${VPC_CR_NAME}-vpc" .status.vpcID)
emit VPC "${VPC_CR_NAME}-vpc" "$VPC_CR_NS" vpcID "$VPC_ID"

IGW_ID=$(jget internetgateway.ec2.services.k8s.aws "${VPC_CR_NAME}-igw" .status.internetGatewayID)
emit InternetGateway "${VPC_CR_NAME}-igw" "$VPC_CR_NS" internetGatewayID "$IGW_ID"

EIP_ALLOC=$(jget elasticipaddress.ec2.services.k8s.aws "${VPC_CR_NAME}-eip1" .status.allocationID)
emit ElasticIPAddress "${VPC_CR_NAME}-eip1" "$VPC_CR_NS" allocationID "$EIP_ALLOC"

NAT_ID=$(jget natgateway.ec2.services.k8s.aws "${VPC_CR_NAME}-nat-gateway1" .status.natGatewayID)
emit NATGateway "${VPC_CR_NAME}-nat-gateway1" "$VPC_CR_NS" natGatewayID "$NAT_ID"

for rt in public-routetable private-routetable1 private-routetable2; do
  RT_ID=$(jget routetable.ec2.services.k8s.aws "${VPC_CR_NAME}-${rt}" .status.routeTableID)
  emit RouteTable "${VPC_CR_NAME}-${rt}" "$VPC_CR_NS" routeTableID "$RT_ID"
done

for sn in public-subnet1 public-subnet2 private-subnet1 private-subnet2; do
  SN_ID=$(jget subnet.ec2.services.k8s.aws "${VPC_CR_NAME}-${sn}" .status.subnetID)
  emit Subnet "${VPC_CR_NAME}-${sn}" "$VPC_CR_NS" subnetID "$SN_ID"
done

echo "# [pivot-adopt-ec2] emitted adoption manifests for VPC $VPC_ID (region $REGION)." >&2
