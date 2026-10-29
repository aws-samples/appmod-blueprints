# 3.2 · Custom — multi-account + create a spoke in another account

A spoke is a workload EKS cluster the hub provisions and manages through KRO + ACK. This page covers
**two cases**:

- **Same‑account spokes** — the spoke runs in the hub's own account (the common case).
- **Cross‑account spokes** — the spoke runs in a **different** AWS account.

Both cases use **one** mechanism: the spoke's entry in your fleet repo. The only difference is
whether the entry carries an `accountId`.

---

## Background — how a spoke's ACK access works (CARM)

For the hub's ACK controllers to provision a spoke's AWS resources, the spoke's **namespace** needs
an `IAMRoleSelector` (ACK Cross‑Account Resource Management, "CARM"). The selector maps the spoke
namespace to the `<prefix>-cluster-mgmt-<svc>` roles ACK assumes. Without a selector, ACK creates
the CR but **silently never reconciles** it.

You do not declare the selectors yourself. The `kro-clusters` chart renders them, together with the
spoke's namespace, **from the spoke's own entry** in
`gitops/fleet/spoke-values/tenants/<tenant>/kro-clusters/values.yaml` (step 2 below). A spoke cannot
exist without its selectors, and there is no second list to keep in sync.

| Objects | Rendered by | Account in the role ARN |
|---|---|---|
| `Namespace <spoke>` + `IAMRoleSelector <svc>-<spoke>` (8 services) | `clusters-kro-<spoke>` (`kro-clusters` chart) | the entry's `accountId`, else the hub's account (`global.accountId`) |
| `Namespace <hub>` + `IAMRoleSelector <svc>-<hub>` | `multi-acct-<hub>` | the hub's account |

`configs/multi-acct/values.yaml` no longer declares spokes: `multi-acct` reads it only for an account
override of the hub itself, and ignores any other key. Details, including how an existing fleet repo
is migrated without deleting anything, are in the
[kro-clusters README](../../gitops/abstractions/kro/kro-clusters/README.md#ack-carm-coverage-iamroleselectors).

---

## Case A — same-account spokes

Omit `accountId` in the spoke's entry. The selectors inherit the hub's account (`global.accountId`,
which the hub passes from its own cluster‑secret), so **no account ID ever enters your repo**.

## Case B — cross-account spokes

Set `accountId: "<spoke-account-id>"` in the spoke's entry (keep that repo **private** if it carries
real account IDs). The selectors then point at the `<prefix>-cluster-mgmt-<svc>` roles **in the spoke
account**.

> **Out‑of‑band requirement (verify live).** For a real cross‑account spoke, the trust policies of
> the `<prefix>-cluster-mgmt-<svc>` roles **in the spoke account** must allow the hub to assume them.
> That trust wiring is not provisioned by the chart — set it up in the spoke account before
> expecting reconciliation.

---

## Create the spoke (both cases)

The spoke is declared in the fleet repo, the same way [quick-existing-fleet.md](quick-existing-fleet.md)
describes; its CARM selectors come with it. In **your** fleet repo:

1. **Trigger file** — `gitops/fleet/spoke-values/tenants/default/kro-clusters/clusters/<name>.json`:
   ```json
   {"clusterName": "<name>"}
   ```
2. **Per‑spoke spec** — a `<name>:` block under `clusters:` in
   `gitops/fleet/spoke-values/tenants/default/kro-clusters/values.yaml`:
   ```yaml
   clusters:
     <name>:
       clusterName: <name>
       tenant: default
       environment: <env>
       provider: kro-ack
       fleetMember: spoke
       region: <region>
       k8sVersion: "1.31"
       enableGeneralPurposeNodePool: true
       cidr:
         vpcCidr: "10.3.0.0/16"          # disjoint from the hub and every other spoke
         publicSubnet1Cidr: "10.3.1.0/24"
         publicSubnet2Cidr: "10.3.2.0/24"
         privateSubnet1Cidr: "10.3.11.0/24"
         privateSubnet2Cidr: "10.3.12.0/24"
       # accountId: OMIT for same-account (Case A, inherits global.accountId).
       # accountId: "<spoke-account-id>"   # cross-account (Case B)
   ```
3. **Fleet member** — `gitops/fleet/members/<name>/values.yaml`:
   ```yaml
   clusterName: <name>
   mode: externalSecret
   externalSecret:
     enabled: true
   labels:
     environment: <env>
     tenant: default
   ```
4. **Per‑cluster overlay** — `overlays/clusters/<name>/platform-manifests/values.yaml`:
   ```yaml
   huggingfaceModels: []
   ```
5. `git commit && git push` to your fleet repo.

ArgoCD reconciles on its next sync: `clusters-kro-<name>` appears and creates the spoke's namespace
and IAMRoleSelectors first (sync waves -2/-1), then KRO creates the `EksclusterWithVpc`, ACK
provisions the VPC + EKS, and `fleet-secrets` registers the spoke.

> **Generative alternative (`task spokes:enable-kro -- <name>`, needs a PAT).** Instead of
> hand‑editing the repo you can run `spokes:enable-kro` (`workshop/Taskfile.yaml`, run from
> `workshop/`): it clones the fleet repo, writes the files above and **pushes** them. It is wired for
> the workshop layout (`tenants/workshop`, the IDE‑bootstrapped GitLab), so on a direct install the
> hand‑edit above is the supported path; the provider Taskfile (`cluster-providers/kind-kro-ack`) has
> no spoke‑writing task. Because it writes to the repo it needs a git token — see
> [custom-install.md](custom-install.md#2-git-token-only-for-a-private-fleet-repo-or-generative-spoke-push), section 2.

---

## Verify

```bash
export KUBECONFIG=$PWD/private/kubeconfig
kubectl get applications -A | grep clusters-kro-<name>
kubectl get eksclusterwithvpcs.kro.run -n <name>
kubectl get iamroleselectors.services.k8s.aws -o name | grep -- '-<name>$'   # 8 selectors
aws eks describe-cluster --name <name> --region <region> --query 'cluster.status'
```

---

## Next

- Tear a spoke down cleanly → [delete-spoke.md](delete-spoke.md)
- See what it costs → [cost.md](cost.md)
