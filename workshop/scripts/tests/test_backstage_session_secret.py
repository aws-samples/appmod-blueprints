"""Hermetic test: Backstage auth.session.secret must come from a Secret, never the ConfigMap.

The chart's app-config must reference ${BACKSTAGE_SESSION_SECRET} (no literal value), the
backstage-session ExternalSecret must feed backstage-session-vars, and the container must
load that Secret via envFrom.

Run:  python -m pytest workshop/scripts/tests/test_backstage_session_secret.py -q
"""
import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
INSTALL = os.path.join(REPO, "gitops", "addons", "charts", "backstage", "templates", "install.yaml")


def _text():
    with open(INSTALL) as f:
        return f.read()


def test_session_secret_is_env_reference_not_literal():
    m = re.search(r"^\s+session:\s*\n\s+secret:\s*(\S+)\s*$", _text(), re.M)
    assert m, "auth.session.secret not found"
    assert m.group(1) == "${BACKSTAGE_SESSION_SECRET}"


def test_session_secret_wired_from_external_secret():
    t = _text()
    assert "name: backstage-session-vars" in t
    assert "property: backstage_session_secret" in t
    assert re.search(r"secretRef:\s*\n\s+name: backstage-session-vars", t)
