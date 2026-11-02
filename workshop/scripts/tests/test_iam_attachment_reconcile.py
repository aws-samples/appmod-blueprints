"""Tests for the iam-attachment-reconcile CronJob (charts/podidentity-pod-restart).

On a policy rename the Policy object keeps its name and reports the old ARN until the
renamed policy exists, so a new RolePolicyAttachment can latch the old ARN. The job
deletes an attachment whose resolved policyArn differs from its Policy's observed ARN.

Run:  python -m pytest workshop/scripts/tests/test_iam_attachment_reconcile.py -q
"""
import os
import shutil
import stat
import subprocess
import textwrap

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CHART = os.path.join(REPO, "gitops", "addons", "charts", "podidentity-pod-restart")

OLD = "arn:aws:iam::111122223333:policy/old-name"
NEW = "arn:aws:iam::111122223333:policy/new-name"

FAKE_KUBECTL = textwrap.dedent("""\
    #!/bin/sh
    echo "$*" >> "$FAKE_DIR/calls"
    case "$1" in
      get)
        case "$2" in
          rolepolicyattachments.iam.aws.upbound.io)
            if [ "$3" = "-o" ]; then cat "$FAKE_DIR/rpa"; fi ;;
          policies.iam.aws.upbound.io)
            f="$FAKE_DIR/policy.$3"; [ -f "$f" ] && cat "$f" || exit 1 ;;
        esac ;;
    esac
    """)


@pytest.fixture(scope="module")
def script():
    if not shutil.which("helm"):
        pytest.skip("helm not installed")
    out = subprocess.run(["helm", "template", "t", CHART], capture_output=True, text=True, check=True).stdout
    for doc in yaml.safe_load_all(out):
        if doc and doc.get("kind") == "CronJob" and doc["metadata"]["name"] == "iam-attachment-reconcile":
            return doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][0]
    raise AssertionError("CronJob iam-attachment-reconcile not rendered")


def run(tmp_path, script, rpas, policies):
    fake = tmp_path / "fake"
    fake.mkdir()
    k = fake / "kubectl"
    k.write_text(FAKE_KUBECTL)
    k.chmod(k.stat().st_mode | stat.S_IEXEC)
    (fake / "rpa").write_text("".join(f"{n}|{p}|{a}\n" for n, p, a in rpas))
    for name, arn in policies.items():
        (fake / f"policy.{name}").write_text(arn)
    (fake / "calls").write_text("")
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", FAKE_DIR=str(fake))
    p = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    deleted = [c.split()[2] for c in (fake / "calls").read_text().splitlines() if c.startswith("delete ")]
    return p, deleted


def test_latched_old_arn_is_deleted(tmp_path, script):
    # The new attachment resolved the old ARN; the renamed policy now reports the new one.
    p, deleted = run(tmp_path, script, [("ns.app-c-role-policy-attachment", "app-c-iam-policy", OLD)],
                     {"app-c-iam-policy": NEW})
    assert p.returncode == 0, p.stderr
    assert deleted == ["ns.app-c-role-policy-attachment"]


def test_matching_arn_is_kept(tmp_path, script):
    p, deleted = run(tmp_path, script, [("a", "pol", NEW)], {"pol": NEW})
    assert p.returncode == 0, p.stderr
    assert deleted == []


def test_rename_in_flight_policy_without_arn_is_kept(tmp_path, script):
    # The policy has no observed ARN yet: nothing to compare with.
    p, deleted = run(tmp_path, script, [("a", "pol", OLD)], {"pol": ""})
    assert p.returncode == 0, p.stderr
    assert deleted == []


def test_missing_policy_unresolved_and_literal_arn_are_kept(tmp_path, script):
    p, deleted = run(tmp_path, script, [("a", "gone", OLD), ("b", "pol", ""), ("c", "", OLD)], {"pol": NEW})
    assert p.returncode == 0, p.stderr
    assert deleted == []


def test_only_the_stale_attachment_is_deleted(tmp_path, script):
    p, deleted = run(tmp_path, script,
                     [("ok", "pol1", NEW), ("stale", "pol2", OLD)], {"pol1": NEW, "pol2": NEW})
    assert p.returncode == 0, p.stderr
    assert deleted == ["stale"]
