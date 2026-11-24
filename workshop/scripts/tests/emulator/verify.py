#!/usr/bin/env python3
"""Check the emulator after the sweep (sweep-on-emulator job, see README.md).

1. Every manifest line marked "gone" (the test prefix) no longer exists, and every line
   marked "kept" (the control prefix) still exists.
2. A name/tag scan finds no resource of the test prefix at all, seeded or not.

Deletions can finish asynchronously (a VPC endpoint passes through `deleting`, for example), so
the checks are retried for up to VERIFY_TIMEOUT seconds before failing.

Usage: python3 verify.py <manifest.tsv> <region> <prefix>
Run through lib.sh's emu_run: it refuses any endpoint other than https://127.0.0.1:<port>.
"""
import os
import re
import sys
import time

import boto3
from botocore.exceptions import ClientError

NOT_FOUND = {
    "ResourceNotFoundException", "NoSuchEntity", "NoSuchBucket", "NotFound", "404",
    "RepositoryNotFoundException", "ParameterNotFound", "InvalidVpcID.NotFound",
    "InvalidSubnetID.NotFound", "InvalidGroup.NotFound", "InvalidNetworkInterfaceID.NotFound",
    "InvalidInternetGatewayID.NotFound", "InvalidRouteTableID.NotFound",
    "InvalidVpcEndpointId.NotFound", "InvalidAllocationID.NotFound",
}


def endpoint_guard():
    ep = os.environ.get("AWS_ENDPOINT_URL", "")
    if not re.fullmatch(r"https://127\.0\.0\.1:\d+", ep):
        sys.exit(f"verify.py: AWS_ENDPOINT_URL={ep!r} is not the local emulator, refusing to run")
    return ep


class Checker:
    def __init__(self, region, endpoint):
        self.endpoint = endpoint
        self._c = {}
        self.region = region

    def c(self, svc):
        if svc not in self._c:
            cl = boto3.client(svc, region_name=self.region)
            if cl.meta.endpoint_url.rstrip("/") != self.endpoint:
                sys.exit(f"verify.py: {svc} client endpoint {cl.meta.endpoint_url} is not {self.endpoint}")
            self._c[svc] = cl
        return self._c[svc]

    def exists(self, family, ident):
        """True/False. Any error other than "not found" is raised: it is not proof of absence."""
        ec2 = self.c("ec2")
        try:
            if family == "vpc":
                return bool(ec2.describe_vpcs(VpcIds=[ident])["Vpcs"])
            if family == "subnet":
                return bool(ec2.describe_subnets(SubnetIds=[ident])["Subnets"])
            if family == "sg":
                return bool(ec2.describe_security_groups(GroupIds=[ident])["SecurityGroups"])
            if family == "eni":
                return bool(ec2.describe_network_interfaces(NetworkInterfaceIds=[ident])["NetworkInterfaces"])
            if family == "igw":
                return bool(ec2.describe_internet_gateways(InternetGatewayIds=[ident])["InternetGateways"])
            if family == "rtb":
                return bool(ec2.describe_route_tables(RouteTableIds=[ident])["RouteTables"])
            if family == "vpce":
                eps = ec2.describe_vpc_endpoints(VpcEndpointIds=[ident])["VpcEndpoints"]
                return any(e["State"].lower() != "deleted" for e in eps)
            if family == "eip":
                return bool(ec2.describe_addresses(AllocationIds=[ident])["Addresses"])
            if family == "eks-cluster":
                self.c("eks").describe_cluster(name=ident)
                return True
            if family == "eks-capability":
                cluster, cap = ident.split("/", 1)
                self.c("eks").describe_capability(clusterName=cluster, capabilityName=cap)
                return True
            if family == "iam-role":
                self.c("iam").get_role(RoleName=ident)
                return True
            if family == "s3-bucket":
                self.c("s3").head_bucket(Bucket=ident)
                return True
            if family == "ecr-repo":
                self.c("ecr").describe_repositories(repositoryNames=[ident])
                return True
            if family == "secret":
                self.c("secretsmanager").describe_secret(SecretId=ident)
                return True
            if family == "log-group":
                groups = self.c("logs").describe_log_groups(logGroupNamePrefix=ident)["logGroups"]
                return any(g["logGroupName"] == ident for g in groups)
            if family == "ssm-param":
                self.c("ssm").get_parameter(Name=ident)
                return True
            if family == "ddb-table":
                # A DELETING table is on its way out: absent for this check.
                return self.c("dynamodb").describe_table(TableName=ident)["Table"]["TableStatus"] != "DELETING"
            if family == "delivery-source":
                self.c("logs").get_delivery_source(name=ident)
                return True
            if family == "delivery-destination":
                self.c("logs").get_delivery_destination(name=ident)
                return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in NOT_FOUND or code.endswith(".NotFound"):
                return False
            raise
        raise ValueError(f"unknown family {family!r}")

    def scan(self, prefix):
        """Names/tags of the test prefix still present, whatever created them."""
        def own(n):  # same shape as the sweep's name_is_ours: peeks, peeks-*, peeks/*
            return n == prefix or n.startswith((prefix + "-", prefix + "/"))

        def items(svc, op, key, **kw):  # every page when the operation is paginated
            cl = self.c(svc)
            if cl.can_paginate(op):
                for page in cl.get_paginator(op).paginate(**kw):
                    yield from page.get(key, [])
            else:
                yield from getattr(cl, op)(**kw).get(key, [])

        found = []
        found += [f"eks:{n}" for n in items("eks", "list_clusters", "clusters") if own(n)]
        found += [f"s3:{b['Name']}" for b in items("s3", "list_buckets", "Buckets") if own(b["Name"])]
        found += [f"ecr:{r['repositoryName']}" for r in items("ecr", "describe_repositories", "repositories")
                  if own(r["repositoryName"])]
        found += [f"secret:{s['Name']}" for s in items("secretsmanager", "list_secrets", "SecretList")
                  if own(s["Name"])]
        for pfx in (f"/aws/eks/{prefix}", f"/aws/lambda/{prefix}-", f"/aws/containerinsights/{prefix}"):
            found += [f"log-group:{g['logGroupName']}"
                      for g in items("logs", "describe_log_groups", "logGroups", logGroupNamePrefix=pfx)
                      if own(g["logGroupName"].split("/", 3)[-1])]
        found += [f"delivery-source:{d['name']}" for d in items("logs", "describe_delivery_sources", "deliverySources")
                  if own(d["name"])]
        found += [f"delivery-destination:{d['name']}"
                  for d in items("logs", "describe_delivery_destinations", "deliveryDestinations") if own(d["name"])]
        found += [f"ssm:{p['Name']}" for p in items("ssm", "describe_parameters", "Parameters")
                  if p["Name"].startswith(f"/{prefix}/")]
        for t in items("dynamodb", "list_tables", "TableNames"):
            if own(t) and self.exists("ddb-table", t):
                found.append(f"dynamodb:{t}")
        found += [f"iam-role:{r['RoleName']}" for r in items("iam", "list_roles", "Roles") if own(r["RoleName"])]
        for flt in ({"Name": "tag:platform.gitops.io/prefix", "Values": [prefix]},
                    {"Name": "tag:Name", "Values": [f"{prefix}-*"]}):
            found += [f"vpc:{v['VpcId']}" for v in items("ec2", "describe_vpcs", "Vpcs", Filters=[flt])]
            found += [f"eip:{a['AllocationId']}" for a in items("ec2", "describe_addresses", "Addresses", Filters=[flt])]
        return sorted(set(found))


def main():
    manifest, region, prefix = sys.argv[1:4]
    chk = Checker(region, endpoint_guard())
    with open(manifest) as f:
        rows = [line.rstrip("\n").split("\t") for line in f if line.strip()]
    deadline = time.time() + int(os.environ.get("VERIFY_TIMEOUT", "30"))
    while True:
        bad = []
        for expect, family, ident in rows:
            present = chk.exists(family, ident)
            if expect == "gone" and present:
                bad.append(f"still present: {family} {ident}")
            elif expect == "kept" and not present:
                bad.append(f"control resource deleted: {family} {ident}")
        bad += [f"still present (scan): {r}" for r in chk.scan(prefix)]
        if not bad or time.time() >= deadline:
            break
        time.sleep(3)
    gone = sum(1 for e, _, _ in rows if e == "gone")
    kept = len(rows) - gone
    if bad:
        print("verify FAILED:")
        for b in bad:
            print(f"  ✗ {b}")
        return 1
    print(f"verify OK: {gone} '{prefix}' resources gone, {kept} control resources intact, "
          f"no '{prefix}-*' resource left")
    return 0


if __name__ == "__main__":
    sys.exit(main())
