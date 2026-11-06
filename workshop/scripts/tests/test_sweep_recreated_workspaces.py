"""Hermetic test: the stack sweep does not leave an AMP or AMG workspace that the hub's
still-running Crossplane re-created after the sweep had deleted it.

Live case: the sweep's §5 deleted the AMP workspace <prefix>-observability-amp at
14:53:29, then submitted the hub EKS delete. The hub's Crossplane was still running (the
cluster takes minutes to go) and its Workspace managed resource was still live (Argo CD had
not reached its sync wave yet), so it saw the workspace missing and CREATED a new one at
14:54:16. Nothing deleted it again: the final re-sweep (§16) only re-deleted scrapers, and
§17 does not count AMP workspaces (Crossplane tags them without the prefix tag), so the
sweep printed DESTROY COMPLETE with the workspace left behind.

Fake AMP/AMG: while the hub is "alive", deleting one of our workspaces makes Crossplane
create a new one with a new id. The hub goes when §6 looks it up. No AWS, no sleeps.
Run:  python -m pytest workshop/scripts/tests/test_sweep_recreated_workspaces.py -q
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_sweep_orchestration as orch  # noqa: E402  (puts the sweep dir on sys.path)


class _World:
    def __init__(self, hub_goes_at_step6=True):
        self.hub_alive = True
        self.hub_goes = hub_goes_at_step6
        self.amp = {"ws-1": "peeks-observability-amp", "ws-other": "other-observability-amp"}
        self.amg = {"g-1": "peeks-observability-amg", "g-other": "otherstack-amg"}
        self.n = 1
        self.created = []

    def recreate(self, kind, name):
        if self.hub_alive:
            self.n += 1
            new = f"{kind}-{self.n}"
            (self.amp if kind == "ws" else self.amg)[new] = name
            self.created.append((kind, name))


class FakeAmp(orch.FakeClient):
    def __init__(self, w):
        super().__init__("amp")
        self.w = w

    def list_scrapers(self, **_):
        return {"scrapers": []}

    def list_workspaces(self, **_):
        return {"workspaces": [{"workspaceId": i, "alias": a, "status": {"statusCode": "ACTIVE"}}
                               for i, a in self.w.amp.items()]}

    def delete_workspace(self, workspaceId):
        name = self.w.amp.pop(workspaceId)
        self.w.recreate("ws", name)


class FakeGrafana(orch.FakeClient):
    def __init__(self, w):
        super().__init__("grafana")
        self.w = w

    def list_workspaces(self, **_):
        return {"workspaces": [{"id": i, "name": n, "status": "ACTIVE"} for i, n in self.w.amg.items()]}

    def delete_workspace(self, workspaceId):
        name = self.w.amg.pop(workspaceId)
        self.w.recreate("g", name)


class FakeEks(orch.FakeClient):
    def __init__(self, w):
        super().__init__("eks")
        self.w = w

    def describe_cluster(self, name):
        if name.endswith("-hub") and self.w.hub_goes:
            self.w.hub_alive = False   # §6: the hub cluster (and its Crossplane) is gone
        raise orch._ResourceNotFound(name)


def _run(world):
    def factory(service, **kwargs):
        return {"amp": FakeAmp, "grafana": FakeGrafana, "eks": FakeEks}.get(
            service, lambda w: orch.FakeClient(service))(world)

    with mock.patch("sweep.context.boto3.client", side_effect=factory):
        from sweep.orchestrator import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main("us-west-2", "peeks")
    return rc, buf.getvalue()


class RecreatedWorkspacesTest(unittest.TestCase):
    def test_workspaces_recreated_before_the_hub_went_are_deleted_again(self):
        w = _World()
        rc, out = _run(w)
        self.assertTrue(w.created, "the fake never re-created anything")
        self.assertEqual(sorted(w.amp.values()), ["other-observability-amp"], out)
        self.assertEqual(sorted(w.amg.values()), ["otherstack-amg"], out)
        self.assertIn("[re-sweep] recreated Deleted AMP workspace", out)
        self.assertEqual(rc, 0, out)

    def test_a_workspace_still_there_at_the_end_is_residue(self):
        # The hub never goes (its delete stuck): Crossplane re-creates every time. The gate
        # must say so instead of DESTROY COMPLETE.
        w = _World(hub_goes_at_step6=False)
        rc, out = _run(w)
        self.assertIn("amp-workspace:", out)
        self.assertIn("amg-workspace:", out)
        self.assertNotIn("DESTROY COMPLETE", out)
        self.assertEqual(rc, 1, out)

    def test_other_deployments_workspaces_are_never_touched_or_counted(self):
        w = _World()
        w.amp = {"ws-other": "other-observability-amp"}
        w.amg = {"g-other": "otherstack-amg"}
        rc, out = _run(w)
        self.assertEqual(rc, 0, out)
        self.assertIn("ws-other", w.amp)
        self.assertIn("g-other", w.amg)


if __name__ == "__main__":
    unittest.main()
