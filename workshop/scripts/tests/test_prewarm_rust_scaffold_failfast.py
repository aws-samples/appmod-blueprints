"""Hermetic tests for prewarm-rust-cicd when Backstage answers but the scaffold fails.

A scaffold that fails fast (seen: 1 s) has nothing in flight server-side, so the task
used to wait its full PIPE_T (600 s) for a CICDPipeline nobody would create. It now
retries once after 30 s, then stops with a clear message. A slow failure (the helper's
30x10s poll ran out) may still be wiring the repo, so it keeps the pipeline wait.

Reuses the fakes and virtual clock of test_prewarm_rust_waits.py.

Run:  python -m pytest workshop/scripts/tests/test_prewarm_rust_scaffold_failfast.py -q
"""
import os
import subprocess

import pytest

pytest.importorskip("yaml")
from test_prewarm_rust_waits import fakes, lines, render  # noqa: E402


def helper(plat, body):
    (plat / "scripts" / "validation" / "backstage-auth.sh").write_text(
        'backstage_scaffolder() {\n'
        '  C=$(cat "$FAKE_T/clock"); echo "$C scaffold" >> "$FAKE_T/scaffold.calls"\n'
        f'{body}\n'
        '}\n')


def run(tmp_path, body):
    b, plat = fakes(tmp_path)          # Backstage and workflow-controller up at t=0
    helper(plat, body)
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", FAKE_T=str(tmp_path), HOME=str(tmp_path))
    r = subprocess.run(["bash", "-c", render("prewarm-rust-cicd", plat)], env=env,
                       capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    return r, int((tmp_path / "clock").read_text())


def test_fast_failure_twice_fails_fast(tmp_path):
    r, clock = run(tmp_path, '  return 1')
    assert r.returncode == 0
    assert "retrying once in 30s" in r.stdout, r.stdout
    assert "scaffold failed in 0s on attempt 2 although Backstage answers" in r.stdout, r.stdout
    assert "task prewarm-rust-cicd" in r.stdout
    assert "waiting for CICDPipeline" not in r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 2
    assert clock == 30, clock          # before: 600 s of pipeline wait


def test_fast_failure_then_success_on_retry(tmp_path):
    body = ('  if [ -f "$FAKE_T/tried" ]; then touch "$FAKE_T/scaffolded"; return 0; fi\n'
            '  touch "$FAKE_T/tried"; return 1')
    r, clock = run(tmp_path, body)
    assert "retrying once in 30s" in r.stdout, r.stdout
    assert "scaffolder task completed" in r.stdout
    assert "✓ CICDPipeline rust-cicd-pipeline ACTIVE." in r.stdout, r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 2
    assert clock == 30, clock


def test_slow_failure_keeps_pipeline_wait(tmp_path):
    # The helper's poll ran out after 300 s: the task may still be wiring server-side.
    r, clock = run(tmp_path, '  sleep 300; return 1')
    assert "continuing to wait for the pipeline anyway" in r.stdout, r.stdout
    assert "retrying once" not in r.stdout
    assert "waiting for CICDPipeline" in r.stdout
    assert len(lines(tmp_path, "scaffold.calls")) == 1
    assert clock == 300 + 600, clock
