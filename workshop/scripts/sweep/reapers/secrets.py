"""Secrets Manager reaper (§8): workshop secrets that may survive task destroy.

IncludePlannedDeletion=True is critical: a secret already SCHEDULED for deletion
is invisible to a normal list_secrets, yet its name stays reserved and blocks the
next deploy's CreateSecret. Force-delete active AND scheduled ones.
"""


def reap(ctx):
    log, sm, prefix, spokes = ctx.log, ctx.sm, ctx.prefix, ctx.spokes
    try:
        _reaped = 0
        _secret_names = [prefix] + [s for s in spokes if not s.startswith(prefix + "-")]
        for _page in sm.get_paginator("list_secrets").paginate(
            IncludePlannedDeletion=True,
            Filters=[{"Key": "name", "Values": _secret_names}],
        ):
            for s in _page.get("SecretList", []):
                try:
                    sm.delete_secret(SecretId=s["ARN"], ForceDeleteWithoutRecovery=True)
                    _reaped += 1
                except Exception:
                    pass
        log(f"Secrets Manager: force-deleted {_reaped} secret(s) (incl. scheduled-for-deletion)")
    except Exception as e:
        log(f"Secrets Manager: {e}")
