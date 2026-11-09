"""Hermetic tests for install perf R1 (v0.4.1 design): scripts/lbc-unstick.sh, called from the ALB
wait loop of scripts/cloudfront-attach-origin.sh when the platform ALB is late.

The helper names the symptom from read-only hub reads, then acts at most LBC_UNSTICK_MAX times
(default 2), LBC_UNSTICK_GAP seconds apart (default 180), never before LBC_UNSTICK_AFTER (480).
Time is the caller's wait counter, so nothing here sleeps.

Everything runs with bash against fake `aws` / `kubectl` / `sleep` on PATH. No cluster.

Run:  python -m pytest workshop/scripts/tests/test_lbc_unstick.py -q
"""
import datetime
import json
import os
import shutil
import subprocess

import pytest

if not shutil.which("bash") or not shutil.which("jq"):
    pytest.skip("bash and jq required", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
HELPER = os.path.join(REPO, "scripts", "lbc-unstick.sh")
ATTACH = os.path.join(REPO, "scripts", "cloudfront-attach-origin.sh")

NOW = datetime.datetime.now(datetime.timezone.utc)


def ts(age_s):
    return (NOW - datetime.timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def dep(avail, age=1000):
    return {"status": {"availableReplicas": avail,
                       "conditions": [{"type": "Available", "status": "True" if avail else "False",
                                       "lastTransitionTime": ts(age)}]}}


RS_FAILED = {"items": [
    {"metadata": {"creationTimestamp": "2026-01-01T00:00:00Z"}, "status": {"conditions": []}},
    {"metadata": {"creationTimestamp": "2026-01-01T00:05:00Z"},
     "status": {"conditions": [{"type": "ReplicaFailure", "status": "True"}]}}]}
RS_OK = {"items": [{"metadata": {"creationTimestamp": "2026-01-01T00:00:00Z"}, "status": {"conditions": []}}]}
ING_NOADDR = {"items": [{"spec": {"ingressClassName": "alb"}, "status": {"loadBalancer": {}}}]}
ING_ADDR = {"items": [{"spec": {"ingressClassName": "alb"},
                       "status": {"loadBalancer": {"ingress": [{"hostname": "x"}]}}}]}
APP_OUTOFSYNC = {"spec": {}, "status": {"health": {"status": "Missing"}}}
APP_HEALTHY = {"spec": {}, "status": {"health": {"status": "Healthy"}}}


class Hub:
    """Fake hub: files under tmp_path drive fake kubectl; every call is logged."""

    def __init__(self, tmp_path, sa=True, deploy=None, rs=RS_OK, ing=ING_NOADDR, app=APP_OUTOFSYNC,
                 kubectl_fails=False, kubeconfig_fails=False, restart_rc=0):
        self.t = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir(exist_ok=True)
        (tmp_path / "sa").write_text("serviceaccount/aws-load-balancer-controller-sa\n" if sa else "")
        (tmp_path / "dep.json").write_text(json.dumps(deploy) if deploy is not None else "")
        (tmp_path / "rs.json").write_text(json.dumps(rs))
        (tmp_path / "ing.json").write_text(json.dumps(ing))
        (tmp_path / "app.json").write_text(json.dumps(app))
        self._fake("kubectl",
                   '#!/usr/bin/env bash\n'
                   'echo "$*" >> "$T/kubectl.calls"\n'
                   f'[ "{int(kubectl_fails)}" = 1 ] && {{ echo boom >&2; exit 1; }}\n'
                   'case "$*" in\n'
                   '  *"get sa "*) cat "$T/sa";;\n'
                   '  *"get deploy "*) cat "$T/dep.json";;\n'
                   '  *"get rs "*) cat "$T/rs.json";;\n'
                   '  *"get ingress"*) cat "$T/ing.json";;\n'
                   '  *"get applications.argoproj.io"*) cat "$T/app.json";;\n'
                   '  *"patch applications.argoproj.io"*) echo patched >> "$T/patches";;\n'
                   f'  *"rollout restart"*) echo restarted >> "$T/restarts"; exit {restart_rc};;\n'
                   'esac\nexit 0\n')
        self._fake("aws",
                   '#!/usr/bin/env bash\n'
                   'echo "$*" >> "$T/aws.calls"\n'
                   f'case "$*" in *update-kubeconfig*) [ "{int(kubeconfig_fails)}" = 1 ] && exit 255;; esac\n'
                   'exit 0\n')
        self._fake("sleep", "#!/usr/bin/env bash\nexit 0\n")

    def _fake(self, name, body):
        p = self.bin / name
        p.write_text(body)
        os.chmod(p, 0o755)

    def env(self, **extra):
        e = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", T=str(self.t),
                 HUB_CLUSTER_NAME="hub", AWS_REGION="us-east-1",
                 LBC_UNSTICK_STATE=str(self.t / "state"))
        e.update(extra)
        return e

    def run(self, waited, **extra):
        return subprocess.run(["bash", HELPER, str(waited)], env=self.env(**extra),
                              capture_output=True, text=True, timeout=60)

    def count(self, name):
        f = self.t / name
        return len(f.read_text().split()) if f.exists() else 0

    def read_calls(self):
        f = self.t / "kubectl.calls"
        return f.read_text() if f.exists() else ""


# ── no action before the threshold, or when everything is fine ─────────────────────────────
@pytest.mark.parametrize("waited", [0, 15, 465, 479])
def test_no_action_before_threshold_and_no_hub_read(tmp_path, waited):
    h = Hub(tmp_path, sa=False)  # would be diag "missing" if it looked
    r = h.run(waited)
    assert r.returncode == 0 and r.stdout == ""
    assert h.read_calls() == "" and not (tmp_path / "aws.calls").exists()
    assert h.count("patches") == 0 and h.count("restarts") == 0


def test_threshold_is_inclusive_480(tmp_path):
    h = Hub(tmp_path, sa=False)
    r = h.run(480)
    assert "lbc-unstick: missing -> argocd-app-kick (0)" in r.stdout
    assert h.count("patches") == 1


def test_healthy_controller_with_addressed_ingress_is_left_alone(tmp_path):
    h = Hub(tmp_path, deploy=dep(1), ing=ING_ADDR)
    r = h.run(600)
    assert r.returncode == 0 and "running -> none (-)" in r.stdout
    assert h.count("patches") == 0 and h.count("restarts") == 0


def test_pods_still_starting_is_left_alone(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_OK)
    r = h.run(600)
    assert "starting -> none (-)" in r.stdout
    assert h.count("restarts") == 0 and not (tmp_path / "state").exists()


# ── the three diagnoses ────────────────────────────────────────────────────────────────────
def test_missing_service_account_kicks_the_lbc_app(tmp_path):
    h = Hub(tmp_path, sa=False, deploy=dep(0))
    r = h.run(500)
    assert "lbc-unstick: missing -> argocd-app-kick (0)" in r.stdout
    assert h.count("patches") == 1 and h.count("restarts") == 0
    assert "applications.argoproj.io aws-load-balancer-controller-hub" in h.read_calls()


def test_missing_deployment_kicks_the_lbc_app(tmp_path):
    h = Hub(tmp_path, sa=True, deploy=None)
    r = h.run(500)
    assert "missing -> argocd-app-kick (0)" in r.stdout and h.count("patches") == 1


def test_missing_with_healthy_app_logs_rc3_and_still_counts(tmp_path):
    h = Hub(tmp_path, sa=False, app=APP_HEALTHY)
    r = h.run(500)
    assert "missing -> argocd-app-kick (3)" in r.stdout
    assert h.count("patches") == 0 and (tmp_path / "state").read_text().split()[0] == "1"


def test_replica_failure_restarts_the_deployment(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED)
    r = h.run(500)
    assert "lbc-unstick: rsfailed -> rollout-restart (0)" in r.stdout
    assert h.count("restarts") == 1 and h.count("patches") == 0
    assert "rollout restart deploy/aws-load-balancer-controller" in h.read_calls()


def test_available_controller_without_alb_address_restarts_after_gap(tmp_path):
    h = Hub(tmp_path, deploy=dep(1, age=300), ing=ING_NOADDR)
    assert "noaddr -> rollout-restart (0)" in h.run(500).stdout and h.count("restarts") == 1


def test_available_but_young_controller_is_not_restarted(tmp_path):
    h = Hub(tmp_path, deploy=dep(1, age=30), ing=ING_NOADDR)
    r = h.run(500)
    assert "running -> none (-)" in r.stdout and h.count("restarts") == 0


# ── bounds ─────────────────────────────────────────────────────────────────────────────────
def test_max_two_actions_and_gap_180(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED)
    h.run(480)                      # action 1
    assert h.count("restarts") == 1
    for w in (495, 540, 600, 645, 659):
        h.run(w)                    # < 180 s after the first
    assert h.count("restarts") == 1, "no repeat within 180 s"
    h.run(660)                      # exactly 180 s later: action 2
    assert h.count("restarts") == 2
    for w in (840, 900, 1200, 1800):
        h.run(w)
    assert h.count("restarts") == 2, "never a third action"


def test_state_file_records_count_and_time(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED)
    h.run(510)
    assert (tmp_path / "state").read_text().split() == ["1", "510"]


def test_env_overrides_for_short_tests(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED)
    ov = dict(LBC_UNSTICK_AFTER="30", LBC_UNSTICK_GAP="10", LBC_UNSTICK_MAX="3")
    h.run(15, **ov)
    assert h.count("restarts") == 0
    h.run(30, **ov); h.run(35, **ov); h.run(40, **ov); h.run(50, **ov); h.run(60, **ov)
    assert h.count("restarts") == 3  # 30, 40, 50; the max (3) stops the rest


# ── failure behaviour: always exit 0, never act on what it could not read ───────────────────
def test_kubectl_failing_means_no_action_rc0(tmp_path):
    h = Hub(tmp_path, kubectl_fails=True, sa=False)
    r = h.run(600)
    assert r.returncode == 0 and "unreadable -> none (-)" in r.stdout
    assert h.count("patches") == 0 and h.count("restarts") == 0 and not (tmp_path / "state").exists()


def test_kubeconfig_failure_means_no_action_rc0(tmp_path):
    h = Hub(tmp_path, kubeconfig_fails=True, sa=False)
    r = h.run(600)
    assert r.returncode == 0 and "no-kubeconfig -> none (-)" in r.stdout
    assert h.read_calls() == ""


def test_failed_restart_is_logged_counted_and_rc0(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED, restart_rc=1)
    r = h.run(500)
    assert r.returncode == 0 and "rsfailed -> rollout-restart (1)" in r.stdout
    assert (tmp_path / "state").read_text().split()[0] == "1"


def test_garbage_rs_json_is_not_a_failure(tmp_path):
    h = Hub(tmp_path, deploy=dep(0))
    (tmp_path / "rs.json").write_text("not json")
    r = h.run(500)
    assert r.returncode == 0 and "starting -> none (-)" in r.stdout


def test_temp_kubeconfig_is_removed(tmp_path):
    h = Hub(tmp_path, deploy=dep(1), ing=ING_ADDR)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    h.run(600, TMPDIR=str(tmpdir))
    assert list(tmpdir.iterdir()) == []


# ── integration with the ALB wait loop of cloudfront-attach-origin.sh ───────────────────────
def run_attach(h, alb_after_calls, kubeconfig_fails=False, **extra):
    """aws describe-load-balancers returns the ALB from call #alb_after_calls on; the script
    then stops at the CloudFront step (no distribution), which is past the loop under test."""
    (h.t / "aws.alb_calls").write_text("0")
    h._fake("aws",
            '#!/usr/bin/env bash\n'
            'echo "$*" >> "$T/aws.calls"\n'
            'case "$*" in\n'
            f'  *update-kubeconfig*) exit {255 if kubeconfig_fails else 0};;\n'
            '  *describe-load-balancers*)\n'
            '     N=$(cat "$T/aws.alb_calls"); N=$((N+1)); echo $N > "$T/aws.alb_calls"\n'
            f'     [ "$N" -ge {alb_after_calls} ] && printf "arn:alb\\tdns\\tinternet-facing\\tactive\\n"; exit 0;;\n'
            '  *list-distributions*) echo None; exit 0;;\n'
            'esac\nexit 0\n')
    return subprocess.run(["bash", ATTACH], env=h.env(**extra), capture_output=True, text=True, timeout=120)


def test_attach_alb_before_threshold_never_touches_the_hub(tmp_path):
    h = Hub(tmp_path, sa=False)
    r = run_attach(h, alb_after_calls=30)  # ALB at ~435 s (< 480)
    assert "lbc-unstick" not in r.stderr, r.stderr
    assert h.read_calls() == "" and h.count("patches") == 0 and h.count("restarts") == 0
    assert "ALB hub-platform" in r.stderr


def test_attach_stalled_alb_triggers_bounded_actions_and_logs(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED)
    r = run_attach(h, alb_after_calls=10_000, ALB_WAIT_SECONDS="1200", HUB_CLUSTER_NAME="hub")
    assert r.returncode == 1  # gave up after the wait budget, as before
    lines = [l for l in r.stderr.splitlines() if "rollout-restart" in l]
    assert len(lines) == 2, r.stderr
    assert h.count("restarts") == 2


def test_attach_alb_appears_after_first_action_stops_acting(tmp_path):
    h = Hub(tmp_path, deploy=dep(0), rs=RS_FAILED)
    r = run_attach(h, alb_after_calls=40)  # ALB at ~585 s: one action at 480, none after
    assert h.count("restarts") == 1, r.stderr
    assert "ALB hub-platform" in r.stderr


def test_attach_survives_a_helper_that_cannot_run(tmp_path):
    h = Hub(tmp_path, sa=False)
    r = run_attach(h, alb_after_calls=40, kubeconfig_fails=True)
    assert "lbc-unstick: no-kubeconfig -> none (-)" in r.stderr
    assert "ALB hub-platform" in r.stderr and h.count("patches") == 0
