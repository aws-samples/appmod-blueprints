"""Hermetic tests for the observability convergence gate (kind-kro-ack and kind-crossplane).

`observability:converged` decides whether the Grafana/AMP keys of a hub are usable:
  * every key is present (grafana_api_key, amp_endpoint_url, amp_region, <hub>/config
    metadata.aws_grafana_url, <prefix>/platform/amp);
  * the Grafana token does NOT expire within GRAFANA_TOKEN_MIN_DAYS (default 7). The expiry
    comes from grafana_api_key_expires_at (written by seed-observability) or, for hubs seeded
    before that key existed, from the newest token of the seed's AMG service accounts;
  * one light AMG API call with the token does not answer 401/403. A network error or a 5xx
    is inconclusive and must NOT invalidate the token (every re-seed mints a new AMG SA).

`install:phase1-observability-bg` must skip the background seed when the gate passes, so that
re-running `task install` on a seeded hub does not mint a new AMG service account each time.

The tasks' cmds are read verbatim from the provider Taskfiles and run under go-task's own
interpreter with the Taskfile's `set:` options. `aws`, `curl` and `task` (for the nested
calls of phase1-observability-bg) are fakes on PATH. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_observability_converged.py -q
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROVIDERS = ("kind-kro-ack", "kind-crossplane")
TASK = shutil.which("task")
HUB, PREFIX, REGION, ACCOUNT = "acme-hub", "acme", "us-west-2", "111122223333"
AMG_HOST = "g-0123abcd.grafana-workspace.us-west-2.amazonaws.com"
TOKEN = "glsa_not-a-real-token_0123456789"
COLORS = ("C_ERR", "C_RESET", "C_OK", "C_INFO", "C_STEP", "C_WARN")
DAY = 86400

pytestmark = pytest.mark.skipif(TASK is None, reason="go-task not on PATH")

FAKE_AWS = r'''#!{python} -I
import json, os, sys
st = json.load(open(os.environ["FAKE_STATE"]))
svc, op, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
opts, i = {}, 0
while i < len(rest):
    if rest[i].startswith("--") and i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        opts[rest[i][2:]] = rest[i + 1]; i += 2
    else:
        i += 1
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["aws", svc, op, opts]) + "\n")
if svc == "secretsmanager" and op == "get-secret-value":
    v = st["secrets"].get(opts["secret-id"])
    if v is None:
        sys.stderr.write("ResourceNotFoundException\n"); sys.exit(254)
    print(v)
elif svc == "secretsmanager" and op == "describe-secret":
    sys.exit(0 if opts["secret-id"] in st["secrets"] else 254)
elif svc == "grafana" and op == "list-workspaces":
    print(st["amg_ws"] or "")
elif svc == "grafana" and op == "describe-workspace":
    print(st["amg_tag"])
elif svc == "grafana" and op == "list-workspace-service-accounts":
    print("\t".join(st["sa_tokens"].keys()))
elif svc == "grafana" and op == "list-workspace-service-account-tokens":
    print(json.dumps({"serviceAccountTokens": st["sa_tokens"].get(opts["service-account-id"], [])}))
else:
    sys.stderr.write("fake aws: unexpected call %s %s\n" % (svc, op)); sys.exit(2)
'''

# curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H @<file> https://<host>/api/org
FAKE_CURL = r'''#!{python} -I
import json, os, sys
st = json.load(open(os.environ["FAKE_STATE"]))
args = sys.argv[1:]
hdr = ""
for i, a in enumerate(args):
    if a == "-H" and args[i + 1].startswith("@"):
        hdr = open(args[i + 1][1:]).read()
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["curl", args[-1], hdr.strip() == "Authorization: Bearer " + st["token"],
                        st["token"] in " ".join(args)]) + "\n")
if st["curl"] == "fail":
    sys.stdout.write("000"); sys.exit(28)
sys.stdout.write(str(st["curl"]))
'''

# Stands in for the nested `task kind-<provider>:...` calls of phase1-observability-bg.
FAKE_TASK = r'''#!{python} -I
import json, os, sys
st = json.load(open(os.environ["FAKE_STATE"]))
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(["task"] + sys.argv[1:]) + "\n")
if any(a.endswith(":observability:converged") for a in sys.argv[1:]):
    sys.exit(0 if st["converged"] else 1)
sys.exit(0)
'''


def _iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000000+00:00", time.gmtime(epoch))


def _state(**kw):
    now = int(time.time())
    secrets = {
        f"{HUB}/secrets": {"grafana_api_key": TOKEN, "amp_endpoint_url": "https://aps.example/ws/",
                           "amp_region": REGION, "grafana_api_key_expires_at": str(now + 20 * DAY + DAY // 2)},
        f"{HUB}/config": {"metadata": json.dumps({"aws_grafana_url": AMG_HOST})},
        f"{PREFIX}/platform/amp": {},
    }
    st = {"secrets": secrets, "token": TOKEN, "curl": 200, "amg_ws": "g-0123abcd",
          "amg_tag": f"{PREFIX}-amg", "sa_tokens": {}, "converged": True}
    st.update(kw)
    st["secrets"] = {k: (json.dumps(v) if isinstance(v, dict) else v)
                     for k, v in st["secrets"].items() if v is not None}
    return st


def _task(provider, name):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        return yaml.safe_load(f)["tasks"][name]


def _run(tmp_path, provider, name, state, env_extra=None):
    t = _task(provider, name)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for fname, body in (("aws", FAKE_AWS), ("curl", FAKE_CURL), ("task", FAKE_TASK)):
        (bindir / fname).write_text(body.replace("{python}", sys.executable))
        (bindir / fname).chmod(0o755)
    st, log = tmp_path / "state.json", tmp_path / "calls.jsonl"
    st.write_text(json.dumps(state))
    log.write_text("")
    env = {k: v for k, v in os.environ.items() if k != "GRAFANA_TOKEN_MIN_DAYS"}
    env.update(PATH=f"{bindir}:{os.environ['PATH']}", FAKE_STATE=str(st), FAKE_LOG=str(log),
               **(env_extra or {}))
    tvars = dict({k: "" for k in COLORS}, HUB_CLUSTER_NAME=HUB, RESOURCE_PREFIX=PREFIX,
                 AWS_REGION=REGION, AWS_ACCOUNT_ID=ACCOUNT)
    task = {"cmds": t["cmds"]}
    if "vars" in t:
        task["vars"] = t["vars"]
    tf = tmp_path / "Taskfile.yaml"   # phase1-observability-bg checks $ROOT_DIR/Taskfile.yaml
    tf.write_text(yaml.safe_dump({"version": "3", "set": ["errexit", "nounset", "pipefail"],
                                  "vars": tvars, "tasks": {"run": task}}, sort_keys=False))
    res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=120)
    time.sleep(0.3)  # let a detached background job (phase1) log its call
    calls = [json.loads(l) for l in log.read_text().splitlines() if l]
    return res, calls


def _converged(tmp_path, provider, env_extra=None, **kw):
    return _run(tmp_path, provider, "observability:converged", _state(**kw), env_extra)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_valid_token_is_converged(tmp_path, provider):
    res, calls = _converged(tmp_path, provider)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"observability keys seeded for {HUB}" in res.stdout
    assert "token accepted by AMG" in res.stdout and "expires in 20d" in res.stdout, res.stdout
    curl = [c for c in calls if c[0] == "curl"]
    assert curl == [["curl", f"https://{AMG_HOST}/api/org", True, False]], calls


@pytest.mark.parametrize("provider", PROVIDERS)
def test_missing_key_is_reported(tmp_path, provider):
    st = _state()
    st["secrets"][f"{HUB}/secrets"] = json.dumps({"amp_endpoint_url": "x", "amp_region": REGION})
    res, calls = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout
    assert f"observability keys missing: {HUB}/secrets:grafana_api_key" in res.stdout
    assert not [c for c in calls if c[0] == "curl"], "no API call without a token"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_token_expiring_soon_is_invalid(tmp_path, provider):
    st = _state()
    s = json.loads(st["secrets"][f"{HUB}/secrets"])
    s["grafana_api_key_expires_at"] = str(int(time.time()) + 3 * DAY + DAY // 2)
    st["secrets"][f"{HUB}/secrets"] = json.dumps(s)
    res, calls = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout
    assert "observability token invalid: grafana_api_key expires in 3d (< 7d, recorded expiry)" in res.stdout
    assert not [c for c in calls if c[0] == "curl"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_min_days_is_configurable(tmp_path, provider):
    # 20 days left: valid with the default 7, invalid with 25.
    res, _ = _converged(tmp_path, provider, env_extra={"GRAFANA_TOKEN_MIN_DAYS": "25"})
    assert res.returncode != 0, res.stdout
    assert "(< 25d, recorded expiry)" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("code", [401, 403])
def test_token_rejected_by_amg_is_invalid(tmp_path, provider, code):
    res, _ = _converged(tmp_path, provider, curl=code)
    assert res.returncode != 0, res.stdout
    assert f"grafana_api_key rejected by AMG (HTTP {code})" in res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("code", ["fail", 500])
def test_inconclusive_api_check_does_not_invalidate(tmp_path, provider, code):
    res, _ = _converged(tmp_path, provider, curl=code)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "AMG check inconclusive" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
def test_legacy_hub_uses_newest_seed_token_expiry(tmp_path, provider):
    now = int(time.time())
    st = _state(sa_tokens={
        "5": [{"id": "a", "name": "token-crossplane-1", "createdAt": _iso(now - 28 * DAY),
               "expiresAt": _iso(now + 1 * DAY + DAY // 2)}],
        "7": [{"id": "b", "name": "token-crossplane-2", "createdAt": _iso(now - 1 * DAY),
               "expiresAt": _iso(now + 28 * DAY + DAY // 2)}]})
    s = json.loads(st["secrets"][f"{HUB}/secrets"])
    del s["grafana_api_key_expires_at"]
    st["secrets"][f"{HUB}/secrets"] = json.dumps(s)
    res, _ = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "expires in 28d" in res.stdout, res.stdout
    # Only the older token left, close to expiry -> invalid.
    st["sa_tokens"] = {"5": st["sa_tokens"]["5"]}
    res, _ = _run(_fresh(tmp_path), provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout
    assert "expires in 1d (< 7d, newest AMG token expiry)" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
def test_legacy_hub_without_amg_lookup_relies_on_api(tmp_path, provider):
    st = _state(amg_ws="")
    s = json.loads(st["secrets"][f"{HUB}/secrets"])
    del s["grafana_api_key_expires_at"]
    st["secrets"][f"{HUB}/secrets"] = json.dumps(s)
    res, _ = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "token accepted by AMG, expiry unknown" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
def test_token_never_printed(tmp_path, provider):
    for code in (200, 401):
        res, calls = _converged(_fresh(tmp_path), provider, curl=code)
        assert TOKEN not in res.stdout + res.stderr
        assert all(not c[3] for c in calls if c[0] == "curl"), "token passed as a curl argument"


def _fresh(tmp_path):
    d = tmp_path / f"r{len(list(tmp_path.iterdir()))}"
    d.mkdir()
    return d


@pytest.mark.parametrize("provider", PROVIDERS)
def test_install_skips_background_seed_when_converged(tmp_path, provider):
    res, calls = _run(tmp_path, provider, "install:phase1-observability-bg", _state(converged=True))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "background seed skipped" in res.stdout, res.stdout
    tasks = [c[1:] for c in calls if c[0] == "task"]
    assert any(a.endswith(":observability:converged") for t in tasks for a in t), tasks
    assert not any(a.endswith(":secrets-manager:seed-observability") for t in tasks for a in t), tasks


@pytest.mark.parametrize("provider", PROVIDERS)
def test_install_starts_background_seed_when_not_converged(tmp_path, provider):
    res, calls = _run(tmp_path, provider, "install:phase1-observability-bg", _state(converged=False))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "running in background" in res.stdout, res.stdout
    for _ in range(20):
        tasks = [c[1:] for c in calls if c[0] == "task"]
        if any(a == f"{provider}:secrets-manager:seed-observability" for t in tasks for a in t):
            break
        time.sleep(0.25)
        calls = [json.loads(l) for l in (tmp_path / "calls.jsonl").read_text().splitlines() if l]
    assert any(a == f"{provider}:secrets-manager:seed-observability" for t in tasks for a in t), tasks


@pytest.mark.parametrize("provider", PROVIDERS)
def test_seed_records_token_expiry_with_the_same_ttl(provider):
    cmd = "\n".join(c if isinstance(c, str) else c.get("cmd", "")
                    for c in _task(provider, "secrets-manager:seed-observability")["cmds"])
    assert 'AMG_API_KEY_EXPIRES_AT=$(( $(date +%s) + AMG_KEY_TTL ))' in cmd
    assert '--seconds-to-live "$AMG_KEY_TTL"' in cmd
    assert '--arg grafana_api_key_expires_at "$AMG_API_KEY_EXPIRES_AT"' in cmd
    assert "grafana_api_key_expires_at: $grafana_api_key_expires_at" in cmd
