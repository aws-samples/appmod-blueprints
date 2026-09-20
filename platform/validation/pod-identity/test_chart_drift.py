#!/usr/bin/env python3
"""Guard against drift between the two per-backend pod-identity charts.

`crossplane-pod-identity` (provider != kro-ack) and `ack-pod-identity`
(provider == kro-ack) are deliberate mirrors: same identities, same IAM policy
documents, different CRD kinds. Duplicating the values was chosen over a shared
library chart because ArgoCD renders a single chart directory and symlinks/shared
paths outside it are not resolved reliably. The tradeoff is that the copies can
silently diverge -- and divergence in an IAM policy document is a security bug
(one provider grants more than the other). This test is the guard.

Compared, for every identity present in BOTH charts:
  - policy.document      (semantic JSON equality, so formatting may differ)
  - policy.name
  - roleName
  - namespace / serviceAccount   (a mismatch here silently breaks credentials)

Identities present in only one chart are reported but NOT failed: the ACK chart
intentionally carries a subset (see docs/platform/ack-pod-identity-design.md --
adot/cloudwatch/cni/kyverno-reporter are dead, crossplane-*-provider is bootstrap
and stays in the RGD).

Exit 0 = no drift. Exit 1 = drift found.
"""

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

REPO = Path(__file__).resolve().parents[3]
CHARTS = REPO / "gitops/addons/charts"
CROSSPLANE = CHARTS / "crossplane-pod-identity/values.yaml"
ACK = CHARTS / "ack-pod-identity/values.yaml"

# Fields that must match exactly for a shared identity.
SCALAR_FIELDS = ["roleName", "namespace", "serviceAccount"]


def load(path):
    if not path.is_file():
        sys.exit(f"ERROR: missing values file: {path}")
    with path.open() as fh:
        return (yaml.safe_load(fh) or {}).get("identities", {}) or {}


def main():
    xp = load(CROSSPLANE)
    ack = load(ACK)

    shared = sorted(set(xp) & set(ack))
    if not shared:
        sys.exit("ERROR: the two charts share no identities -- that cannot be right.")

    failures = []

    for name in shared:
        a, b = xp[name], ack[name]

        for field in SCALAR_FIELDS:
            if a.get(field) != b.get(field):
                failures.append(
                    f"{name}.{field}: crossplane={a.get(field)!r} ack={b.get(field)!r}"
                )

        pa, pb = a.get("policy"), b.get("policy")
        if bool(pa) != bool(pb):
            failures.append(f"{name}.policy: present in only one chart")
            continue
        if not pa:
            continue

        if pa.get("name") != pb.get("name"):
            failures.append(
                f"{name}.policy.name: crossplane={pa.get('name')!r} ack={pb.get('name')!r}"
            )

        try:
            da, db = json.loads(pa["document"]), json.loads(pb["document"])
        except (KeyError, json.JSONDecodeError) as exc:
            failures.append(f"{name}.policy.document: not valid JSON ({exc})")
            continue

        if da != db:
            failures.append(
                f"{name}.policy.document: IAM policy documents DIFFER "
                f"(statements: crossplane={len(da.get('Statement', []))} "
                f"ack={len(db.get('Statement', []))})"
            )

    print(f"compared {len(shared)} shared identities: {', '.join(shared)}")
    only_xp = sorted(set(xp) - set(ack))
    only_ack = sorted(set(ack) - set(xp))
    if only_xp:
        print(f"  crossplane-only (expected): {', '.join(only_xp)}")
    if only_ack:
        print(f"  ack-only: {', '.join(only_ack)}")

    if failures:
        print("\nDRIFT DETECTED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nThe two charts are mirrors. Fix by copying the corrected value into BOTH\n"
            "values.yaml files (policy documents must stay semantically identical).",
            file=sys.stderr,
        )
        return 1

    print("\nOK: no drift between crossplane-pod-identity and ack-pod-identity.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
