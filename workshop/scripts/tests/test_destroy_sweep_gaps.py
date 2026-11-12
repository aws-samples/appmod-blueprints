"""Three resource classes a real kind-kro-ack `task destroy` (DESTROY_KEEP_DATA=false,
two stacks of one account) left behind, now swept:

1. The CloudWatch Logs capability-log objects of the SPOKES (delivery source
   <spoke>-kro, destination <spoke>-kro-cwl and the delivery between them). Step 2/2b
   only took the hub's: the source name had to contain the hub name.
2. The Ray model bucket <prefix>-ray-models-<account> (ray:setup creates it with the
   AWS CLI; nothing deleted it).
3. The Ray ECR repo <prefix>-ray-vllm-custom (ray:setup creates it; step 5 skips it,
   it is not ACK-tagged).

Unit tests on scripts/sweep_lib.py with fakes, then the destroy steps themselves read
verbatim from both providers' Taskfiles and run under go-task (bash with
`set -euo pipefail` when go-task is not on PATH) with a fake `aws` and a fake boto3:
exit code and the AWS calls made are asserted. No AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_sweep_gaps.py -q
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

yaml = pytest.importorskip("yaml")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import sweep_lib as sl  # noqa: E402

KRO_ACK = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
CROSSPLANE = os.path.join(REPO, "cluster-providers", "kind-crossplane", "Taskfile.yaml")
TASK = shutil.which("task")
ACCT, REGION, PREFIX = "111122223333", "us-west-2", "hb"
HUB = f"{PREFIX}-hub"


def cap_arn(cluster, cap="kro"):
    return f"arn:aws:eks:{REGION}:{ACCT}:capability/{cluster}/{cap}/abc123"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(REPO, "scripts", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AwsError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(f"An error occurred ({code}) when calling the op")


# ------------------------------------------------------------ 1. log deliveries

class FakeLogs:
    """sources: name -> resource ARN; deliveries: (id, source, destination name)."""

    def __init__(self, sources, dests, deliveries=(), gone_on_delete=()):
        self.sources, self.dests = dict(sources), list(dests)
        self.deliveries = list(deliveries)
        self.gone_on_delete = set(gone_on_delete)
        self.calls = []

    def describe_delivery_sources(self, **_):
        return {"deliverySources": [{"name": n, "resourceArns": [a]} for n, a in self.sources.items()]}

    def describe_deliveries(self, **_):
        return {"deliveries": [{"id": i, "deliverySourceName": s, "deliveryDestinationArn": f"arn:dest/{d}"}
                               for i, s, d in self.deliveries]}

    def describe_delivery_destinations(self, **_):
        return {"deliveryDestinations": [{"name": d, "arn": f"arn:dest/{d}"} for d in self.dests]}

    def _del(self, kind, ident):
        self.calls.append((kind, ident))
        if ident in self.gone_on_delete:
            raise AwsError("ResourceNotFoundException")

    def delete_delivery(self, id):
        self._del("delivery", id)

    def delete_delivery_source(self, name):
        self._del("source", name)

    def delete_delivery_destination(self, name):
        self._del("dest", name)


def stack_logs():
    return FakeLogs(
        {f"{HUB}-kro": cap_arn(HUB), f"{PREFIX}-dev-kro": cap_arn(f"{PREFIX}-dev"),
         f"{PREFIX}-prod-kro": cap_arn(f"{PREFIX}-prod"),          # retained spoke
         "ha-dev-kro": cap_arn("ha-dev"),                           # another stack
         f"{PREFIX}-a-dev-kro": cap_arn(f"{PREFIX}-a-dev")},        # longer prefix: not ours
        [f"{HUB}-kro-cwl", f"{PREFIX}-dev-kro-cwl", f"{PREFIX}-prod-kro-cwl", "ha-dev-kro-cwl",
         f"{PREFIX}-a-dev-kro-cwl"],
        deliveries=[("d-hub", f"{HUB}-kro", f"{HUB}-kro-cwl"),
                    ("d-dev", f"{PREFIX}-dev-kro", f"{PREFIX}-dev-kro-cwl"),
                    ("d-prod", f"{PREFIX}-prod-kro", f"{PREFIX}-prod-kro-cwl"),
                    ("d-ha", "ha-dev-kro", "ha-dev-kro-cwl")])


INVENTORY = {"clusters": [{"name": f"{PREFIX}-dev", "deletionPolicy": "delete"},
                          {"name": f"{PREFIX}-prod", "deletionPolicy": "retain"}]}


def test_spoke_and_hub_deliveries_are_deleted_in_order():
    logs = stack_logs()
    ids, srcs, dsts, n = sl.sweep_log_deliveries(logs, {HUB, f"{PREFIX}-dev"})
    assert logs.calls == [("delivery", "d-hub"), ("delivery", "d-dev"),
                          ("source", f"{HUB}-kro"), ("source", f"{PREFIX}-dev-kro"),
                          ("dest", f"{HUB}-kro-cwl"), ("dest", f"{PREFIX}-dev-kro-cwl")]
    assert n == 6


def test_hub_leftovers_take_the_inventory_spoke_and_nothing_else():
    """The real gap: sweep-hub-leftovers (step 2b) left <spoke>-kro and -cwl."""
    from test_destroy_teardown_leftovers import FakeEc2, FakeElbv2  # noqa: E402
    logs = stack_logs()
    r = sl.sweep_hub_leftovers(FakeEc2({}), FakeElbv2({}), logs, PREFIX, HUB,
                               {"ha-dev": {"status": "ACTIVE", "vpc": ""}}, INVENTORY)
    touched = {i for _, i in logs.calls}
    assert {f"{PREFIX}-dev-kro", f"{PREFIX}-dev-kro-cwl", "d-dev", f"{HUB}-kro"} <= touched
    assert not touched & {f"{PREFIX}-prod-kro", f"{PREFIX}-prod-kro-cwl", "d-prod", "ha-dev-kro",
                          "ha-dev-kro-cwl", "d-ha", f"{PREFIX}-a-dev-kro", f"{PREFIX}-a-dev-kro-cwl"}
    assert r["deliveries"] == ["d-hub", "d-dev"] and r["deleted"] == 6


def test_live_spoke_keeps_its_deliveries():
    from test_destroy_teardown_leftovers import FakeEc2, FakeElbv2  # noqa: E402
    logs = stack_logs()
    sl.sweep_hub_leftovers(FakeEc2({}), FakeElbv2({}), logs, PREFIX, HUB,
                           {f"{PREFIX}-dev": {"status": "ACTIVE", "vpc": ""}}, INVENTORY)
    assert not {i for _, i in logs.calls} & {f"{PREFIX}-dev-kro", "d-dev", f"{PREFIX}-dev-kro-cwl"}


def test_source_with_another_name_is_taken_by_its_capability_arn():
    logs = FakeLogs({f"{PREFIX}-dev-logs-kro": cap_arn(f"{PREFIX}-dev"),
                     f"{PREFIX}-x-kro": cap_arn("ha-dev")}, [])
    _, srcs, _ = sl.select_log_deliveries(logs, {f"{PREFIX}-dev"})
    assert srcs == [f"{PREFIX}-dev-logs-kro"]


def test_destination_another_delivery_still_uses_is_kept():
    logs = FakeLogs({f"{PREFIX}-dev-kro": cap_arn(f"{PREFIX}-dev"), "other-src": "arn:x"},
                    [f"{PREFIX}-dev-kro-cwl"],
                    deliveries=[("d1", f"{PREFIX}-dev-kro", f"{PREFIX}-dev-kro-cwl"),
                                ("d2", "other-src", f"{PREFIX}-dev-kro-cwl")])
    ids, srcs, dsts = sl.select_log_deliveries(logs, {f"{PREFIX}-dev"})
    assert ids == ["d1"] and srcs == [f"{PREFIX}-dev-kro"] and dsts == []


def test_not_found_is_done_and_dry_run_deletes_nothing(capsys):
    logs = stack_logs()
    logs.gone_on_delete = {"d-dev", f"{PREFIX}-dev-kro"}
    *_, n = sl.sweep_log_deliveries(logs, {f"{PREFIX}-dev"})
    out = capsys.readouterr().out
    assert n == 1 and "⚠" not in out and "already gone" in out
    logs = stack_logs()
    *_, n = sl.sweep_log_deliveries(logs, {HUB}, dry_run=True)
    assert logs.calls == [] and n == 0


def test_no_gone_cluster_selects_nothing():
    assert sl.select_log_deliveries(stack_logs(), set()) == ([], [], [])


def test_capability_arn_cluster():
    assert sl.capability_arn_cluster(cap_arn("c1", "ack")) == "c1"
    assert sl.capability_arn_cluster(f"arn:aws:eks:{REGION}:{ACCT}:cluster/c1") == ""
    assert sl.capability_arn_cluster("") == ""


def test_log_deliveries_cli_never_fails(capsys):
    mod = load("sweep-log-deliveries.py")

    class Eks:
        def list_clusters(self, **_):
            return {"clusters": []}

    class Broken(Eks):
        def list_clusters(self, **_):
            raise AwsError("AccessDeniedException")
    logs = stack_logs()
    assert mod.main([PREFIX, REGION, HUB], eks=Broken(), logs=logs) == 0
    assert "AccessDeniedException" in capsys.readouterr().out and logs.calls == []
    # No inventory: the hub and the <prefix>-spoke-dev/-prod spokes.
    logs = FakeLogs({f"{HUB}-kro": cap_arn(HUB), f"{PREFIX}-spoke-dev-ack": cap_arn(f"{PREFIX}-spoke-dev", "ack"),
                     f"{PREFIX}-dev-kro": cap_arn(f"{PREFIX}-dev")}, [])
    assert mod.main([PREFIX, REGION, HUB], eks=Eks(), logs=logs) == 0
    assert logs.calls == [("source", f"{HUB}-kro"), ("source", f"{PREFIX}-spoke-dev-ack")]


# -------------------------------------------------------- 2 + 3. Ray bucket, repos

class FakeS3:
    def __init__(self, buckets, region=REGION, versions=2500, head_error=None, fail=()):
        self.buckets, self.region = set(buckets), region
        self.objects = [{"Key": f"models/m/{i}", "VersionId": f"v{i}"} for i in range(versions)]
        self.markers = [{"Key": "models/m/0", "VersionId": "dm0"}]
        self.head_error, self.fail = head_error, set(fail)
        self.calls = []

    def head_bucket(self, Bucket):
        self.calls.append(("head_bucket", Bucket))
        if self.head_error:
            raise AwsError(self.head_error)
        if Bucket not in self.buckets:
            raise AwsError("404")

    def get_bucket_location(self, Bucket):
        return {"LocationConstraint": None if self.region == "us-east-1" else self.region}

    def list_object_versions(self, Bucket, KeyMarker=None, VersionIdMarker=None):
        start = int(KeyMarker or 0)
        page = self.objects[start:start + 1000]
        resp = {"Versions": page, "IsTruncated": start + 1000 < len(self.objects)}
        if start == 0:
            resp["DeleteMarkers"] = self.markers
        if resp["IsTruncated"]:
            resp.update(NextKeyMarker=str(start + 1000), NextVersionIdMarker="x")
        return resp

    def delete_objects(self, Bucket, Delete):
        assert len(Delete["Objects"]) <= 1000
        self.calls.append(("delete_objects", len(Delete["Objects"])))
        return {}

    def delete_bucket(self, Bucket):
        self.calls.append(("delete_bucket", Bucket))
        if "delete_bucket" in self.fail:
            raise AwsError("BucketNotEmpty")
        self.buckets.discard(Bucket)


class FakeEcr:
    def __init__(self, repos):
        self.repos = set(repos)
        self.calls = []

    def describe_repositories(self, repositoryNames):
        if repositoryNames[0] not in self.repos:
            raise AwsError("RepositoryNotFoundException")
        return {"repositories": [{"repositoryName": repositoryNames[0]}]}

    def delete_repository(self, repositoryName, force):
        self.calls.append(("delete_repository", repositoryName, force))
        self.repos.discard(repositoryName)


BUCKET = f"{PREFIX}-ray-models-{ACCT}"
VLLM, NEURON = f"{PREFIX}-ray-vllm-custom", f"{PREFIX}-ray-neuron-custom"


def test_ray_bucket_is_emptied_all_versions_then_deleted_and_repos_force_deleted():
    s3, ecr = FakeS3({BUCKET, "user-bucket"}), FakeEcr({VLLM, f"{PREFIX}-myapp"})
    n, failed = sl.sweep_ray_resources(s3, ecr, PREFIX, ACCT, REGION)
    deleted = sum(c[1] for c in s3.calls if c[0] == "delete_objects")
    assert deleted == 2501, "every version and delete marker"
    assert s3.calls[-1] == ("delete_bucket", BUCKET) and s3.buckets == {"user-bucket"}
    assert ecr.calls == [("delete_repository", VLLM, True)], "exact names only, not <prefix>-*"
    assert (n, failed) == (2, [])


def test_ray_resources_already_gone_are_done():
    s3, ecr = FakeS3(set()), FakeEcr(set())
    assert sl.sweep_ray_resources(s3, ecr, PREFIX, ACCT, REGION) == (0, [])
    assert ecr.calls == [] and not [c for c in s3.calls if c[0] != "head_bucket"]


def test_keep_data_keeps_bucket_and_repos(capsys):
    s3, ecr = FakeS3({BUCKET}), FakeEcr({VLLM, NEURON})
    assert sl.sweep_ray_resources(s3, ecr, PREFIX, ACCT, REGION, keep_data=True) == (0, [])
    assert s3.calls == [] and ecr.calls == []
    assert "DESTROY_KEEP_DATA=true" in capsys.readouterr().out


def test_bucket_in_another_region_is_kept():
    s3 = FakeS3({BUCKET}, region="eu-west-3")
    sl.sweep_ray_resources(s3, FakeEcr(set()), PREFIX, ACCT, REGION)
    assert not [c for c in s3.calls if c[0] in ("delete_objects", "delete_bucket")]
    # HeadBucket from the wrong region endpoint answers 301: kept, not a failure.
    s3 = FakeS3({BUCKET}, head_error="301")
    assert sl.sweep_ray_resources(s3, FakeEcr(set()), PREFIX, ACCT, REGION) == (0, [])


def test_dry_run_deletes_nothing():
    s3, ecr = FakeS3({BUCKET}), FakeEcr({VLLM, NEURON})
    n, _ = sl.sweep_ray_resources(s3, ecr, PREFIX, ACCT, REGION, dry_run=True)
    assert n == 3 and ecr.calls == [] and [c[0] for c in s3.calls] == ["head_bucket"]


def test_read_and_delete_errors_are_failures_with_the_code_only(capsys):
    n, failed = sl.sweep_ray_resources(FakeS3({BUCKET}, head_error="403"), FakeEcr(set()), PREFIX, ACCT, REGION)
    assert failed == [f"s3:{BUCKET}"]
    n, failed = sl.sweep_ray_resources(FakeS3({BUCKET}, fail={"delete_bucket"}), FakeEcr(set()),
                                       PREFIX, ACCT, REGION)
    assert failed == [f"s3:{BUCKET}"] and "(BucketNotEmpty)" in capsys.readouterr().out


def test_no_account_sweeps_nothing():
    s3 = FakeS3({BUCKET})
    assert sl.sweep_ray_resources(s3, FakeEcr({VLLM}), PREFIX, "", REGION) == (0, [])
    assert s3.calls == []


def test_ray_cli_skips_while_the_hub_is_live_and_records_failures(tmp_path, capsys, monkeypatch):
    mod = load("sweep-ray-resources.py")
    failures = tmp_path / "failures"
    monkeypatch.setenv("SWEEP_FAILURES_FILE", str(failures))

    class Eks:
        def __init__(self, live):
            self.live = live

        def list_clusters(self, **_):
            return {"clusters": self.live}

        def describe_cluster(self, name):
            return {"cluster": {"status": "ACTIVE"}}
    s3, ecr = FakeS3({BUCKET}), FakeEcr({VLLM})
    assert mod.main([PREFIX, REGION, HUB, ACCT], eks=Eks([HUB]), s3=s3, ecr=ecr) == 0
    assert "skip Ray resources" in capsys.readouterr().out and s3.calls == [] and ecr.calls == []
    assert mod.main([PREFIX, REGION, HUB, ACCT], eks=Eks([]), s3=FakeS3({BUCKET}, head_error="403"),
                    ecr=FakeEcr(set())) == 0
    assert failures.read_text() == f"sweep-ray-resources(s3:{BUCKET})\n"
    assert ACCT not in capsys.readouterr().out.replace(BUCKET, "")


# ----------------------------------------------- the Taskfile steps, stub-executed

FAKE_BOTO3 = r'''
import json, os
_FX = json.load(open(os.environ["FAKE_FX"]))
class ClientError(Exception):
    def __init__(self, code, op):
        self.response = {"Error": {"Code": code}}
        super().__init__("An error occurred (%s) when calling the %s operation" % (code, op))
class _Client:
    def __init__(self, svc):
        self._svc = svc
    def __getattr__(self, op):
        def call(**kw):
            with open(os.environ["FAKE_LOG"], "a") as f:
                f.write(json.dumps([self._svc, op, kw]) + "\n")
            s, fx = self._svc, _FX
            if (s, op) == ("eks", "list_clusters"):
                return {"clusters": fx.get("live", [])}
            if (s, op) == ("eks", "describe_cluster"):
                return {"cluster": {"status": "ACTIVE"}}
            if (s, op) == ("logs", "describe_delivery_sources"):
                return {"deliverySources": [{"name": n, "resourceArns": [a]} for n, a in fx["sources"].items()]}
            if (s, op) == ("logs", "describe_deliveries"):
                return {"deliveries": [{"id": i, "deliverySourceName": src, "deliveryDestinationArn": "arn:dest/" + d}
                                       for i, src, d in fx["deliveries"]]}
            if (s, op) == ("logs", "describe_delivery_destinations"):
                return {"deliveryDestinations": [{"name": d, "arn": "arn:dest/" + d} for d in fx["dests"]]}
            if (s, op) == ("s3", "head_bucket"):
                if kw["Bucket"] not in fx["buckets"]:
                    raise ClientError("404", "HeadBucket")
                return {}
            if (s, op) == ("s3", "get_bucket_location"):
                return {"LocationConstraint": fx["region"]}
            if (s, op) == ("s3", "list_object_versions"):
                return {"Versions": [{"Key": "models/m/a", "VersionId": "v1"}], "IsTruncated": False}
            if (s, op) == ("ecr", "describe_repositories"):
                if kw["repositoryNames"][0] not in fx["repos"]:
                    raise ClientError("RepositoryNotFoundException", "DescribeRepositories")
                return {}
            if op.startswith(("describe_", "list_", "get_")):
                return {}
            return {}
        return call
def client(svc, **kw):
    return _Client(svc)
class Session:
    def __init__(self, **kw):
        pass
    def get_credentials(self):
        return object()
    def client(self, svc, **kw):
        return _Client(svc)
'''

FX = {
    "region": REGION,
    "sources": {f"{HUB}-kro": cap_arn(HUB), f"{PREFIX}-spoke-dev-kro": cap_arn(f"{PREFIX}-spoke-dev"),
                f"{PREFIX}-dev-kro": cap_arn(f"{PREFIX}-dev"), "ha-dev-kro": cap_arn("ha-dev")},
    "dests": [f"{HUB}-kro-cwl", f"{PREFIX}-spoke-dev-kro-cwl", f"{PREFIX}-dev-kro-cwl", "ha-dev-kro-cwl"],
    "deliveries": [["d-hub", f"{HUB}-kro", f"{HUB}-kro-cwl"],
                   ["d-sdev", f"{PREFIX}-spoke-dev-kro", f"{PREFIX}-spoke-dev-kro-cwl"],
                   ["d-dev", f"{PREFIX}-dev-kro", f"{PREFIX}-dev-kro-cwl"],
                   ["d-ha", "ha-dev-kro", "ha-dev-kro-cwl"]],
    "buckets": [BUCKET], "repos": [VLLM, NEURON],
}


def _step(taskfile, marker):
    with open(taskfile) as f:
        cmds = yaml.safe_load(f)["tasks"]["destroy"]["cmds"]
    return next(c["cmd"] for c in cmds if isinstance(c, dict) and marker in c.get("cmd", ""))


def _run(tmp_path, cmd, keep_data="false", fx=None, inventory=None):
    bindir, pylib = tmp_path / "bin", tmp_path / "pylib" / "boto3"
    bindir.mkdir()
    pylib.mkdir(parents=True)
    (pylib / "__init__.py").write_text(FAKE_BOTO3)
    # Fake aws CLI: logs the call, answers every list/describe with nothing.
    (bindir / "aws").write_text('#!/bin/sh\necho "aws $*" >> "$FAKE_CLI_LOG"\nexit 0\n')
    (bindir / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    for b in ("aws", "python3"):
        (bindir / b).chmod(0o755)
    priv = tmp_path / "private"
    priv.mkdir()
    (priv / "destroy-inventory.json").write_text(json.dumps(inventory or {"clusters": []}))
    fxf, log, cli = tmp_path / "fx.json", tmp_path / "boto.jsonl", tmp_path / "cli.log"
    fxf.write_text(json.dumps(fx or FX))
    log.write_text("")
    cli.write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", PYTHONPATH=str(tmp_path / "pylib"),
               FAKE_FX=str(fxf), FAKE_LOG=str(log), FAKE_CLI_LOG=str(cli),
               SWEEP_FAILURES_FILE=str(priv / "destroy-sweep-failures"))
    cmd = cmd.replace("{{.ROOT_DIR}}/private/", str(priv) + "/").replace("{{.ROOT_DIR}}", REPO)
    tvars = {"AWS_REGION": REGION, "RESOURCE_PREFIX": PREFIX, "HUB_CLUSTER_NAME": HUB, "AWS_ACCOUNT_ID": ACCT,
             "DESTROY_KEEP_DATA": keep_data, "DOMAIN": ""}
    if TASK:
        tf = tmp_path / "Taskfile.yml"
        tf.write_text(yaml.safe_dump({"version": "3", "set": ["errexit", "nounset", "pipefail"], "vars": tvars,
                                      "tasks": {"run": {"cmds": [{"cmd": cmd}]}}}, sort_keys=False))
        res = subprocess.run([TASK, "-s", "-t", str(tf), "run"], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    else:
        for k, v in tvars.items():
            cmd = cmd.replace("{{.%s}}" % k, v)
        res = subprocess.run(["bash", "-c", "set -euo pipefail\n" + cmd], cwd=tmp_path, env=env,
                             capture_output=True, text=True, timeout=120)
    calls = [json.loads(ln) for ln in log.read_text().splitlines()]
    return res, calls


def _deletes(calls):
    return [(s, op, next(iter(kw.values()), "")) for s, op, kw in calls
            if op.startswith("delete_") and op != "delete_objects"]


KRO_MARKER = "# 2d."
XP_MARKER = "sweep-ray-resources.py"


def test_kind_kro_ack_sweep_step_removes_spoke_deliveries_bucket_and_repos(tmp_path):
    inv = {"clusters": [{"name": f"{PREFIX}-dev", "deletionPolicy": "delete"}]}
    res, calls = _run(tmp_path, _step(KRO_ACK, KRO_MARKER), inventory=inv)
    assert res.returncode == 0, res.stdout + res.stderr
    d = _deletes(calls)
    for want in [("logs", "delete_delivery", "d-dev"), ("logs", "delete_delivery_source", f"{PREFIX}-dev-kro"),
                 ("logs", "delete_delivery_destination", f"{PREFIX}-dev-kro-cwl"),
                 ("logs", "delete_delivery_source", f"{HUB}-kro"),
                 ("logs", "delete_delivery_source", f"{PREFIX}-spoke-dev-kro"),
                 ("s3", "delete_bucket", BUCKET),
                 ("ecr", "delete_repository", VLLM), ("ecr", "delete_repository", NEURON)]:
        assert want in d, (want, d, res.stdout)
    assert not [x for x in d if "ha-dev" in str(x[2]) or x[2] == "d-ha"], "another stack's objects"
    i = d.index
    assert i(("logs", "delete_delivery", "d-dev")) < i(("logs", "delete_delivery_source", f"{PREFIX}-dev-kro")) \
        < i(("logs", "delete_delivery_destination", f"{PREFIX}-dev-kro-cwl"))
    assert not (tmp_path / "private" / "destroy-sweep-failures").exists()


def test_kind_kro_ack_sweep_step_keep_data_keeps_bucket_and_repos(tmp_path):
    res, calls = _run(tmp_path, _step(KRO_ACK, KRO_MARKER), keep_data="true")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [c for c in calls if c[0] in ("s3", "ecr")]
    assert ("logs", "delete_delivery_source", f"{HUB}-kro") in _deletes(calls)


def test_kind_kro_ack_sweep_step_keeps_everything_while_the_hub_is_live(tmp_path):
    res, calls = _run(tmp_path, _step(KRO_ACK, KRO_MARKER), fx=dict(FX, live=[HUB]))
    assert res.returncode == 0, res.stdout + res.stderr
    d = _deletes(calls)
    assert not [x for x in d if x[0] in ("s3", "ecr")] and ("logs", "delete_delivery_source", f"{HUB}-kro") not in d


def test_kind_crossplane_phase_6b_removes_the_same(tmp_path):
    res, calls = _run(tmp_path, _step(CROSSPLANE, XP_MARKER))
    assert res.returncode == 0, res.stdout + res.stderr
    d = _deletes(calls)
    for want in [("logs", "delete_delivery", "d-hub"), ("logs", "delete_delivery_source", f"{HUB}-kro"),
                 ("logs", "delete_delivery_source", f"{PREFIX}-spoke-dev-kro"),
                 ("s3", "delete_bucket", BUCKET), ("ecr", "delete_repository", VLLM)]:
        assert want in d, (want, d, res.stdout)
    assert ("logs", "delete_delivery_source", f"{PREFIX}-dev-kro") not in d, "not recorded: not this stack's"


def test_kind_crossplane_phase_6b_keep_data(tmp_path):
    res, calls = _run(tmp_path, _step(CROSSPLANE, XP_MARKER), keep_data="true")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not [c for c in calls if c[0] in ("s3", "ecr")]


def test_crossplane_destroy_declares_keep_data_default_false():
    t = yaml.safe_load(open(CROSSPLANE))["tasks"]["destroy"]["vars"]
    assert t["DESTROY_KEEP_DATA"] == '{{.DESTROY_KEEP_DATA | default "false"}}'
