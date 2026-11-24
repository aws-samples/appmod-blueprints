#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Seed the emulator with the leftovers a failed PEEKS teardown leaves behind, for the test
# prefix ($PREFIX) and for a control stack ($CONTROL) the sweep must not touch.
#
# Every resource created is written to $EMU_WORK/manifest.tsv as "<expect> <family> <id>"
# (expect = gone for $PREFIX, kept for $CONTROL); verify.py checks each line after the sweep.
#
# Not seeded, on purpose (see README.md): the CFN-owned IDE VPC (the emulator, like AWS,
# refuses the reserved aws:cloudformation:* tags, so it needs a real stack) and CloudFront
# (ListVpcOrigins is a stub in the emulator). The capability log delivery of $PREFIX-hub is
# created by scenario-10.sh, which records it too.
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "$0")/lib.sh"
emu_load
emu_assert_identity

MANIFEST="$EMU_WORK/manifest.tsv"
: >"$MANIFEST"
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >>"$MANIFEST"; }
q() { emu_aws "$@" --output text; }   # one value out of a --query
AZ_A="${EMU_REGION}a"; AZ_B="${EMU_REGION}b"
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":["eks.amazonaws.com","capabilities.eks.amazonaws.com"]},"Action":["sts:AssumeRole","sts:TagSession"]}]}'

tags() { # name prefix [extra Key=..,Value=.. ...] -> an EC2 tag-specification body
  local n="$1" p="$2"; shift 2
  local t="{Key=Name,Value=$n},{Key=platform.gitops.io/prefix,Value=$p}"
  for x in "$@"; do t="$t,{$x}"; done
  echo "$t"
}

seed_stack() { # prefix expect
  local p="$1" e="$2" vpc sn sga sgb eni igw rtb vpce eip role hubvpc hsa hsb
  log "seeding $p (expected after the sweep: $e)"

  # Spoke VPC as ACK leaves it: subnet, two SGs that reference each other, an ENI, an
  # attached IGW, an associated route table, and the guardduty-data endpoint (with its
  # requester-managed ENI).
  vpc=$(q ec2 create-vpc --cidr-block 10.10.0.0/16 --query Vpc.VpcId \
    --tag-specifications "ResourceType=vpc,Tags=[$(tags "$p-spoke-dev-vpc" "$p" "Key=eks:kubernetes-resource-name,Value=$p-spoke-dev-vpc")]")
  rec "$e" vpc "$vpc"
  sn=$(q ec2 create-subnet --vpc-id "$vpc" --cidr-block 10.10.1.0/24 --availability-zone "$AZ_A" --query Subnet.SubnetId)
  rec "$e" subnet "$sn"
  sga=$(q ec2 create-security-group --vpc-id "$vpc" --group-name "$p-spoke-dev-a" --description a --query GroupId)
  sgb=$(q ec2 create-security-group --vpc-id "$vpc" --group-name "$p-spoke-dev-b" --description b --query GroupId)
  emu_aws ec2 authorize-security-group-ingress --group-id "$sga" --protocol tcp --port 443 --source-group "$sgb" >/dev/null
  emu_aws ec2 authorize-security-group-ingress --group-id "$sgb" --protocol tcp --port 443 --source-group "$sga" >/dev/null
  rec "$e" sg "$sga"; rec "$e" sg "$sgb"
  eni=$(q ec2 create-network-interface --subnet-id "$sn" --groups "$sga" --query NetworkInterface.NetworkInterfaceId)
  rec "$e" eni "$eni"
  igw=$(q ec2 create-internet-gateway --query InternetGateway.InternetGatewayId)
  emu_aws ec2 attach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$vpc"
  rec "$e" igw "$igw"
  rtb=$(q ec2 create-route-table --vpc-id "$vpc" --query RouteTable.RouteTableId)
  emu_aws ec2 associate-route-table --route-table-id "$rtb" --subnet-id "$sn" >/dev/null
  rec "$e" rtb "$rtb"
  vpce=$(q ec2 create-vpc-endpoint --vpc-id "$vpc" --vpc-endpoint-type Interface \
    --service-name "com.amazonaws.$EMU_REGION.guardduty-data" --subnet-ids "$sn" \
    --security-group-ids "$sga" --no-private-dns-enabled --query VpcEndpoint.VpcEndpointId)
  rec "$e" vpce "$vpce"

  eip=$(q ec2 allocate-address --domain vpc --query AllocationId \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$p-spoke-dev-eip1}]")
  rec "$e" eip "$eip"

  # Hub VPC on two AZs, the hub and a spoke cluster, the hub's kro capability.
  hubvpc=$(q ec2 create-vpc --cidr-block 10.20.0.0/16 --query Vpc.VpcId \
    --tag-specifications "ResourceType=vpc,Tags=[$(tags "$p-hub-vpc" "$p")]")
  rec "$e" vpc "$hubvpc"
  hsa=$(q ec2 create-subnet --vpc-id "$hubvpc" --cidr-block 10.20.1.0/24 --availability-zone "$AZ_A" --query Subnet.SubnetId)
  hsb=$(q ec2 create-subnet --vpc-id "$hubvpc" --cidr-block 10.20.2.0/24 --availability-zone "$AZ_B" --query Subnet.SubnetId)
  rec "$e" subnet "$hsa"; rec "$e" subnet "$hsb"
  role=$(q iam create-role --role-name "$p-hub-ack-capability-role" --assume-role-policy-document "$TRUST" --query Role.Arn)
  rec "$e" iam-role "$p-hub-ack-capability-role"
  for c in "$p-hub" "$p-spoke-prod"; do
    emu_aws eks create-cluster --name "$c" --role-arn "$role" \
      --resources-vpc-config "subnetIds=$hsa,$hsb" --tags "platform.gitops.io/prefix=$p" >/dev/null
    rec "$e" eks-cluster "$c"
  done
  for c in "$p-hub" "$p-spoke-prod"; do emu_aws eks wait cluster-active --name "$c"; done
  emu_aws eks create-capability --cluster-name "$p-hub" --capability-name kro --type KRO \
    --role-arn "$role" --delete-propagation-policy RETAIN >/dev/null
  rec "$e" eks-capability "$p-hub/kro"

  # Bucket with objects (the sweep must empty it first), ECR, secrets, logs, SSM, DynamoDB.
  if [ "$EMU_REGION" = us-east-1 ]; then  # us-east-1 refuses an explicit LocationConstraint, as on AWS
    emu_aws s3api create-bucket --bucket "$p-ray-models-$EMU_ACCOUNT" >/dev/null
  else
    emu_aws s3api create-bucket --bucket "$p-ray-models-$EMU_ACCOUNT" \
      --create-bucket-configuration "LocationConstraint=$EMU_REGION" >/dev/null
  fi
  printf 'weights\n' >"$EMU_WORK/tmp/obj"
  for k in models/a.bin models/b.bin; do
    emu_aws s3api put-object --bucket "$p-ray-models-$EMU_ACCOUNT" --key "$k" --body "$EMU_WORK/tmp/obj" >/dev/null
  done
  rec "$e" s3-bucket "$p-ray-models-$EMU_ACCOUNT"
  for r in "$p-ray-vllm-custom" "$p/rust-app"; do
    emu_aws ecr create-repository --repository-name "$r" >/dev/null
    rec "$e" ecr-repo "$r"
  done
  for s in "$p-hub/config" "$p/platform/keycloak"; do
    emu_aws secretsmanager create-secret --name "$s" --secret-string '{"seed":"fake"}' >/dev/null
    rec "$e" secret "$s"
  done
  emu_aws logs create-log-group --log-group-name "/aws/eks/$p-hub/cluster"
  rec "$e" log-group "/aws/eks/$p-hub/cluster"
  emu_aws ssm put-parameter --name "/$p/hub/test" --type String --value seed >/dev/null
  rec "$e" ssm-param "/$p/hub/test"
  # The DynamoDB table IS seeded: the residue reaper must delete it, and since #1314 the §17
  # gate no longer counts it as residue while it is DELETING, so the sweep must exit 0.
  emu_aws dynamodb create-table --table-name "$p-terraform-lock" \
    --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  rec "$e" ddb-table "$p-terraform-lock"
}

seed_stack "$PREFIX" gone
seed_stack "$CONTROL" kept
log "seeded $(wc -l <"$MANIFEST") resources ($MANIFEST)"
