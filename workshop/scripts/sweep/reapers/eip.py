"""Elastic IP reaper (§13): spoke NAT-gateway EIPs that persist UNASSOCIATED after
the NAT is torn down out of order. Release only UNASSOCIATED addresses that are ours
(ctx.eip_is_ours: ownership/cluster tag, our hub's ACK capability, or our clusters' names)."""


def reap(ctx):
    log, ec2 = ctx.log, ctx.ec2
    try:
        released = 0
        for a in ec2.describe_addresses().get("Addresses", []):
            if a.get("AssociationId"):
                continue  # still attached — never touch
            tags = {t["Key"]: t["Value"] for t in a.get("Tags", [])}
            if ctx.eip_is_ours(tags):
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
