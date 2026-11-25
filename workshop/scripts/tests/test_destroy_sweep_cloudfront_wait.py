"""Hermetic test: scripts/sweep-cloudfront.py (task destroy step 6a) waits for a disabled
CloudFront distribution to be Deployed (up to ~20 min) before deleting it (#1301).

It had the race #1299 fixed in the workshop reaper: a 300 s wait whose result was
ignored, no wait at all for a distribution already Enabled=False but still InProgress,
and a DistributionNotDisabled refusal swallowed, so the distribution was left behind.

Virtual clock, no AWS, no real sleep.
Run:  python -m pytest workshop/scripts/tests/test_destroy_sweep_cloudfront_wait.py -q
"""
import contextlib
import io
import os
import re
import runpy
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "scripts", "sweep-cloudfront.py")
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "workshop", "scripts"))
import sweep_lib as sl  # noqa: E402
from sweep import resilience  # noqa: E402
from sweep.reapers import cloudfront  # noqa: E402

HUB = "peeks-hub"
DIST = "EDIST1"
VO = "vo-1"


class _Err(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class FakeCf:
    """A disable reaches Deployed at `deployed_at` on the virtual clock; delete before is refused."""

    def __init__(self, clock, enabled, deployed_at):
        self.clock = clock
        self.enabled = enabled
        self.deploy_after = deployed_at
        self.deployed_at = None if enabled else deployed_at
        self.deleted = False
        self.vo_deleted = False
        self.delete_calls = 0

    def _deployed(self):
        return self.deployed_at is not None and self.clock["t"] >= self.deployed_at

    def list_vpc_origins(self):
        return {"VpcOriginList": {"Items": [{"Id": VO, "Name": HUB + "-vo"}]}}

    def list_distributions(self):
        return {"DistributionList": {"Items": [{"Id": DIST, "Comment": HUB + "-platform"}]}}

    def get_distribution_config(self, Id):
        return {"ETag": "e1", "DistributionConfig": {"Enabled": self.enabled}}

    def update_distribution(self, Id, DistributionConfig, IfMatch):
        self.enabled = DistributionConfig["Enabled"]
        self.deployed_at = self.clock["t"] + self.deploy_after

    def get_distribution(self, Id):
        return {"ETag": "e2", "Distribution": {"Status": "Deployed" if self._deployed() else "InProgress"}}

    def delete_distribution(self, Id, IfMatch):
        self.delete_calls += 1
        if self.enabled or not self._deployed():
            raise _Err("DistributionNotDisabled")
        self.deleted = True

    def get_vpc_origin(self, Id):
        return {"ETag": "e3"}

    def delete_vpc_origin(self, Id, IfMatch):
        if not self.deleted:
            raise _Err("CannotDeleteEntityWhileInUse")
        self.vo_deleted = True


def run_script(monkeypatch, cf):
    clock = cf.clock

    def tick(s):
        clock["t"] += s

    real_poll = resilience.poll_until

    def virtual_poll(pred, *, attempts, delay, backoff=1.0, sleep=None):
        return real_poll(pred, attempts=attempts, delay=delay, backoff=backoff, sleep=tick)

    monkeypatch.setattr(sl, "client", lambda service, *a, **k: cf)
    monkeypatch.setattr(cloudfront, "poll_until", virtual_poll)
    monkeypatch.setattr("time.sleep", tick)
    monkeypatch.setattr(sys, "argv", [SCRIPT, HUB])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        runpy.run_path(SCRIPT, run_name="__main__")
    return buf.getvalue()


def test_already_disabled_but_in_progress_is_waited_on(monkeypatch):
    # Disabled by an earlier run; Deployed only 600 s from now. The old code skipped the wait.
    cf = FakeCf({"t": 0.0}, enabled=False, deployed_at=600)
    out = run_script(monkeypatch, cf)
    assert cf.deleted and cf.vo_deleted, out
    assert cf.delete_calls == 1, out


def test_wait_uses_the_full_20_min_budget(monkeypatch):
    # Deployed 1150 s after the disable: past the old 300 s wait, inside the 1200 s budget.
    cf = FakeCf({"t": 0.0}, enabled=True, deployed_at=1150)
    out = run_script(monkeypatch, cf)
    assert cf.deleted and cf.vo_deleted, out
    assert cf.delete_calls == 1, out
    assert cloudfront.DEPLOYED_ATTEMPTS * cloudfront.DEPLOYED_DELAY == 1200


def test_not_disabled_refusal_is_retried(monkeypatch):
    cf = FakeCf({"t": 0.0}, enabled=False, deployed_at=0)
    real_delete = cf.delete_distribution
    calls = {"n": 0}

    def flaky(Id, IfMatch):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Err("DistributionNotDisabled")
        real_delete(Id, IfMatch)

    cf.delete_distribution = flaky
    out = run_script(monkeypatch, cf)
    assert calls["n"] == 2, out
    assert cf.deleted and cf.vo_deleted, out


def test_wait_is_bounded_and_vpc_origin_still_attempted(monkeypatch):
    cf = FakeCf({"t": 0.0}, enabled=True, deployed_at=100_000)
    out = run_script(monkeypatch, cf)
    assert not cf.deleted
    assert cf.delete_calls == cloudfront.DELETE_TRIES, out
    assert "CannotDeleteEntityWhileInUse" in out  # VPC origin delete still attempted
    assert cf.clock["t"] <= 1200 + 2 * 8 * 15 + 60, out  # ~24 min worst case


# ── The deadline guard of step 6a in the kind-kro-ack Taskfile ──────────────────────────
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")


def _guard():
    """(threshold, the `if ... fi` text of step 6a) read verbatim from the Taskfile."""
    yaml = pytest.importorskip("yaml")
    with open(TASKFILE) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    cmd = next(c["cmd"] for c in cmds if isinstance(c, dict) and "# 6a." in c.get("cmd", ""))
    m = re.search(r'if \[ "\$\(dl_left\)" -gt (\d+) \]; then\n.*?\nfi\n', cmd, re.S)
    assert m, "step 6a deadline guard not found"
    return int(m.group(1)), m.group(0)


def test_step6a_guard_covers_the_helper_worst_case():
    # Per distribution: the Deployed wait, then (DELETE_TRIES - 1) short waits after a refusal.
    worst = (cloudfront.DEPLOYED_ATTEMPTS + (cloudfront.DELETE_TRIES - 1) * cloudfront.RETRY_ATTEMPTS) \
        * cloudfront.DEPLOYED_DELAY
    assert worst == 1440
    assert _guard()[0] == 1500 and _guard()[0] > worst


@pytest.mark.parametrize("left, runs", [(1501, True), (1500, False), (331, False), (0, False)])
def test_step6a_runs_only_with_more_than_the_worst_case_left(tmp_path, left, runs):
    guard = _guard()[1].replace("{{.ROOT_DIR}}", str(tmp_path)).replace("{{.HUB_CLUSTER_NAME}}", HUB)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "sweep-cloudfront.py").write_text("print('SWEEP-RAN')\n")
    res = subprocess.run(["bash", "-c", f"dl_left() {{ echo {left}; }}\n{guard}"],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert ("SWEEP-RAN" in res.stdout) is runs, res.stdout
    assert ("6a: deadline" in res.stdout) is (not runs), res.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
