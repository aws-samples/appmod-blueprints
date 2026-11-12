"""Hermetic tests: the CloudFront distribution and VPC origin are created TAGGED with
platform.gitops.io/prefix=<prefix>, so the consumer IAM policy can allow
cloudfront:CreateDistribution / CreateVpcOrigin only on
aws:RequestTag/platform.gitops.io/prefix instead of on "*" unconditionally.

Runs the real scripts with bash against a fake `aws` that records its argv. No AWS.

Run:  python -m pytest workshop/scripts/tests/test_cloudfront_ownership_tag.py -q
"""
import json
import os
import shutil
import subprocess

import pytest

if not shutil.which("bash") or not shutil.which("jq"):
    pytest.skip("bash and jq required", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
RESERVE = os.path.join(REPO, "scripts", "cloudfront-reserve-domain.sh")
ATTACH = os.path.join(REPO, "scripts", "cloudfront-attach-origin.sh")
TAG = "platform.gitops.io/prefix"

FAKE_AWS = r"""#!/usr/bin/env bash
# Record every call (one JSON array of argv per line), answer what the scripts need.
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$AWS_LOG"
case "$1 $2" in
  "cloudfront list-distributions")
    if [ -n "${FAKE_DIST_ID:-}" ]; then
      case "$*" in *DomainName*) echo "d111.cloudfront.net" ;; *) echo "$FAKE_DIST_ID" ;; esac
    else echo None; fi ;;
  "cloudfront create-distribution-with-tags")
    echo '{"Distribution":{"Id":"E123","DomainName":"d111.cloudfront.net"}}' ;;
  "cloudfront create-distribution")
    echo '{"Distribution":{"Id":"E123","DomainName":"d111.cloudfront.net"}}' ;;
  "elbv2 describe-load-balancers")
    printf 'arn:aws:elasticloadbalancing:r:1:loadbalancer/app/x/1\tx.elb\tinternal\tactive\n' ;;
  "cloudfront get-distribution") echo None ;;
  "cloudfront list-vpc-origins") echo "" ;;
  "cloudfront create-vpc-origin") echo "vo_abcdefgh12345" ;;
  # Stop the attach script right after the create: we only assert on the create call.
  "cloudfront get-vpc-origin") exit 3 ;;
  *) echo "" ;;
esac
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text(FAKE_AWS)
    aws.chmod(0o755)
    sleep = bindir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    log = tmp_path / "aws.log"
    e = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    e.update(PATH=f"{bindir}:{os.environ['PATH']}", AWS_LOG=str(log),
             PLATFORM_CONFIG_FILE=str(tmp_path / "missing.yaml"))
    e.pop("RESOURCE_PREFIX", None)
    return e, log


def calls(log):
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def run(script, e, **extra):
    return subprocess.run(["bash", script], env={**e, **extra}, capture_output=True,
                          text=True, timeout=30)


def test_reserve_creates_tagged_distribution(env):
    e, log = env
    r = run(RESERVE, e, HUB_CLUSTER_NAME="peeks-hub", RESOURCE_PREFIX="peeks")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "d111.cloudfront.net"
    cs = calls(log)
    assert not any(c[:2] == ["cloudfront", "create-distribution"] for c in cs), \
        "untagged create-distribution would be denied by the RequestTag condition"
    create = [c for c in cs if c[:2] == ["cloudfront", "create-distribution-with-tags"]]
    assert len(create) == 1
    cfg = json.loads(create[0][create[0].index("--distribution-config-with-tags") + 1])
    assert cfg["Tags"]["Items"] == [{"Key": TAG, "Value": "peeks"}]
    assert cfg["DistributionConfig"]["Comment"] == "peeks-hub-platform"


def test_reserve_prefix_from_config(env, tmp_path):
    if not shutil.which("yq"):
        pytest.skip("yq required")
    e, log = env
    cfgf = tmp_path / "config.local.yaml"
    cfgf.write_text('resourcePrefix: "acme"\nhub:\n  clusterName: "acme-hub"\n')
    r = run(RESERVE, e, PLATFORM_CONFIG_FILE=str(cfgf))
    assert r.returncode == 0, r.stderr
    create = [c for c in calls(log) if c[1] == "create-distribution-with-tags"][0]
    cfg = json.loads(create[create.index("--distribution-config-with-tags") + 1])
    assert cfg["Tags"]["Items"][0]["Value"] == "acme"


def test_reserve_without_prefix_fails_before_any_create(env):
    e, log = env
    r = run(RESERVE, e, HUB_CLUSTER_NAME="peeks-hub")
    assert r.returncode == 1
    assert "resource prefix unknown" in r.stderr
    assert not any(c[0] == "cloudfront" and c[1].startswith("create") for c in calls(log))


def test_reserve_idempotent_reuse_creates_nothing(env):
    e, log = env
    r = run(RESERVE, e, HUB_CLUSTER_NAME="peeks-hub", RESOURCE_PREFIX="peeks", FAKE_DIST_ID="E123")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "d111.cloudfront.net"
    assert not any(c[1].startswith("create") for c in calls(log))


def test_attach_creates_tagged_vpc_origin(env):
    e, log = env
    r = run(ATTACH, e, HUB_CLUSTER_NAME="peeks-hub", AWS_REGION="us-west-2",
            RESOURCE_PREFIX="peeks", FAKE_DIST_ID="E123", CF_TIMEOUT_SECONDS="0")
    create = [c for c in calls(log) if c[:2] == ["cloudfront", "create-vpc-origin"]]
    assert len(create) == 1, r.stderr
    tags = json.loads(create[0][create[0].index("--tags") + 1])
    assert tags == {"Items": [{"Key": TAG, "Value": "peeks"}]}
    json.loads(create[0][create[0].index("--vpc-origin-endpoint-config") + 1])


def test_attach_without_prefix_fails_before_any_call(env):
    e, log = env
    r = run(ATTACH, e, HUB_CLUSTER_NAME="peeks-hub", AWS_REGION="us-west-2")
    assert r.returncode == 1
    assert "resource prefix unknown" in r.stderr
    assert calls(log) == []
