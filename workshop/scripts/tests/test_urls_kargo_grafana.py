"""Hermetic go-task test: `task urls` prints the real Kargo and Grafana URLs.

Kargo is served under /kargo on the platform ingress ("/" is Langfuse). Grafana is the Amazon
Managed Grafana (AMG) workspace <prefix>-observability with its own endpoint: <ingress>/grafana
is a 404. Both providers (kind-kro-ack, kind-crossplane) carry the same printout.

Run:  python -m pytest workshop/scripts/tests/test_urls_kargo_grafana.py -q
"""
import os
import shutil
import subprocess

import pytest

TASK = shutil.which("task")
if not TASK or not shutil.which("yq"):
    pytest.skip("go-task and yq are needed", allow_module_level=True)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# FAKE_AMG: ok = workspace exists, none = list-workspaces returns None, denied = every
# `aws grafana` call fails (expired token), badep = endpoint with shell characters.
FAKE_AWS = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_AWS_LOG"
case "$1 $2" in
  "eks describe-capability") echo "https://argocd.example.invalid" ;;
  "grafana list-workspaces")
    case "$FAKE_AMG" in
      denied) echo "An error occurred (ExpiredTokenException) when calling the ListWorkspaces operation" >&2; exit 254 ;;
      none) echo None ;;
      *) echo g-0123456789 ;;
    esac ;;
  "grafana describe-workspace")
    if [ "$FAKE_AMG" = badep ]; then echo "g-1.example.com';touch $FAKE_PWN;'"; else echo g-0123456789.grafana-workspace.us-west-2.amazonaws.com; fi ;;
  *) echo ok ;;
esac
"""

PROVIDERS = ["kind-kro-ack", "kind-crossplane"]


def _run(tmp_path, provider, amg):
    r = tmp_path / "repo"
    r.mkdir()
    shutil.copy(os.path.join(REPO, "Taskfile.yaml"), r / "Taskfile.yaml")
    shutil.copytree(os.path.join(REPO, "cluster-providers"), r / "cluster-providers")
    (r / "scripts").mkdir()
    shutil.copy(os.path.join(REPO, "scripts", "install-timing.sh"), r / "scripts" / "install-timing.sh")
    shutil.copytree(os.path.join(REPO, "gitops", "addons", "registry"), r / "gitops" / "addons" / "registry")
    (r / "workshop").mkdir()
    shutil.copy(os.path.join(REPO, "workshop", "Taskfile.yaml"), r / "workshop" / "Taskfile.yaml")
    (r / "config.local.yaml").write_text(
        f"clusterProvider: {provider}\nresourcePrefix: acme\ndomain: dxyz.cloudfront.example\n"
        "aws: {region: us-west-2}\nhub: {clusterName: acme-hub}\n")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "aws").write_text(FAKE_AWS)
    (bindir / "aws").chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_AWS_LOG=str(log),
               FAKE_AMG=amg, FAKE_PWN=str(tmp_path / "pwned"), HOME=str(tmp_path), TMPDIR=str(tmp_path))
    for k in ("AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_DEFAULT_PROFILE", "KUBECONFIG"):
        env.pop(k, None)
    res = subprocess.run([TASK, "-d", str(r), f"{provider}:urls"], env=env,
                         capture_output=True, text=True, timeout=120)
    return res, res.stdout + res.stderr


@pytest.mark.parametrize("provider", PROVIDERS)
def test_kargo_path_and_amg_endpoint(tmp_path, provider):
    res, out = _run(tmp_path, provider, "ok")
    assert res.returncode == 0, out
    assert "Kargo:      https://dxyz.cloudfront.example/kargo\n" in out, out
    assert ("Grafana:    https://g-0123456789.grafana-workspace.us-west-2.amazonaws.com\n") in out, out
    assert "dxyz.cloudfront.example/grafana" not in out, out
    assert "ArgoCD:     https://argocd.example.invalid" in out, out
    # still no passwords in the printout
    assert "get-secret-value" in out and "password: key" in out, out


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("amg", ["none", "denied", "badep"])
def test_no_amg_prints_a_clear_fallback_not_a_404_path(tmp_path, provider, amg):
    res, out = _run(tmp_path, provider, amg)
    assert res.returncode == 0, out
    assert "Grafana:    (Amazon Managed Grafana acme-observability not found or not readable" in out, out
    assert "dxyz.cloudfront.example/grafana" not in out, out
    assert "Kargo:      https://dxyz.cloudfront.example/kargo\n" in out, out
    assert not (tmp_path / "pwned").exists(), "endpoint was evaluated by a shell"
