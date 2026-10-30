#!/usr/bin/env python3
"""
sweep-credentials-check.py AWS_REGION [EXPECTED_ACCOUNT]

task kind-kro-ack:destroy preflight. The teardown sweep runs python helpers
(boto3) next to `aws` CLI calls. They must act on the same account: when they
do not see the same credentials (for example AWS_PROFILE and
AWS_DEFAULT_PROFILE set to different profiles, which the aws CLI and boto3
resolve in opposite orders), the helpers fail closed and silently skip the VPC,
RDS, log group and IAM sweeps. Exits 0 when boto3 has credentials for
EXPECTED_ACCOUNT (the account `aws sts get-caller-identity` reports), 3 when it
has none, 1 when it resolves to another account. Prints no account id.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sweep_lib as sl  # noqa: E402


def main(argv, sts=None, out=sys.stdout):
    pos, _ = sl.parse_common(argv, __doc__)
    if not pos or not pos[0]:
        print(__doc__, file=sys.stderr)
        return 2
    region, expected = pos[0], (pos[1] if len(pos) > 1 else '')
    sts = sts or sl.client('sts', region)
    acct = sts.get_caller_identity()['Account']
    if expected and acct != expected:
        print('ERROR sweep-credentials-check: boto3 and the aws CLI resolve to DIFFERENT AWS accounts '
              f'(profile in effect for boto3: {sl.align_profile() or "<none>"}). Refusing to start.',
              file=sys.stderr)
        return 1
    print('  ✓ teardown helpers (boto3) use the same AWS account as the aws CLI', file=out)
    return 0


if __name__ == '__main__':
    sys.exit(sl.run_cli(main, sys.argv[1:], 'sweep-credentials-check'))
