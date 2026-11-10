"""install-eso.sh: ESO chart install must survive github.com 504s (repo -> OCI -> vendored).

`helm` is a fake on PATH (no network, no cluster); `sleep` is replaced via ESO_SLEEP so
back-off delays are recorded, not waited. The Taskfile wiring is checked by reading the
tasks' cmds, and the vendored chart is pinned to core.yaml defaultVersion.

Run:  python -m pytest workshop/scripts/tests/test_install_eso_retry.py -q
"""
import os
import hashlib
import re
import shutil
import subprocess
import tarfile

import pytest

yaml = pytest.importorskip("yaml")
if not shutil.which("bash"):
    pytest.skip("bash not available", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT = os.path.join(REPO, "cluster-providers", "common", "scripts", "install-eso.sh")
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
CORE = os.path.join(REPO, "gitops", "addons", "registry", "core.yaml")
VENDOR_DIR = os.path.join(REPO, "gitops", "vendor", "charts")

# Fake helm: `pull` succeeds/fails per FAKE_REPO_FAILS / FAKE_OCI_FAILS (number of leading
# failures, "all" = always); `upgrade` records its args and exits FAKE_UPGRADE_RC.
FAKE_HELM = r"""#!/usr/bin/env bash
echo "helm $*" >> "$FAKE_LOG"
case "$1" in
  pull)
    if [[ " $* " == *" oci://"* ]]; then k=oci; fails="${FAKE_OCI_FAILS:-0}"; else k=repo; fails="${FAKE_REPO_FAILS:-0}"; fi
    c="$FAKE_DIR/count.$k"; n=$(( $(cat "$c" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$c"
    if [ "$fails" = all ] || [ "$n" -le "$fails" ]; then echo "Error: context deadline exceeded" >&2; exit 1; fi
    dest=""; ver=""
    while [ $# -gt 0 ]; do case "$1" in --destination) dest="$2";; --version) ver="$2";; esac; shift; done
    echo chart > "$dest/external-secrets-$ver.tgz"; exit 0;;
  upgrade) exit "${FAKE_UPGRADE_RC:-0}";;
esac
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    helm = bindir / "helm"
    helm.write_text(FAKE_HELM)
    helm.chmod(0o755)
    sl = bindir / "fakesleep"
    sl.write_text('#!/usr/bin/env bash\necho "sleep $1" >> "$FAKE_LOG"\n')
    sl.chmod(0o755)
    vend = tmp_path / "vendor"
    vend.mkdir()
    (vend / "external-secrets-9.9.9.tgz").write_text("vendored")
    (vend / "external-secrets-9.9.9.tgz.sha256").write_text(
        hashlib.sha256(b"vendored").hexdigest() + "  external-secrets-9.9.9.tgz\n")
    e = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_LOG=str(tmp_path / "log"),
             FAKE_DIR=str(tmp_path), ESO_VERSION="9.9.9", ESO_SLEEP=str(sl),
             ESO_VENDORED_DIR=str(vend), ESO_RETRY_BASE="5")
    return e, tmp_path


def run(env, *args):
    e, tmp = env
    p = subprocess.run(["bash", SCRIPT, *args], env=e, capture_output=True, text=True, timeout=60)
    log = (tmp / "log").read_text() if (tmp / "log").exists() else ""
    return p, log


def test_happy_path_one_pull_one_install(env):
    p, log = run(env)
    assert p.returncode == 0, p.stderr
    assert log.count("helm pull") == 1 and "sleep" not in log
    assert "source=repo attempt=1/5: chart fetched" in p.stdout
    assert "installed (source=repo)" in p.stdout


def test_repo_retries_with_backoff_then_succeeds(env):
    env[0]["FAKE_REPO_FAILS"] = "3"
    p, log = run(env)
    assert p.returncode == 0, p.stderr
    assert log.count("helm pull") == 4 and "oci://" not in log
    delays = [int(x) for x in re.findall(r"sleep (\d+)", log)]
    assert len(delays) == 3
    # exponential: base*2^(n-1) <= delay < base*2^(n-1) + base
    for i, d in enumerate(delays):
        assert 5 * 2**i <= d < 5 * 2**i + 5
    assert "source=repo attempt=4/5: chart fetched" in p.stdout


def test_repo_exhausted_falls_back_to_oci(env):
    env[0]["FAKE_REPO_FAILS"] = "all"
    env[0]["FAKE_OCI_FAILS"] = "1"
    p, log = run(env)
    assert p.returncode == 0, p.stderr
    pulls = [l for l in log.splitlines() if l.startswith("helm pull")]
    assert len(pulls) == 5 + 2  # 5 repo attempts, then OCI fails once and succeeds
    assert all("oci://" not in l for l in pulls[:5]) and all("oci://" in l for l in pulls[5:])
    assert "falling back to OCI" in p.stdout and "installed (source=oci)" in p.stdout


def test_all_network_sources_fail_uses_vendored(env):
    env[0]["FAKE_REPO_FAILS"] = "all"
    env[0]["FAKE_OCI_FAILS"] = "all"
    p, log = run(env)
    assert p.returncode == 0, p.stderr
    assert log.count("helm pull") == 7
    assert "falling back to vendored" in p.stdout and "installed (source=vendored)" in p.stdout
    install = [l for l in log.splitlines() if l.startswith("helm upgrade")][0]
    assert install.split()[4].endswith("/vendor/external-secrets-9.9.9.tgz")


def test_vendored_tampered_tgz_is_rejected(env):
    e, tmp = env
    e["FAKE_REPO_FAILS"] = e["FAKE_OCI_FAILS"] = "all"
    (tmp / "vendor" / "external-secrets-9.9.9.tgz").write_text("tampered")
    p, log = run(env)
    assert p.returncode != 0
    assert "sha256 mismatch" in p.stderr and "helm upgrade" not in log


def test_vendored_without_sha256_file_is_rejected(env):
    e, tmp = env
    e["FAKE_REPO_FAILS"] = e["FAKE_OCI_FAILS"] = "all"
    (tmp / "vendor" / "external-secrets-9.9.9.tgz.sha256").unlink()
    p, log = run(env)
    assert p.returncode != 0
    assert "missing checksum file" in p.stderr and "helm upgrade" not in log


def test_no_source_available_fails_nonzero_without_install(env):
    e, tmp = env
    e["FAKE_REPO_FAILS"] = e["FAKE_OCI_FAILS"] = "all"
    e["ESO_VERSION"] = "1.0.0"  # no vendored tgz for this version
    p, log = run(env)
    assert p.returncode == 1
    assert "helm upgrade" not in log
    assert "no vendored chart for 1.0.0" in p.stderr


def test_install_failure_is_not_retried_and_propagates(env):
    env[0]["FAKE_UPGRADE_RC"] = "7"
    p, log = run(env)
    assert p.returncode == 7
    assert log.count("helm upgrade") == 1 and log.count("helm pull") == 1


def test_extra_args_and_timeout_reach_helm_upgrade(env):
    env[0]["ESO_TIMEOUT"] = "10m"
    p, log = run(env, "--", "--set", "tolerations[0].key=CriticalAddonsOnly")
    assert p.returncode == 0, p.stderr
    install = [l for l in log.splitlines() if l.startswith("helm upgrade")][0]
    assert "--set tolerations[0].key=CriticalAddonsOnly" in install
    assert install.endswith("--wait --timeout 10m")
    assert "--namespace external-secrets" in install


def _cmds(task):
    with open(TASKFILE) as f:
        t = yaml.safe_load(f)["tasks"][task]
    return [c for c in t["cmds"] if isinstance(c, str)]


def test_tasks_use_script_hub_timeout_10m_bootstrap_5m():
    hub = "\n".join(_cmds("hub:install-eso"))
    boot = "\n".join(_cmds("kro:install-eso-bootstrap"))
    for body in (hub, boot):
        assert "install-eso.sh" in body
        assert "helm upgrade" not in body and "helm repo add" not in body
    assert "ESO_TIMEOUT=10m" in hub and "--timeout 5m" not in hub
    assert "ESO_TIMEOUT=5m" in boot
    assert "CriticalAddonsOnly" in hub  # seed-safe tolerations preserved


def test_vendored_chart_matches_core_yaml_default_version():
    with open(CORE) as f:
        ver = str(yaml.safe_load(f)["external-secrets"]["defaultVersion"])
    tgz = os.path.join(VENDOR_DIR, f"external-secrets-{ver}.tgz")
    assert os.path.isfile(tgz), (
        f"core.yaml external-secrets.defaultVersion={ver} but {tgz} is missing: "
        f"vendor it with `helm pull oci://ghcr.io/external-secrets/charts/external-secrets "
        f"--version {ver} -d gitops/vendor/charts` and remove the old tgz")
    others = [n for n in os.listdir(VENDOR_DIR) if n.endswith(".tgz") and n != os.path.basename(tgz)]
    assert not others, f"stale vendored charts: {others}"
    with tarfile.open(tgz) as t:
        chart = yaml.safe_load(t.extractfile("external-secrets/Chart.yaml"))
    assert str(chart["version"]) == ver
    sumfile = tgz + ".sha256"
    assert os.path.isfile(sumfile), f"missing {sumfile}: sha256sum {os.path.basename(tgz)} > {os.path.basename(sumfile)}"
    want, name = open(sumfile).read().split()
    assert name == os.path.basename(tgz)
    with open(tgz, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == want, "vendored tgz does not match its .sha256"


# --- kind-crossplane / byoc: same script, same fallback chain -------------------------------
PROVIDERS = ["kind-crossplane", "byoc"]


def _provider_taskfile(provider):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        return yaml.safe_load(f)


def _provider_eso_version(provider):
    """Resolve ESO_VERSION exactly as the Taskfile does (GITOPS_ROOT + yq path), no stub value."""
    t = _provider_taskfile(provider)
    root = t["vars"]["GITOPS_ROOT"].replace("{{.ROOT_DIR}}", REPO)
    m = re.search(r"yq '(\.[\w.-]+)' \{\{\.GITOPS_ROOT\}\}(\S+)", t["tasks"]["hub:install-eso"]["vars"]["ESO_VERSION"]["sh"])
    assert m, "ESO_VERSION sh no longer matches the expected yq form"
    path = root + m.group(2)
    assert os.path.isfile(path), f"{provider}: ESO_VERSION reads {path}, which does not exist"
    doc = yaml.safe_load(open(path))
    for k in m.group(1).strip(".").split("."):
        doc = doc[k]
    return str(doc)


def _provider_cmd(provider):
    t = _provider_taskfile(provider)["tasks"]["hub:install-eso"]
    body = "\n".join(c for c in t["cmds"] if isinstance(c, str))
    assert "helm upgrade" not in body and "helm repo add" not in body
    cmd = [l for l in body.splitlines() if "install-eso.sh" in l][0].lstrip("- ").strip()
    return (cmd.replace("{{.ROOT_DIR}}", REPO).replace("{{.ESO_VERSION}}", _provider_eso_version(provider)))


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("repo,oci,source", [(0, 0, "repo"), ("all", 0, "oci"), ("all", "all", "vendored")])
def test_provider_task_uses_fallback_chain(env, provider, repo, oci, source):
    e, tmp = env
    e["FAKE_REPO_FAILS"], e["FAKE_OCI_FAILS"] = str(repo), str(oci)
    e["ESO_RETRY_ATTEMPTS"] = e["ESO_OCI_ATTEMPTS"] = "2"
    cmd = _provider_cmd(provider)  # real ESO_VERSION, resolved from the provider's own GITOPS_ROOT
    ver = re.search(r"ESO_VERSION=(\S+)", cmd).group(1)
    vend = e["ESO_VENDORED_DIR"]  # fixture vendors 9.9.9 only; give it the real version too
    for suf in ("", ".sha256"):
        n = f"external-secrets-{ver}.tgz{suf}"
        data = open(os.path.join(vend, f"external-secrets-9.9.9.tgz{suf}")).read().replace("9.9.9", ver)
        open(os.path.join(vend, n), "w").write(data)
    p = subprocess.run(["bash", "-c", cmd], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert f"installed (source={source})" in p.stdout
    log = open(e["FAKE_LOG"]).read()
    install = [l for l in log.splitlines() if l.startswith("helm upgrade")][0]
    assert "--set serviceAccount.name=external-secrets-sa" in install
    assert install.endswith("--wait --timeout 5m")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_gitops_paths_exist(provider):
    """Every {{.GITOPS_ROOT}}/<path> the provider applies/reads must exist (byoc had GITOPS_ROOT one level too high)."""
    raw = open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")).read()
    root = _provider_taskfile(provider)["vars"]["GITOPS_ROOT"].replace("{{.ROOT_DIR}}", REPO)
    for rel in set(re.findall(r"\{\{\.GITOPS_ROOT\}\}(/(?:addons/registry|bootstrap)/[\w.-]+\.yaml)", raw)):
        assert os.path.isfile(root + rel), f"{provider}: {root + rel} missing"
