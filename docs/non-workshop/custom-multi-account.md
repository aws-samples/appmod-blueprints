# 3.2 · Custom — multi-account + create a spoke in another account

A spoke is a workload EKS cluster the hub provisions and manages through KRO + ACK. This page covers
**two cases**:

- **Same‑account spokes** — the spoke runs in the hub's own account (the common case).
- **Cross‑account spokes** — the spoke runs in a **different** AWS account.

The two cases use **different** mechanisms, and both are kept on purpose (neither replaces the
other).

---

## Background — how a spoke's ACK access works (CARM)

For the hub's ACK controllers to provision a spoke's AWS resources, the spoke's **namespace** needs
an `IAMRoleSelector` (ACK Cross‑Account Resource Management, "CARM"). The selector maps the spoke
namespace to the `<prefix>-cluster-mgmt-<svc>` roles ACK assumes. Without a selector, ACK creates
the CR but **silently never reconciles** it.

There are two ways to produce that selector:

| Mechanism | Covers | Account | Where you declare it |
|---|---|---|---|
| `global.spokeNames` (names only) | **same‑account** spokes on the direct path | hub's account only | the `spoke_namespaces` annotation on the hub cluster‑secret |
| `configs/multi-acct/values.yaml` (`<spoke>: "<account-id>"`) | **any** account (incl. cross‑account) | any | your fleet repo |

---

## Case A — same-account spokes (`global.spokeNames`)

On the direct (`kind-kro-ack`) path, `.Values.clusters` (the workshop's multi‑acct map) is never
populated, so same‑account spoke namespaces would get no selector. `global.spokeNames` closes that
gap: a **list of names** (never an account number); each name inherits `global.accountId` (the hub's
own account).

This is the fix that ships with
[#1157](https://github.com/aws-samples/appmod-blueprints/issues/1157): strictly additive, default
`[]` (a no‑op — rendering is byte‑identical when unset), and it never overwrites an explicit
`.Values.clusters` entry.

### How to set it

The `multi-acct` registry entry reads `global.spokeNames` from the **`spoke_namespaces` annotation**
on the hub cluster‑secret, exactly like `accountId` (`aws_account_id`) and `clusterName`
(`aws_cluster_name`). Set that annotation to a comma/space‑delimited list of your spoke namespaces:

```bash
# Add/patch the spoke_namespaces annotation on the hub cluster-secret (names only, no account IDs):
kubectl --kubeconfig $PWD/private/kubeconfig -n argocd \
  annotate secret -l argocd.argoproj.io/secret-type=cluster \
  spoke_namespaces="dev,prod" --overwrite
```

Supply the annotation through your fleet/Secrets‑Manager contract so it survives re‑seeds (the same
channel that carries `aws_account_id` / `aws_cluster_name`). Names are arbitrary and
customer‑supplied; the account is supplied once via `global.accountId`, never per spoke — so **no
account ID ever enters a public repo**.

> **Verify the selectors render** (one per ACK service, per spoke namespace):
> ```bash
> kubectl get iamroleselectors.services.k8s.aws -A
> kubectl get ns dev prod
> ```

---

## Case B — cross-account spokes (`configs/multi-acct/values.yaml`)

When a spoke must run in a **different** account than the hub, a name‑only list cannot express it —
you need the explicit account ID. Declare it in your **fleet repo** at
`configs/multi-acct/values.yaml`:

```yaml
# configs/multi-acct/values.yaml  (in YOUR fleet repo — keep private if it carries real account IDs)
clusters:
  <spoke-name>: "<spoke-account-id>"     # the 12-digit account the spoke runs in
```

An explicit entry here **always wins** over `global.spokeNames` for the same name (the chart guards
with `hasKey`), so a spoke listed in both keeps its explicit cross‑account value and is not rendered
twice.

> **Out‑of‑band requirement (verify live).** For a real cross‑account spoke, the trust policies of
> the `<prefix>-cluster-mgmt-<svc>` roles **in the spoke account** must allow the hub to assume them.
> That trust wiring lives outside the CARM chart and is not provisioned by this map — set it up in
> the spoke account before expecting reconciliation.

---

## Create the spoke (both cases)

The CARM selector only grants ACK access; the spoke itself is declared in the fleet repo, the same
way [quick-existing-fleet.md](quick-existing-fleet.md) describes. In **your** fleet repo:

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
       # accountId: OMIT for same-account (inherits global.accountId).
       # For cross-account, the account comes from configs/multi-acct/values.yaml (Case B).
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
5. Add the CARM coverage (Case A `global.spokeNames` **or** Case B
   `configs/multi-acct/values.yaml`), then `git commit && git push` to your fleet repo.

ArgoCD reconciles on its next sync: `clusters-kro-<name>` appears, KRO creates the
`EksclusterWithVpc`, ACK provisions the VPC + EKS, and `fleet-secrets` registers the spoke.

> **Generative alternative (`spokes:apply`, needs a PAT).** Instead of hand‑editing the repo you can
> declare a `spokes:` map in `config.local.yaml` and let the installer materialise and **push** the
> files. Because it writes to the repo it needs a git token — see
> [custom-prerequisites.md](custom-prerequisites.md), section 4.

---

## Verify

```bash
export KUBECONFIG=$PWD/private/kubeconfig
kubectl get applications -A | grep clusters-kro-<name>
kubectl get eksclusterwithvpcs.kro.run -n <name>
kubectl get iamroleselectors.services.k8s.aws -A | grep <name>
aws eks describe-cluster --name <name> --region <region> --query 'cluster.status'
```

---

## Next

- Tear a spoke down cleanly → [custom-delete-spoke.md](custom-delete-spoke.md)
- See what it costs → [custom-cost.md](custom-cost.md)
