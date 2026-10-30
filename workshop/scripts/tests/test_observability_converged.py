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
elif svc == "secretsmanager" and op in ("create-secret", "put-secret-value"):
    sid = opts.get("secret-id") or opts.get("name")
    if op == "create-secret" and sid in st["secrets"]:
        sys.stderr.write("ResourceExistsException\n"); sys.exit(254)
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(["put", sid, opts["secret-string"]]) + "\n")
elif svc == "secretsmanager" and op == "restore-secret":
    sys.exit(254)
elif svc == "grafana" and op == "list-workspaces":
    if st["amg_ws"] is None:
        sys.stderr.write("ThrottlingException\n"); sys.exit(254)
    print(st["amg_ws"] or "")
elif svc == "grafana" and op == "describe-workspace":
    if "endpoint" in opts.get("query", ""):
        print(st["amg_endpoint"])
    else:
        tag = st["amg_tag"]
        tag = tag.get(opts["workspace-id"]) if isinstance(tag, dict) else tag
        if tag is None:
            sys.stderr.write("AccessDeniedException\n"); sys.exit(254)
        print(tag)
elif svc == "amp" and op == "list-workspaces":
    print("\t".join(st["amp_tags"].keys()))
elif svc == "amp" and op == "list-tags-for-resource":
    tag = st["amp_tags"].get(opts["resource-arn"].rsplit("/", 1)[-1])
    if tag is None:
        sys.stderr.write("AccessDeniedException\n"); sys.exit(254)
    print(tag)
elif svc == "eks" and op == "list-clusters":
    print("\t".join(st.get("eks", {}).keys()))
elif svc == "eks" and op == "describe-cluster" and "tags" in opts.get("query", ""):
    # st["eks_tags"]: cluster name -> [prefix tag, environment tag]; absent = no tags.
    t = st.get("eks_tags", {}).get(opts["name"])
    if t is None:
        sys.stderr.write("ResourceNotFoundException\n"); sys.exit(254)
    print("\t".join(t))
elif svc == "eks" and op == "describe-cluster":
    # st["eks"]: cluster name -> status ("ACTIVE", "CREATING", ...) or "error"; absent = not found.
    v = st.get("eks", {}).get(opts["name"])
    if v is None:
        sys.stderr.write("ResourceNotFoundException\n"); sys.exit(254)
    if v == "error":
        sys.stderr.write("ThrottlingException\n"); sys.exit(254)
    print(v)
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
          "amg_tag": f"{PREFIX}-amg", "amg_endpoint": AMG_HOST, "amp_tags": {},
          "sa_tokens": {}, "converged": True}
    st.update(kw)
    st["secrets"] = {k: (json.dumps(v) if isinstance(v, dict) else v)
                     for k, v in st["secrets"].items() if v is not None}
    return st


def _task(provider, name):
    with open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")) as f:
        return yaml.safe_load(f)["tasks"][name]


def _run(tmp_path, provider, name, state, env_extra=None, tvars_extra=None, task_vars=True):
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
                 AWS_REGION=REGION, AWS_ACCOUNT_ID=ACCOUNT, **(tvars_extra or {}))
    task = {"cmds": t["cmds"]}
    if "vars" in t and task_vars:
        task["vars"] = t["vars"]
    # The spoke-name resolver is called as $ROOT_DIR/scripts/resolve-spoke-cluster.sh.
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(os.path.join(REPO, "scripts", "resolve-spoke-cluster.sh"), tmp_path / "scripts")
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


# ── Review of #1168: stale URL, converge under errexit, keys kept through the hub re-seed ──

@pytest.mark.parametrize("provider", PROVIDERS)
def test_stale_grafana_url_is_not_converged(tmp_path, provider):
    # The AMG workspace was replaced: the stored host is dead (curl inconclusive) and the
    # tag-matched ACTIVE workspace has another endpoint -> not converged, so install re-seeds.
    res, calls = _converged(tmp_path, provider, curl="fail",
                            amg_endpoint="g-new.grafana-workspace.us-west-2.amazonaws.com")
    assert res.returncode != 0, res.stdout
    assert f"observability stale: aws_grafana_url ({AMG_HOST})" in res.stdout, res.stdout
    assert not [c for c in calls if c[0] == "curl"]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", ["list-fails", "no-active-match", "describe-fails"])
def test_stale_check_is_inconclusive_without_a_positive_mismatch(tmp_path, provider, case):
    kw = {"list-fails": {"amg_ws": None}, "no-active-match": {"amg_ws": ""},
          "describe-fails": {"amg_tag": {}}}[case]
    res, _ = _converged(tmp_path, provider, curl="fail", **kw)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "AMG check inconclusive" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("last", ["non-matching", "lookup-fails"])
def test_converge_survives_a_non_matching_last_workspace(tmp_path, provider, last):
    # errexit: `[ ... ] && OK=true` as the loop body's last statement made the task exit 1
    # when the LAST ACTIVE workspace listed did not match (or its tag lookup failed).
    amp = {"w1": f"{PREFIX}-amp"}
    amg = {"g1": f"{PREFIX}-amg"}
    if last == "non-matching":
        amp["w2"], amg["g2"] = "other-amp", "other-amg"
    else:
        amp["w2"] = None
    # lookup-fails: w2 is listed but its tag lookup errors; g2 is listed but describe errors.
    st = _state(converged=False, amp_tags=amp, amg_ws="g1\tg2", amg_tag=amg)
    res, _ = _run(tmp_path, provider, "observability:converge", st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "AMP and AMG are ACTIVE: seeding observability inline" in res.stdout, res.stdout


OBS_KEYS = {"aws_grafana_url": AMG_HOST,
            "spoke_dev_cluster_arn": "arn:aws:eks:us-west-2:111122223333:cluster/acme-spoke-dev",
            "spoke_dev_private_subnet_ids": "subnet-a,subnet-b", "spoke_dev_security_group_id": "sg-d",
            "spoke_prod_cluster_arn": "arn:aws:eks:us-west-2:111122223333:cluster/acme-spoke-prod",
            "spoke_prod_private_subnet_ids": "subnet-c,subnet-d", "spoke_prod_security_group_id": "sg-p"}


def _hub_seed(tmp_path, provider, existing_meta):
    (tmp_path / "private").mkdir(exist_ok=True)
    (tmp_path / "private" / "git-domain").write_text("git.example.com\n")
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text("domain: example.com\n")
    st = _state()
    st["secrets"][f"{HUB}/config"] = (json.dumps({"metadata": json.dumps(existing_meta)})
                                      if existing_meta is not None else None)
    st["secrets"] = {k: v for k, v in st["secrets"].items() if v is not None}
    res, calls = _run(tmp_path, provider, "secrets-manager:seed", st, task_vars=False, tvars_extra={
        "CONFIG_FILE": str(cfg), "INGRESS_DOMAIN": "example.com", "ARGOCD_URL": "argo.example.com",
        "CLUSTER_ARN": "arn:hub", "VPC_ID": "vpc-1", "PRIVATE_SUBNET_IDS": "subnet-1,subnet-2",
        "SUBNET_IDS": "subnet-1,subnet-2", "CLUSTER_SG": "sg-1"})
    assert res.returncode == 0, res.stdout + res.stderr
    puts = [c for c in calls if c[0] == "put" and c[1] == f"{HUB}/config"]
    assert len(puts) == 1, calls
    return json.loads(json.loads(puts[0][2])["metadata"])


@pytest.mark.parametrize("provider", PROVIDERS)
def test_hub_reseed_keeps_grafana_url_and_spoke_scraper_keys(tmp_path, provider):
    meta = _hub_seed(tmp_path, provider, dict(OBS_KEYS, aws_argocd_url="argo.example.com"))
    for k, v in OBS_KEYS.items():
        assert meta.get(k) == v, (k, meta)
    # ...so the gate passes on the re-seeded secret and install skips the re-seed.
    st = _state()
    st["secrets"][f"{HUB}/config"] = json.dumps({"metadata": json.dumps(meta)})
    res, _ = _run(_fresh(tmp_path), provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.parametrize("provider", PROVIDERS)
def test_hub_seed_adds_no_observability_keys_when_none_were_seeded(tmp_path, provider):
    for existing in (None, {"aws_grafana_url": "", "spoke_dev_cluster_arn": ""}):
        meta = _hub_seed(_fresh(tmp_path), provider, existing)
        assert not set(OBS_KEYS) & set(meta), meta


# ── spoke_* scraper keys: a spoke created after the first seed must not stay unwired ──

SPOKE_KEYS = {k: v for k, v in OBS_KEYS.items() if k.startswith("spoke_")}


def _with_meta(meta, **kw):
    st = _state(**kw)
    st["secrets"][f"{HUB}/config"] = json.dumps({"metadata": json.dumps(dict(meta, aws_grafana_url=AMG_HOST))})
    return st


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("env", ["dev", "prod"])
def test_active_spoke_without_scraper_keys_is_not_converged(tmp_path, provider, env):
    # First seed ran before the spoke existed: no spoke_<env>_* keys. The spoke is ACTIVE now,
    # so the gate must fail and install re-seeds (which writes the keys).
    meta = {k: v for k, v in SPOKE_KEYS.items() if not k.startswith(f"spoke_{env}_")}
    st = _with_meta(meta, eks={f"{PREFIX}-spoke-dev": "ACTIVE", f"{PREFIX}-spoke-prod": "ACTIVE"})
    res, calls = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout
    assert "observability spoke keys missing (spoke cluster ACTIVE)" in res.stdout, res.stdout
    for k in ("cluster_arn", "private_subnet_ids", "security_group_id"):
        assert f"spoke_{env}_{k}" in res.stdout, res.stdout
    other = "prod" if env == "dev" else "dev"
    assert f"spoke_{other}_" not in res.stdout, res.stdout
    assert not [c for c in calls if c[0] == "curl"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_empty_scraper_keys_from_a_partial_first_seed_are_missing(tmp_path, provider):
    # The seed writes "" for a spoke it did not find when the other one existed.
    meta = dict(SPOKE_KEYS, spoke_prod_cluster_arn="", spoke_prod_private_subnet_ids="",
                spoke_prod_security_group_id="")
    st = _with_meta(meta, eks={f"{PREFIX}-spoke-dev": "ACTIVE", f"{PREFIX}-spoke-prod": "ACTIVE"})
    res, _ = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout
    assert "spoke_prod_cluster_arn" in res.stdout and "spoke_dev_" not in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
def test_active_spokes_with_scraper_keys_are_converged(tmp_path, provider):
    st = _with_meta(SPOKE_KEYS, eks={f"{PREFIX}-spoke-dev": "ACTIVE", f"{PREFIX}-spoke-prod": "ACTIVE"})
    res, _ = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "token accepted by AMG" in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", ["not-found", "creating", "api-error"])
def test_spoke_check_skips_unless_the_spoke_is_active(tmp_path, provider, case):
    # No spoke_* keys at all. A spoke that does not exist (yet), is not ACTIVE, or whose
    # describe-cluster errors must NOT fail the gate: an error never triggers a re-seed
    # (each re-seed mints a new AMG service account).
    eks = {"not-found": {}, "creating": {f"{PREFIX}-spoke-dev": "CREATING"},
           "api-error": {f"{PREFIX}-spoke-dev": "error", f"{PREFIX}-spoke-prod": "error"}}[case]
    st = _with_meta({}, eks=eks)
    res, calls = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "spoke keys missing" not in res.stdout, res.stdout
    eks_calls = [c for c in calls if c[1:3] == ["eks", "describe-cluster"]]
    assert sorted({c[3]["name"] for c in eks_calls}) == [f"{PREFIX}-spoke-dev", f"{PREFIX}-spoke-prod"], eks_calls


@pytest.mark.parametrize("provider", PROVIDERS)
def test_hub_reseed_then_late_spoke_is_detected(tmp_path, provider):
    # Chain: first seed wired only the dev spoke, hub:seed re-ran (keys kept), then prod came up.
    meta = _hub_seed(tmp_path, provider, {"aws_grafana_url": AMG_HOST,
                                          "spoke_dev_cluster_arn": SPOKE_KEYS["spoke_dev_cluster_arn"],
                                          "spoke_dev_private_subnet_ids": "subnet-a,subnet-b",
                                          "spoke_dev_security_group_id": "sg-d",
                                          "spoke_prod_cluster_arn": "", "spoke_prod_private_subnet_ids": "",
                                          "spoke_prod_security_group_id": ""})
    st = _state(eks={f"{PREFIX}-spoke-dev": "ACTIVE"})
    st["secrets"][f"{HUB}/config"] = json.dumps({"metadata": json.dumps(meta)})
    res, _ = _run(_fresh(tmp_path), provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr   # prod not there yet: skip still fires
    st["eks"][f"{PREFIX}-spoke-prod"] = "ACTIVE"
    res, _ = _run(_fresh(tmp_path), provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout                 # prod ACTIVE, unwired: re-seed
    assert "spoke_prod_cluster_arn" in res.stdout, res.stdout


# ── spokes with non-workshop names (found by tags) ──
@pytest.mark.parametrize("provider", PROVIDERS)
def test_hub_reseed_keeps_spoke_cluster_name_keys(tmp_path, provider):
    names = {"spoke_dev_cluster_name": f"{PREFIX}-dev", "spoke_prod_cluster_name": "custom-prod"}
    meta = _hub_seed(tmp_path, provider, dict(OBS_KEYS, **names))
    for k, v in names.items():
        assert meta.get(k) == v, (k, meta)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_tag_discovered_spoke_without_keys_is_not_converged(tmp_path, provider):
    # peeks-a style: spoke <prefix>-dev, no workshop-named cluster, no spoke_* keys yet.
    st = _with_meta({}, eks={f"{PREFIX}-dev": "ACTIVE"}, eks_tags={f"{PREFIX}-dev": [PREFIX, "dev"]})
    res, _ = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode != 0, res.stdout
    assert "spoke_dev_cluster_name" in res.stdout and "spoke_dev_cluster_arn" in res.stdout, res.stdout
    assert "spoke_prod_" not in res.stdout, res.stdout


@pytest.mark.parametrize("provider", PROVIDERS)
def test_tag_discovered_spoke_with_keys_is_converged(tmp_path, provider):
    meta = {k: v for k, v in SPOKE_KEYS.items() if k.startswith("spoke_dev_")}
    meta["spoke_dev_cluster_name"] = f"{PREFIX}-dev"
    st = _with_meta(meta, eks={f"{PREFIX}-dev": "ACTIVE"}, eks_tags={f"{PREFIX}-dev": [PREFIX, "dev"]})
    res, _ = _run(tmp_path, provider, "observability:converged", st)
    assert res.returncode == 0, res.stdout + res.stderr
