"""Tests for the second real kind-kro-ack teardown with this branch (input from
that run), fixed in task kind-kro-ack:destroy:

1. The python sweep helpers use the SAME AWS profile as the aws CLI calls of the
   task. The aws CLI v2 reads AWS_PROFILE before AWS_DEFAULT_PROFILE, botocore
   the other way round; with both set to different values every helper got no
   credentials, failed closed and skipped the hub VPC, RDS, log group and IAM
   sweeps while destroy reported success.
2. A helper without credentials fails loudly: clear stderr message, exit 3,
   recorded in private/destroy-sweep-failures, and destroy's final check fails.
   protect-shared-iam keeps retaining everything (fail closed) in that case.
3. A preflight proves boto3 and the aws CLI resolve to the same account before
   anything is torn down.
4. EBS volumes of the EKS Auto Mode CSI driver (tag eks:eks-cluster-name) are
   swept like the kubernetes.io/cluster/<name>=owned ones.
5. Route53 records external-dns created for a removed cluster of the stack are
   deleted; never the hosted zone, NS/SOA, ACM validation records, hand-made
   records, or another owner's records.
6. The destroy mode file lives under private/ (one per checkout), not /tmp.

Fakes only (plus real botocore profile resolution on temp config files): no
AWS, no network.

Run:  python -m pytest workshop/scripts/tests/test_destroy_credentials_dns.py -q
"""
import importlib.util
import os
import subprocess
import sys

import pytest
import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import sweep_lib as sl  # noqa: E402

TASKFILE = os.path.join(REPO, "cluster-providers", "kind-kro-ack", "Taskfile.yaml")
ENV_VARS = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
            "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN")


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(REPO, "scripts", name))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv(sl.FAILURES_FILE_ENV, str(tmp_path / "private" / "destroy-sweep-failures"))
    sl._SESSIONS.clear()
    yield
    sl._SESSIONS.clear()


class NoCredentialsError(Exception):
    """Same class name as botocore.exceptions.NoCredentialsError."""

    def __init__(self):
        super().__init__("Unable to locate credentials")


# ------------------------------------------------------------- 1. profile

def test_aws_profile_wins_over_aws_default_profile_like_the_cli(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "env-a")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "default")
    assert sl.align_profile() == "env-a"
    assert os.environ["AWS_DEFAULT_PROFILE"] == "env-a"


def test_only_aws_default_profile_is_left_alone(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "env-b")
    assert sl.align_profile() == "env-b"
    assert "AWS_PROFILE" not in os.environ


def test_no_profile_at_all_changes_nothing():
    assert sl.align_profile() == ""
    assert "AWS_DEFAULT_PROFILE" not in os.environ


def write_profiles(tmp_path):
    """Two profiles: 'default' without credentials, 'env-a' with fake static keys."""
    cfg = tmp_path / "config"
    cfg.write_text("[default]\nregion = us-west-2\n\n[profile env-a]\nregion = us-west-2\n")
    creds = tmp_path / "credentials"
    creds.write_text("[env-a]\naws_access_key_id = AKIDEXAMPLEENVA\naws_secret_access_key = notasecret\n")
    return str(cfg), str(creds)


def test_real_boto3_uses_the_cli_profile_when_both_vars_differ(monkeypatch, tmp_path):
    pytest.importorskip("boto3")
    cfg, creds = write_profiles(tmp_path)
    monkeypatch.setenv("AWS_CONFIG_FILE", cfg)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", creds)
    monkeypatch.setenv("AWS_PROFILE", "env-a")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "default")
    s = sl.session("us-west-2")
    assert s.get_credentials().access_key == "AKIDEXAMPLEENVA"


def test_real_boto3_without_credentials_raises_credentials_error(monkeypatch, tmp_path):
    pytest.importorskip("boto3")
    cfg, creds = write_profiles(tmp_path)
    monkeypatch.setenv("AWS_CONFIG_FILE", cfg)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", creds)
    monkeypatch.setenv("AWS_PROFILE", "default")
    with pytest.raises(sl.CredentialsError):
        sl.session("us-west-2")


class FakeBoto3:
    def __init__(self, creds=True):
        self.creds, self.seen = creds, []

    def Session(self, region_name=None):
        self.seen.append(os.environ.get("AWS_DEFAULT_PROFILE"))
        outer = self

        class S:
            def get_credentials(self):
                return object() if outer.creds else None

            def client(self, svc, region_name=None):
                return (svc, region_name)
        return S()


def test_session_aligns_the_profile_before_boto3_reads_it(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "env-a")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "default")
    fake = FakeBoto3()
    assert sl.client("eks", "us-west-2", boto3_mod=fake) == ("eks", "us-west-2")
    assert fake.seen == ["env-a"]


def test_session_without_credentials_raises():
    with pytest.raises(sl.CredentialsError, match="no AWS credentials"):
        sl.session("us-west-2", boto3_mod=FakeBoto3(creds=False))


# ------------------------------------------------------------- 2. fail loudly

def test_run_cli_reports_records_and_exits_3(tmp_path, capsys):
    path = tmp_path / "f"

    def main(_):
        raise sl.CredentialsError("no AWS credentials found for profile default")
    assert sl.run_cli(main, [], "sweep-x", failures_path=str(path)) == sl.CREDENTIALS_EXIT
    err = capsys.readouterr().err
    assert "ERROR sweep-x: no usable AWS credentials" in err and "Nothing was swept" in err
    assert path.read_text() == "sweep-x\n"


def test_run_cli_treats_a_botocore_no_credentials_error_the_same(tmp_path):
    def main(_):
        raise NoCredentialsError()
    assert sl.run_cli(main, [], "sweep-y", failures_path=str(tmp_path / "f")) == 3


def test_run_cli_lets_other_errors_through():
    def main(_):
        raise ValueError("boom")
    with pytest.raises(ValueError):
        sl.run_cli(main, [], "sweep-z")


def test_try_does_not_swallow_a_credentials_error():
    def fn():
        raise NoCredentialsError()
    with pytest.raises(NoCredentialsError):
        sl._try(fn, "thing")


class NoCredsEks:
    def list_clusters(self, **_):
        raise NoCredentialsError()


class Unused:
    def __getattr__(self, name):
        raise AssertionError(f"{name} called without credentials")


CLIS = [
    ("sweep-hub-vpc.py", ["hb", "us-west-2", "hb-hub"], dict(ec2=Unused(), eks=NoCredsEks())),
    ("sweep-spoke-vpcs.py", ["hb", "us-west-2", "hb-hub"], dict(ec2=Unused(), eks=NoCredsEks())),
    ("sweep-log-groups.py", ["hb", "us-west-2", "hb-hub"], dict(logs=Unused(), eks=NoCredsEks())),
    ("sweep-iam-guard.py", ["us-west-2"], dict(eks=NoCredsEks())),
    ("sweep-hub-leftovers.py", ["hb", "us-west-2", "hb-hub"],
     dict(ec2=Unused(), elbv2=Unused(), logs=Unused(), eks=NoCredsEks())),
]


@pytest.mark.parametrize("script,argv,kw", CLIS, ids=[c[0] for c in CLIS])
def test_every_sweep_cli_exits_3_without_credentials(script, argv, kw, tmp_path, capsys):
    mod = load(script)
    rc = sl.run_cli(lambda a: mod.main(a, **kw), argv, script[:-3])
    assert rc == sl.CREDENTIALS_EXIT
    assert "no usable AWS credentials" in capsys.readouterr().err
    assert (tmp_path / "private" / "destroy-sweep-failures").read_text() == script[:-3] + "\n"


def test_rds_cli_exits_3_without_credentials():
    class Rds:
        def describe_db_clusters(self, **_):
            raise NoCredentialsError()

        def describe_db_instances(self, **_):
            raise NoCredentialsError()

        def describe_db_subnet_groups(self, **_):
            raise NoCredentialsError()
    mod = load("sweep-rds.py")
    assert sl.run_cli(lambda a: mod.main(a, rds=Rds()), ["hb", "us-west-2"], "sweep-rds") == 3


def test_shared_iam_cli_exits_3_and_deletes_nothing(tmp_path):
    inv = tmp_path / "destroy-inventory.json"
    inv.write_text('{"clusters": []}')
    (tmp_path / "shared-iam-retained.json").write_text('{"roles": ["shared-role"]}')
    mod = load("sweep-shared-iam.py")
    rc = sl.run_cli(lambda a: mod.main(a, eks=NoCredsEks(), iam=Unused()),
                    ["us-west-2", "--inventory", str(inv)], "sweep-shared-iam")
    assert rc == 3


def test_protect_shared_iam_still_retains_everything_without_credentials(tmp_path, capsys):
    import json
    mod = load("protect-shared-iam.py")
    calls = []

    def kubectl(args):
        if args[0] == "get":
            if args[1] == "roles.iam.aws.upbound.io":
                return 0, json.dumps({"items": [
                    {"metadata": {"name": n, "annotations": {"crossplane.io/external-name": n}},
                     "spec": {"forProvider": {}}} for n in ("hb-own", "shared-role")]})
            return 1, ""
        calls.append(args)
        return 0, ""
    rc = mod.main(["hb", "us-west-2", "hb-hub"], eks=NoCredsEks(), kubectl=kubectl)
    assert rc == sl.CREDENTIALS_EXIT
    assert sorted(c[2] for c in calls) == ["hb-own", "shared-role"], "fail closed: every role retained"
    assert "no usable AWS credentials" in capsys.readouterr().err
    assert (tmp_path / "private" / "destroy-sweep-failures").read_text() == "protect-shared-iam\n"


# ------------------------------------------------------------- 3. preflight

class Sts:
    def __init__(self, acct=None, exc=None):
        self.acct, self.exc = acct, exc

    def get_caller_identity(self):
        if self.exc:
            raise self.exc
        return {"Account": self.acct}


def test_preflight_passes_on_the_same_account(capsys):
    mod = load("sweep-credentials-check.py")
    assert mod.main(["us-west-2", "111122223333"], sts=Sts("111122223333")) == 0
    assert "111122223333" not in capsys.readouterr().out


def test_preflight_refuses_another_account(capsys):
    mod = load("sweep-credentials-check.py")
    assert mod.main(["us-west-2", "111122223333"], sts=Sts("444455556666")) == 1
    err = capsys.readouterr().err
    assert "DIFFERENT AWS accounts" in err and "444455556666" not in err


def test_preflight_without_credentials_exits_3():
    mod = load("sweep-credentials-check.py")
    rc = sl.run_cli(lambda a: mod.main(a, sts=Sts(exc=NoCredentialsError())),
                    ["us-west-2", "111122223333"], "sweep-credentials-check")
    assert rc == 3


# ------------------------------------------------------------- 4. EBS tag

class Ec2Vols:
    def __init__(self, vols):
        self.vols, self.deleted = vols, []

    def describe_volumes(self, Filters=(), NextToken=None):
        return {"Volumes": [{"VolumeId": i, "Tags": t} for i, t in self.vols.items()]}

    def delete_volume(self, VolumeId):
        self.deleted.append(VolumeId)


def test_auto_mode_csi_volumes_are_owned_by_their_cluster():
    assert sl.volume_owners({"Tags": [{"Key": "eks:eks-cluster-name", "Value": "hb-hub"}]}) == ["hb-hub"]
    both = {"Tags": [{"Key": "eks:eks-cluster-name", "Value": "hb-hub"},
                     {"Key": "kubernetes.io/cluster/hb-hub", "Value": "owned"}]}
    assert sl.volume_owners(both) == ["hb-hub"]
    assert sl.volume_owners({"Tags": [{"Key": "kubernetes.io/cluster/hb-hub", "Value": "shared"}]}) == []


def test_auto_mode_volumes_of_the_removed_hub_only_are_selected():
    ec2 = Ec2Vols({
        "vol-hub": [{"Key": "eks:eks-cluster-name", "Value": "hb-hub"}],
        "vol-live-other": [{"Key": "eks:eks-cluster-name", "Value": "ha-hub"}],
        "vol-retained": [{"Key": "eks:eks-cluster-name", "Value": "hb-prod"}],
        "vol-untagged": [{"Key": "Name", "Value": "x"}],
    })
    is_gone = sl.gone_stack_clusters("hb", "hb-hub", {"ha-hub": {"status": "ACTIVE", "vpc": ""}},
                                     {"clusters": [{"name": "hb-prod", "deletionPolicy": "retain"}]})
    sel, _ = sl.select_ebs_volumes(ec2, is_gone)
    assert [v for v, _ in sel] == ["vol-hub"]


# ------------------------------------------------------------- 5. Route53

ZONE = "platform.example.com."


def txt(name, owner):
    return {"Name": name, "Type": "TXT", "TTL": 300, "ResourceRecords": [
        {"Value": f'"heritage=external-dns,external-dns/owner={owner},external-dns/resource=ingress/ns/x"'}]}


def alias(name, typ):
    return {"Name": name, "Type": typ, "AliasTarget": {"HostedZoneId": "ZLB", "DNSName": "lb.example.",
                                                       "EvaluateTargetHealth": True}}


class FakeR53:
    def __init__(self, zones):
        self.zones = zones  # name -> [rrsets]
        self.changes = []

    def list_hosted_zones(self, **_):
        return {"HostedZones": [{"Id": f"/hostedzone/Z{i}", "Name": n} for i, n in enumerate(self.zones)]}

    def list_resource_record_sets(self, HostedZoneId, **kw):
        name = list(self.zones)[int(HostedZoneId[1:])]
        rr = self.zones[name]
        if "StartRecordName" not in kw:  # two pages
            return {"ResourceRecordSets": rr[:3], "IsTruncated": len(rr) > 3,
                    "NextRecordName": "x", "NextRecordType": "A"}
        return {"ResourceRecordSets": rr[3:], "IsTruncated": False}

    def change_resource_record_sets(self, HostedZoneId, ChangeBatch):
        self.changes.append((HostedZoneId, ChangeBatch["Changes"]))

    def delete_hosted_zone(self, **_):
        raise AssertionError("a hosted zone must never be deleted")


def r53_account():
    return FakeR53({
        ZONE: [
            {"Name": ZONE, "Type": "NS", "ResourceRecords": [{"Value": "ns."}]},
            {"Name": ZONE, "Type": "SOA", "ResourceRecords": [{"Value": "soa"}]},
            {"Name": "_acmvalidation." + ZONE, "Type": "CNAME", "ResourceRecords": [{"Value": "_x.acm."}]},
            alias("hb." + ZONE, "A"), alias("hb." + ZONE, "AAAA"),
            txt("aaaa-hb." + ZONE, "hb-hub"), txt("cname-hb." + ZONE, "hb-hub"),
            alias("ha." + ZONE, "A"), txt("cname-ha." + ZONE, "ha-hub"),
            alias("manual." + ZONE, "A"),
            {"Name": "legacy." + ZONE, "Type": "A", "ResourceRecords": [{"Value": "192.0.2.1"}]},
            txt("legacy." + ZONE, "hb-dev"),
        ],
        "other.example.org.": [alias("hb.other.example.org.", "A"), txt("cname-hb.other.example.org.", "hb-hub")],
    })


def is_gone_hb(live=("ha-hub",)):
    return sl.gone_stack_clusters("hb", "hb-hub", {n: {"status": "ACTIVE", "vpc": ""} for n in live},
                                  {"clusters": [{"name": "hb-dev", "deletionPolicy": "delete"}]})


def test_external_dns_records_of_the_removed_stack_only_are_deleted():
    r53 = r53_account()
    n = sl.sweep_dns_records(r53, sl.select_dns_records(r53, "hb." + ZONE.rstrip("."), is_gone_hb())[0])
    assert len(r53.changes) == 1, "one atomic batch, only in the ingress domain's zone"
    zid, changes = r53.changes[0]
    got = [(c["ResourceRecordSet"]["Type"], c["ResourceRecordSet"]["Name"]) for c in changes]
    assert sorted(got) == sorted([("A", "hb." + ZONE), ("AAAA", "hb." + ZONE), ("TXT", "aaaa-hb." + ZONE),
                                  ("TXT", "cname-hb." + ZONE), ("A", "legacy." + ZONE),
                                  ("TXT", "legacy." + ZONE)])
    assert all(c["Action"] == "DELETE" for c in changes)
    types = [t for t, _ in got]
    assert types.index("TXT") > max(i for i, t in enumerate(types) if t != "TXT"), "data before TXT"
    assert n == 6


def test_dns_records_of_a_live_or_unknown_owner_and_hand_made_ones_are_kept():
    r53 = r53_account()
    plans, kept = sl.select_dns_records(r53, "platform.example.com", is_gone_hb())
    names = {rr["Name"] for _, _, rrs in plans for rr in rrs}
    assert not names & {"ha." + ZONE, "cname-ha." + ZONE, "manual." + ZONE, "_acmvalidation." + ZONE, ZONE}
    assert ("cname-ha." + ZONE, "ha-hub") in kept


def test_nothing_while_the_hub_is_live():
    r53 = r53_account()
    plans, _ = sl.select_dns_records(r53, "platform.example.com", is_gone_hb(live=("ha-hub", "hb-hub")))
    names = {rr["Name"] for _, _, rrs in plans for rr in rrs}
    assert "hb." + ZONE not in names


def test_no_domain_or_a_domain_without_a_zone_touches_nothing():
    r53 = r53_account()
    assert sl.select_dns_records(r53, "", is_gone_hb()) == ([], [])
    assert sl.select_dns_records(r53, "d1234.cloudfront.net", is_gone_hb()) == ([], [])


def test_dns_dry_run_writes_nothing(capsys):
    r53 = r53_account()
    plans, _ = sl.select_dns_records(r53, "platform.example.com", is_gone_hb())
    assert sl.sweep_dns_records(r53, plans, dry_run=True) == 0 and r53.changes == []
    assert "would delete Route53 A hb." in capsys.readouterr().out


def test_dns_records_of_a_nested_prefix_hub_are_kept():
    """Review #1174: prefix "hb" must not take the records of "hb-a-hub", even when
    that hub is not live in this region (it may run in another region, same zone)."""
    r53 = FakeR53({ZONE: [alias("a.hb." + ZONE, "A"), txt("a-a.hb." + ZONE, "hb-a-hub")]})
    plans, kept = sl.select_dns_records(r53, "platform.example.com", is_gone_hb(live=()))
    assert plans == [] and ("a-a.hb." + ZONE, "hb-a-hub") in kept


def test_hub_leftovers_cli_passes_the_domain_to_route53(capsys, tmp_path):
    from test_destroy_teardown_leftovers import FakeEc2, FakeElbv2, FakeLogs, FakeEks
    mod = load("sweep-hub-leftovers.py")
    r53 = r53_account()
    inv = tmp_path / "destroy-inventory.json"
    inv.write_text('{"clusters": [{"name": "hb-dev", "deletionPolicy": "delete"}]}')
    rc = mod.main(["hb", "us-west-2", "hb-hub", "--domain", "hb.platform.example.com", "--inventory", str(inv)],
                  ec2=FakeEc2({}), elbv2=FakeElbv2({}), logs=FakeLogs([], []), eks=FakeEks(["ha-hub"]), r53=r53)
    assert rc == 0 and len(r53.changes) == 1
    assert "hub leftovers: 6 selected, 6 deleted" in capsys.readouterr().out


# ------------------------------------------------------------- Taskfile wiring

def destroy_cmds():
    t = yaml.safe_load(open(TASKFILE))
    return [c if isinstance(c, str) else c.get("cmd", "") for c in t["tasks"]["destroy"]["cmds"]]


def test_preflight_runs_before_anything_is_torn_down():
    cmds = destroy_cmds()
    i_pre = next(i for i, c in enumerate(cmds) if "sweep-credentials-check.py" in c)
    i_kind = next(i for i, c in enumerate(cmds) if "destroy-mode" in c)
    assert i_pre < i_kind
    pre = cmds[i_pre]
    assert "rm -f" in pre and "destroy-sweep-failures" in pre and "exit 1" in pre


def test_destroy_mode_is_per_checkout_not_global():
    text = open(TASKFILE).read()
    assert "/tmp/peeks-destroy-mode" not in text
    assert "{{.ROOT_DIR}}/private/destroy-mode" in text


def test_iam_guard_stderr_is_no_longer_hidden_and_domain_is_passed():
    text = "\n".join(destroy_cmds())
    assert 'sweep-iam-guard.py" "$REGION" 2>/dev/null' not in text
    assert '--domain "{{.DOMAIN}}"' in text


def run_final_check(tmp_path, failures):
    cmd = destroy_cmds()[-1]
    root = tmp_path / "root"
    (root / "private").mkdir(parents=True)
    if failures:
        (root / "private" / "destroy-sweep-failures").write_text(failures)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws = bindir / "aws"
    aws.write_text("#!/bin/bash\nexit 254\n")  # describe-cluster: hub gone
    aws.chmod(0o755)
    script = (cmd.replace("{{.ROOT_DIR}}", str(root)).replace("{{.HUB_CLUSTER_NAME}}", "hb-hub")
              .replace("{{.AWS_REGION}}", "us-west-2").replace("{{.C_ERR}}", "").replace("{{.C_OK}}", "")
              .replace("{{.C_INFO}}", "").replace("{{.C_RESET}}", ""))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)


def test_final_check_fails_when_a_helper_had_no_credentials(tmp_path):
    res = run_final_check(tmp_path, "sweep-hub-vpc\nsweep-rds\nsweep-hub-vpc\n")
    assert res.returncode == 1
    assert "sweep-hub-vpc sweep-rds" in res.stdout and "Destroy complete" not in res.stdout


def test_final_check_passes_without_failures(tmp_path):
    res = run_final_check(tmp_path, "")
    assert res.returncode == 0 and "Destroy complete" in res.stdout
