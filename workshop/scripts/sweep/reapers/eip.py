"""Elastic IP reaper (§13): spoke NAT-gateway EIPs that persist UNASSOCIATED after
the NAT is torn down out of order. Release only UNASSOCIATED prefixed addresses."""


def reap(ctx):
    log, ec2, prefix, OWNER_PREFIX_TAG = ctx.log, ctx.ec2, ctx.prefix, ctx.OWNER_PREFIX_TAG
    try:
        released = 0
        for a in ec2.describe_addresses().get("Addresses", []):
            if a.get("AssociationId"):
                continue  # still attached — never touch
            tags = {t["Key"]: t["Value"] for t in a.get("Tags", [])}
            owned = (
                tags.get(OWNER_PREFIX_TAG) == prefix
                or any(prefix in str(v) for v in tags.values())
                or any(prefix in str(k) for k in tags.keys())
            )
            if owned:
                try:
                    ec2.release_address(AllocationId=a["AllocationId"])
                    log(f"  Released EIP {a.get('PublicIp')} ({tags.get('Name', '-')})")
                    released += 1
                except Exception as e:
                    log(f"  EIP {a.get('PublicIp')}: {e}")
        if released == 0:
            log("No orphaned EIPs to release")
    except Exception as e:
        log(f"Elastic IPs: {e}")
