# Advanced operations — delete a spoke

> Applies to every mode. The workshop ships ready‑made tasks (see the honesty note); this page
> gives the equivalent sequence for a direct install.

Cleanly tear down **one** spoke provisioned through KRO + ACK, without orphaning its live AWS
resources. The sequence is **remove the spec → prune through the still‑present app → sweep what
outlives it**, in that order.

> ### ⚠️ Honesty note — read this first
> The repo ships ready‑made tasks for this — `spokes:disable-kro`, `spokes:sweep-kro`,
> `spokes:disable-all` — but they live in `workshop/Taskfile.yaml` and are **wired for the
> workshop**: they target the `tenants/workshop` overlay and clone the **IDE‑bootstrapped GitLab**
> fleet‑config, and they are **not** reachable from the root `Taskfile.yaml` used by a direct
> install. On the direct (`kind-kro-ack`) path your fleet repo is your own (tenant `default`), so
> **run the equivalent sequence below by hand** against your fleet repo. The steps mirror exactly
> what `spokes:disable-kro` / `spokes:sweep-kro` do (verified against their code); only the repo and
> tenant differ. **This mapping onto the direct path is to be validated on a real direct‑path
> teardown** — the underlying mechanism is code‑verified, but the ready‑made task is not yet wired
> to the direct path.

Set these for the commands below:

```bash
export KUBECONFIG=$PWD/private/kubeconfig     # hub kubeconfig the install wrote
SPOKE=<name>                                  # the spoke to delete
REGION=<region>
```

---

## The critical ordering rule

Each KRO spoke is driven by one ArgoCD app, `clusters-kro-<name>`, generated from the trigger file
`clusters/<name>.json`. **Do not delete the trigger file first.** The `clusters-kro` ApplicationSet
runs with `preserveResourcesOnDeletion=true`, so removing the trigger makes the appset drop the app
*without* pruning — which **orphans** the `EksclusterWithVpc` (the live EKS cluster + VPC survive,
unmanaged). Instead: remove only the **spec**, prune **through** the still‑present app, then clean up
the trigger.

---

## Phase 1 — remove the spoke spec (keep the trigger)

In your fleet repo, delete only the `<name>:` block from the KRO values, keeping
`clusters/<name>.json` for now:

```bash
# in a clone of YOUR fleet repo
yq -i 'del(.clusters."'"$SPOKE"'")' \
  gitops/fleet/spoke-values/tenants/default/kro-clusters/values.yaml
git commit -am "feat: disable spoke $SPOKE (remove KRO cluster spec)" && git push
```

---

## Phase 2 — prune through the still-present app (deletes the cluster + VPC)

Pruning the app triggers KRO/ACK to delete the live `EksclusterWithVpc` — i.e. the EKS cluster and
its VPC — via the resources' deletion policy. Prefer the ArgoCD CLI; fall back to a `kubectl` patch
if you have no ArgoCD session:

```bash
APP="clusters-kro-$SPOKE"

# Preferred: ArgoCD CLI (uses your existing session)
argocd app get "$APP" --refresh
argocd app sync "$APP" --prune --timeout 600

# Fallback (no argocd CLI / no token): patch the Application to run a prune sync
kubectl -n argocd patch application "$APP" --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD","prune":true}}}'
```

Wait for the prune to actually complete before Phase 3 — never clean up before the live resource is
confirmed gone.

---

## Phase 3 — post-prune cleanup (fleet repo)

Only **after** a confirmed prune, remove the trigger marker, the fleet member and the per‑cluster
overlay in your fleet repo:

```bash
rm -f gitops/fleet/spoke-values/tenants/default/kro-clusters/clusters/"$SPOKE".json
# Legacy only: fleet repos created before kro-clusters owned the selectors may still list the
# spoke in configs/multi-acct (ignored now); drop it as cleanup.
yq -i 'del(.clusters."'"$SPOKE"'")' configs/multi-acct/values.yaml 2>/dev/null || true
rm -rf gitops/fleet/members/"$SPOKE" overlays/clusters/"$SPOKE"
git commit -am "chore: remove $SPOKE marker + fleet member (post-prune)" && git push
```

The spoke's namespace and IAMRoleSelectors are rendered by `clusters-kro-<name>` with
`Prune=false,Delete=false`, so the prune above leaves them in place on purpose: ACK still needs them
to finish deleting the spoke's CRs. They are removed in the sweep, once the namespace is gone.

### De-register from ArgoCD

The `clusters-kro` and `fleet-secrets` ApplicationSets are create‑update (they never delete an
app), so the files above being gone still leaves `clusters-kro-<name>` and `fleet-secret-<name>`
behind, and the latter keeps the cluster Secret. Delete them **after** both appsets have re‑read the
fleet repo (so they can't recreate the apps):

```bash
for AS in clusters-kro fleet-secrets; do
  kubectl -n argocd annotate applicationsets.argoproj.io "$AS" \
    argocd.argoproj.io/application-set-refresh=true --overwrite
done
# wait until the refresh annotation clears on both, then:
kubectl -n argocd delete applications.argoproj.io "clusters-kro-$SPOKE" "fleet-secret-$SPOKE" --ignore-not-found
kubectl -n argocd delete externalsecrets.external-secrets.io "fleet-secret-$SPOKE" --ignore-not-found
kubectl -n argocd delete secret "$SPOKE" --ignore-not-found
```

---

## Phase 4 — sweep what outlives the cluster

Some objects survive the cluster deletion and must be swept last. **Never sweep a live spoke** —
wait until both the `EksclusterWithVpc` instance and the EKS cluster are gone:

```bash
# 1. Wait until the spoke is truly gone
kubectl get eksclusterwithvpcs.kro.run -n "$SPOKE" -o name       # expect: nothing
aws eks describe-cluster --name "$SPOKE" --region "$REGION"      # expect: ResourceNotFound

# 2. Confirm no ArgoCD app still targets the spoke namespace (would recreate CRs)
kubectl get applications.argoproj.io -n argocd -o json \
  | jq -r --arg c "$SPOKE" '.items[] | select(.spec.destination.namespace==$c) | .metadata.name'

# 3. Delete the spoke's hub namespace (holds hub-side addon CRs orphaned on de-registration)
kubectl delete namespace "$SPOKE" --wait=true --timeout=10m

# 4. Delete the per-spoke IAMRoleSelectors (multi-acct runs prune:false, so removing the
#    spoke from its values does NOT delete them) — only after the namespace is gone
kubectl get iamroleselectors.services.k8s.aws -o json \
  | jq -r --arg c "$SPOKE" '.items[] | select(.spec.namespaceSelector.names==[$c]) | .metadata.name' \
  | xargs -r -n1 kubectl delete iamroleselectors.services.k8s.aws
```

Finally, sweep IAM objects named `<name>-*` that outlive the cluster (the ack‑pod‑identity
roles/policies with a retain deletion policy, and any roles the spoke's own Crossplane created).
Match by name **and** by the tag that ties them to the spoke (`eks:kubernetes-namespace` /
`services.k8s.aws/namespace` == `<name>`, or `managed-by=crossplane` on a `<name>-Crossplane*`
role) before deleting — detach/delete attached and inline policies and instance‑profile
associations first, then the role; and delete `Local`‑scope policies named `<name>-*`.

> These IAM deletions are destructive. Review the matched list before deleting, and keep the
> name‑plus‑tag filter so you never remove a role that merely shares a name prefix.

---

## Verify the teardown is clean

```bash
aws eks list-clusters --region "$REGION"                              # the spoke is gone
aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=tag:Name,Values=$SPOKE*" --query 'Vpcs[].VpcId'     # no orphan spoke VPC
kubectl get ns "$SPOKE" 2>&1                                          # NotFound
aws iam list-roles --query "Roles[?starts_with(RoleName,'$SPOKE-')].RoleName" --output text   # empty
```

A leftover `DELETE_FAILED` or orphaned spoke VPC (with VPC‑endpoint ENIs) is the usual residue when
Phase 2's prune did not complete — re‑run the prune, confirm the `EksclusterWithVpc` is gone, then
redo the sweep.
