"""Hermetic tests for the two Rust prewarm waits.

prewarm-pathA-rust-kro: the AppmodService CRD check on spoke-dev is a bounded wait loop
(same as prewarm-pathA-frontend), not a single check made seconds after the spokes go
ACTIVE, which skipped the whole pre-deploy while the spoke was still syncing its RGDs.

prewarm-rust-cicd: on a slow first hub sync the Backstage Deployment (and the Argo
Workflows controller) did not exist yet when the prewarm ran. The scaffold failed in 1 s,
nothing retried it, and the task then waited its full PIPE_T for a CICDPipeline nobody
would create. The task now waits (bounded) for Backstage to answer before scaffolding,
and for the workflow-controller Deployment to exist before `rollout status`.

Fakes: kubectl, aws, curl, git, and a virtual clock (`sleep` advances it, `date +%s` reads
it), so waits are measured in virtual seconds and the tests run instantly. The Backstage
helper script is replaced by a fake whose scaffold only succeeds when Backstage is up.

Run:  python -m pytest workshop/scripts/tests/test_prewarm_rust_waits.py -q
"""
import os
import re
import shutil
import subprocess

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TASKFILE = os.path.join(REPO, "workshop", "Taskfile.yaml")

VARS = {
    "APP_NAME": "rust", "APP_NS": "team-rust", "AWS_REGION": "r", "AWS_ACCOUNT_ID": "000000000000",
    "BUILD_TIMEOUT": "900", "PIPELINE_TIMEOUT": "600", "CLOUDFRONT_DOMAIN": "cf.example", "DOMAIN": "",
    "ENABLED": "true", "CICD_ENABLED": "true", "GIT_DOMAIN": "git.example", "GIT_TOKEN": "",
    "GIT_PASSWORD": "pw", "GIT_USERNAME": "user1", "HUB_CLUSTER_NAME": "hub",
    "INSTALL_BUDGET_SEC": "6600", "INSTALL_START": "1000000", "RESOURCE_PREFIX": "p", "USER_PASSWORD": "pw",
}


def render(task, plat, text=None):
    b = yaml.safe_load(text if text is not None else open(TASKFILE))["tasks"][task]["cmds"][0]
    b = b.replace("{{.PLATFORM_DIR}}", str(plat))
    b = re.sub(r"\{\{\s*\.C_[A-Z]+\s*\}\}", "", b)
    return re.sub(r"\{\{\s*\.([A-Z_]+)\s*\}\}", lambda m: VARS.get(m.group(1), ""), b)


# Fake authenticated catalog read: 200 once Backstage is up. Tests that need another
# answer append their own backstage_template_status after this one (last one wins).
TEMPLATE_STATUS_OK = (
    'backstage_template_status() {{\n'
    '  C=$(cat "$FAKE_T/clock"); echo "$C template" >> "$FAKE_T/template.calls"\n'
    '  if [ "$C" -ge {backstage_at} ]; then echo 200; else echo 503; fi\n'
    '}}\n')


def fakes(tmp_path, crd_at=0, backstage_at=0, wfc_at=0, cd_at=0):
    """crd_at / backstage_at / wfc_at / cd_at: virtual second at which the AppmodService
    CRD on spoke-dev, Backstage, the workflow-controller Deployment and the rust-dev-cd
    Argo CD app appear."""
    b = tmp_path / "bin"
    b.mkdir()
    plat = tmp_path / "plat"
    (plat / "scripts" / "validation").mkdir(parents=True)
    (tmp_path / "clock").write_text("0")
    now = 'C=$(cat "$FAKE_T/clock")'
    (b / "sleep").write_text(f'#!/usr/bin/env bash\n{now}; echo $((C + ${{1%s}})) > "$FAKE_T/clock"\n')
    (b / "date").write_text(
        '#!/usr/bin/env bash\n'
        f'if [ "$1" = "+%s" ]; then {now}; echo $((1000000 + C)); else /bin/date "$@"; fi\n')
    (b / "aws").write_text('#!/usr/bin/env bash\ncase "$*" in *list-images*) echo 0;; esac\nexit 0\n')
    (b / "git").write_text('#!/usr/bin/env bash\necho "git $*" >> "$FAKE_T/git.calls"; exit 1\n')
    (b / "curl").write_text(
        '#!/usr/bin/env bash\n'
        f'{now}; echo "$C curl $*" >> "$FAKE_T/curl.calls"\n'
        f'if [ "$C" -ge {backstage_at} ]; then echo 401; else echo 503; fi\n')
    (b / "kubectl").write_text(
        '#!/usr/bin/env bash\n'
        f'{now}\n'
        'case "$*" in\n'
        f'  *"get crd appmodservices.kro.run"*) echo "$C crd" >> "$FAKE_T/crd.calls"; [ "$C" -ge {crd_at} ];;\n'
        f'  *"get applications.argoproj.io"*) [ "$C" -ge {cd_at} ];;\n'
        f'  *"get deploy/backstage"*) [ "$C" -ge {backstage_at} ];;\n'
        f'  *"get deploy/workflow-controller"*) [ "$C" -ge {wfc_at} ];;\n'
        f'  *"rollout status deploy/workflow-controller"*) [ "$C" -ge {wfc_at} ];;\n'
        '  *"get crd workflows.argoproj.io"*) exit 0;;\n'
        '  *"logs deploy/backstage"*) cat "$FAKE_T/backstage.log" 2>/dev/null; exit 0;;\n'
        '  *"get cicdpipeline"*"jsonpath"*) [ -f "$FAKE_T/scaffolded" ] && echo ACTIVE; exit 0;;\n'
        '  *"get cicdpipeline"*) [ -f "$FAKE_T/scaffolded" ] && echo cicdpipeline/rust-cicd-pipeline; exit 0;;\n'
        '  *) exit 0;;\n'
        'esac\n')
    for f in ("sleep", "date", "aws", "git", "curl", "kubectl"):
        os.chmod(b / f, 0o755)
    # Fake Backstage helper: the scaffold succeeds only when Backstage is up.
    (plat / "scripts" / "validation" / "backstage-auth.sh").write_text(
        'backstage_scaffolder() {\n'
        f'  {now}; echo "$C scaffold" >> "$FAKE_T/scaffold.calls"\n'
        f'  if [ "$C" -ge {backstage_at} ]; then touch "$FAKE_T/scaffolded"; return 0; fi; return 1\n'
        '}\n'
        + TEMPLATE_STATUS_OK.format(backstage_at=backstage_at))
    return b, plat


def run(tmp_path, task, text=None, **at):
    b, plat = fakes(tmp_path, **at)
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path))
    r = subprocess.run(["bash", "-c", render(task, plat, text)], env=env,
                       capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    clock = int((tmp_path / "clock").read_text())
    return r, clock


def lines(tmp_path, name):
    p = tmp_path / name
    return p.read_text().splitlines() if p.exists() else []


# ── prewarm-pathA-rust-kro ─────────────────────────────────────────────────────────────
def test_rust_kro_waits_for_late_crd(tmp_path):
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", crd_at=60)
    assert "AppmodService CRD not served" not in r.stdout, r.stdout
    # it went on to the clone step (fake git fails there: proves the CRD gate passed)
    assert "could not clone" in r.stdout, r.stdout
    assert clock == 60
    assert len(lines(tmp_path, "crd.calls")) == 5


def test_rust_kro_crd_wait_is_bounded(tmp_path):
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", crd_at=10_000)
    assert "AppmodService CRD not served on p-spoke-dev after 900s" in r.stdout, r.stdout
    assert "retry: cd ~/environment/platform-on-eks-workshop/workshop && task prewarm-pathA-rust-kro" in r.stdout
    assert clock == 900
    assert r.returncode == 0


def test_rust_kro_waits_for_crd_served_after_300s(tmp_path):
    # Seen on an event: the CRD was still not served 300 s after the wait started (the
    # spoke's kro capability had been created ~2 min earlier). A 300 s wait skipped.
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", crd_at=600)
    assert "AppmodService CRD not served" not in r.stdout, r.stdout
    assert "could not clone" in r.stdout, r.stdout
    assert clock == 600


def test_rust_kro_crd_wait_capped_by_install_budget(tmp_path, monkeypatch):
    # left() still caps the wait: only 300 s of budget left before DEADLINE
    # (INSTALL_START + INSTALL_BUDGET_SEC - 300 - 120 - 300).
    monkeypatch.setitem(VARS, "INSTALL_START", str(1000000 - (6600 - 300 - 120 - 300) + 300))
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", crd_at=10_000)
    assert "AppmodService CRD not served on p-spoke-dev after 300s" in r.stdout, r.stdout
    assert clock == 300


def test_rust_kro_waits_for_late_rust_dev_cd(tmp_path):
    # In the install's background job, rust-dev-cd can appear after the job reaches
    # this task (the foreground Rust CI/CD prewarm is still running).
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", cd_at=600)
    assert "not found after" not in r.stdout, r.stdout
    assert "could not clone" in r.stdout, r.stdout
    assert clock == 600


def test_rust_kro_rust_dev_cd_wait_is_bounded(tmp_path):
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", cd_at=10_000)
    assert "Argo CD app rust-dev-cd not found after 900s" in r.stdout, r.stdout
    assert lines(tmp_path, "crd.calls") == []
    assert clock == 900
    assert r.returncode == 0


def test_rust_kro_crd_already_served_no_wait(tmp_path):
    r, clock = run(tmp_path, "prewarm-pathA-rust-kro", crd_at=0)
    assert clock == 0
    assert "could not clone" in r.stdout


# ── prewarm-rust-cicd ──────────────────────────────────────────────────────────────────
def test_cicd_waits_for_backstage_then_scaffolds(tmp_path):
    # Backstage and the workflow-controller come up 5 min after the prewarm starts (seen on a slow first hub sync).
    r, clock = run(tmp_path, "prewarm-rust-cicd", backstage_at=300, wfc_at=240)
    assert r.returncode == 0
    assert "scaffolder task completed" in r.stdout, r.stdout
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert "workflow-controller not Ready" not in r.stdout
    calls = lines(tmp_path, "scaffold.calls")
    assert len(calls) == 1 and int(calls[0].split()[0]) >= 300
    assert clock < 400, clock     # before: 600 s of pipeline wait and no pipeline


def test_cicd_backstage_wait_is_bounded_and_skips_pipeline_wait(tmp_path):
    r, clock = run(tmp_path, "prewarm-rust-cicd", backstage_at=10_000)
    assert "Backstage not answering after 600s" in r.stdout, r.stdout
    assert lines(tmp_path, "scaffold.calls") == []
    assert "waiting for CICDPipeline" not in r.stdout
    assert r.returncode == 0


def test_cicd_backstage_up_no_extra_wait(tmp_path):
    r, clock = run(tmp_path, "prewarm-rust-cicd")
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert clock == 0
