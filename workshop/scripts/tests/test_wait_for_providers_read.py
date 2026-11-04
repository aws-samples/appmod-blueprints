"""Hermetic test for kind-kro-ack hub:wait-for-providers: it must read provider health from the
table (HEALTHY column), not from a nested-filter JSONPath that kubectl rejects. The shell block
runs with bash against a fake `kubectl` and a no-op `sleep`. No cluster.

Run:  python -m pytest workshop/scripts/tests/test_wait_for_providers_read.py -q
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
TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")


def _block():
    cmds = yaml.safe_load(open(TASKFILE))["tasks"]["hub:wait-for-providers"]["cmds"]
    b = [c for c in cmds if isinstance(c, str) and "providers.pkg.crossplane.io" in c][0]
    b = b.replace("{{.ROOT_DIR}}", "/nonexistent").replace("{{.HUB_CLUSTER_NAME}}", "hub")
    return re.sub(r"\{\{\s*\.C_[A-Z]+\s*\}\}", "", b)


def _run(tmp_path, tables):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for i, t in enumerate(tables):
        (tmp_path / f"t{i}").write_text(t)
    (bin_ / "kubectl").write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in *jsonpath*) echo "error: unterminated filter" >&2; exit 1;; esac\n'
        'case "$*" in *patch*) exit 0;; *"-o json"*) echo "{}"; exit 0;; esac\n'
        'N=$(cat "$T/n" 2>/dev/null || echo 0); echo $((N+1)) > "$T/n"\n'
        'F="$T/t$N"; [ -f "$F" ] || F=$(ls "$T"/t* | sort -V | tail -1); cat "$F"\n')
    (bin_ / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in ("kubectl", "sleep"):
        os.chmod(bin_ / f, 0o755)
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", T=str(tmp_path))
    return subprocess.run(["bash", "-c", _block()], env=env, capture_output=True, text=True, timeout=60)


HEALTHY = "provider-aws-iam True True xpkg/iam 5m\nprovider-aws-eks True True xpkg/eks 5m\n"
ONE_BAD = "provider-aws-iam True False xpkg/iam 1m\nprovider-aws-eks True True xpkg/eks 1m\n"


def test_all_healthy_passes_on_first_poll(tmp_path):
    r = _run(tmp_path, [HEALTHY])
    assert "All 2 Crossplane providers Healthy" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "n").read_text().strip() == "1"


def test_waits_for_an_unhealthy_provider(tmp_path):
    r = _run(tmp_path, [ONE_BAD, ONE_BAD, HEALTHY])
    assert "All 2 Crossplane providers Healthy" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "n").read_text().strip() == "3"
