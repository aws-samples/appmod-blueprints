---
inclusion: auto
---

# Troubleshooting Guide

## ArgoCD Issues

### Application Out of Sync
**Symptoms**: Application shows "OutOfSync" status

**Diagnosis**:
```bash
argocd app get <app-name>
argocd app diff <app-name>
```

**Solutions**:
- Check for manual changes in cluster
- Verify Git repository is accessible
- Review sync waves and dependencies
- Check for resource conflicts

### Sync Failures
**Symptoms**: Sync operation fails

**Common Causes**:
- Missing CRDs
- Invalid manifests
- Resource dependencies not met
- Insufficient permissions

**Solutions**:
- Check sync operation logs
- Validate manifests with kubectl dry-run
- Review resource ordering (sync waves)
- Verify service account permissions

### Phantom-healthy: manifest app reports Healthy before workloads are Ready

**Symptom**: `argocd app get <app>` (e.g. `argo-workflows-peeks-hub`) shows `Synced/Healthy`,
but the namespace/pods/CRDs don't exist yet and a force-sync "creates nothing". Most often seen
on a freshly (re)provisioned hub and misread as "X is missing / broken".

**Root cause**: For a `type: manifest` app, ArgoCD computes health from the *applied* resources
and marks the app Healthy as soon as the manifests are applied — it does NOT wait for a
Deployment inside those manifests (e.g. `workflow-controller`) to become Available, nor for the
controller to start serving its CRDs. Apps at a late sync-wave (argo-workflows is wave 7) widen
this window. It is a **timing race**, not a deploy failure — the app reconciles fully a bit
later (confirmed on event 8: re-synced cleanly ~8h after the initial sync, controller actively
processing CI workflows).

**Diagnosis / correct gate** — check the workload, not the ArgoCD health:
```bash
kubectl rollout status deploy/workflow-controller -n argo --timeout=300s
kubectl rollout status deploy/argo-server         -n argo --timeout=300s
kubectl get crd workflows.argoproj.io >/dev/null && echo "Workflow CRD OK"
kubectl get workflowtemplates -A --no-headers | wc -l   # expect >0
```

**Fix**: none required in platform code — wait for the controller to be Ready (and re-check)
rather than trusting the app's `Healthy`. Validation harnesses must gate Module 30 on the
controller rollout, not on `argocd app get` (see scripts/validation/validate-workshop-from-content.md
→ "Workflow Polling" prerequisite gate).

## Backstage Issues

### Plugin Not Loading
**Diagnosis**:
```bash
# Check backend logs
kubectl logs -n backstage deployment/backstage-backend

# Check frontend console
# Open browser dev tools
```

**Solutions**:
- Verify plugin registration in backend
- Check plugin dependencies installed
- Review plugin configuration
- Clear browser cache

### Catalog Entities Not Appearing
**Diagnosis**:
```bash
# Check catalog processor logs
kubectl logs -n backstage deployment/backstage-backend | grep catalog
```

**Solutions**:
- Verify catalog provider configuration
- Check entity YAML syntax
- Review entity processor registration
- Refresh catalog manually

## Kro Issues

### RGD Not Discovered
**Diagnosis**:
```bash
kubectl get resourcegraphdefinition -A
kubectl describe rgd <rgd-name> -n kro-system
```

**Solutions**:
- Verify RGD is in correct namespace
- Check Kro controller logs
- Validate RGD YAML syntax
- Ensure Kro CRDs are installed

### RGD in a subdirectory never deploys (ArgoCD app reports Synced/Healthy)

**Symptom**: A KRO RGD that lives in a subdirectory (e.g.
`addons/charts/kro/resource-groups/manifests/cicd-pipeline/cicd-pipeline.yaml`) is missing on
the cluster even though its ArgoCD app (e.g. `kro-manifests-hub-peeks-hub`) shows
`Synced/Healthy`. A force-sync creates nothing.

**Root cause**: A `type: manifest` (directory) ArgoCD source only reads the top-level directory
unless `directory.recurse: true` is set — and even with recurse, a `directory.exclude` glob can
skip the subdirectory. In this repo the **spoke** `kro-manifests` registry entry deliberately
`exclude:`s `{cicd-pipeline/**,...}`, while the **hub** `kro-manifests-hub` entry recurses with
no exclude (so the hub gets `cicdpipeline.kro.run`). Confirm you're looking at the right app.

**Diagnosis**:
```bash
kubectl get application kro-manifests-hub-peeks-hub -n argocd \
  -o jsonpath='{range .spec.sources[*]}path={.path} recurse={.directory.recurse} exclude={.directory.exclude}{"\n"}{end}'
kubectl get resourcegraphdefinitions.kro.run | grep cicd   # expect cicdpipeline.kro.run Active
```

**Fix**: in `gitops/addons/registry/platform.yaml`, ensure the relevant entry has
`directory.recurse: true` and that its `exclude` does not cover the subdir (or move the manifest
to the top-level `manifests/` directory). NOTE: this is already correct in committed code — a
phantom "missing RGD" is usually a sync-timing window on a fresh hub (the app is at sync-wave
-2), not a config error. Re-check after the app finishes its first reconcile.

### ResourceGroup Stuck
**Diagnosis**:
```bash
kubectl describe resourcegroup <name> -n <namespace>
kubectl get events -n <namespace> --sort-by='.lastTimestamp'
```

**Solutions**:
- Check resource dependencies
- Verify required CRDs exist
- Review resource status conditions
- Check for permission issues

## Kubernetes Issues

### Pod CrashLoopBackOff
**Diagnosis**:
```bash
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace> --previous
```

**Common Causes**:
- Application errors
- Missing configuration
- Resource limits too low
- Failed health checks

### ImagePullBackOff
**Diagnosis**:
```bash
kubectl describe pod <pod-name> -n <namespace>
```

**Solutions**:
- Verify image exists in registry
- Check image pull secrets
- Verify registry permissions
- Check network connectivity

## Helm Issues

### Chart Dependency Errors
**Diagnosis**:
```bash
helm dependency list ./gitops/addons/charts/<chart-name>
```

**Solutions**:
```bash
# Build dependencies
task build-helm-dependencies

# Or manually
cd ./gitops/addons/charts/<chart-name>
helm dependency update
```

### Template Rendering Errors
**Diagnosis**:
```bash
helm template <release-name> ./path/to/chart \
  -f values.yaml \
  --debug
```

**Solutions**:
- Check values file syntax
- Verify template syntax
- Review variable references
- Test with minimal values

## Network Issues

### Service Not Accessible
**Diagnosis**:
```bash
kubectl get svc -n <namespace>
kubectl get endpoints -n <namespace>
kubectl describe svc <service-name> -n <namespace>
```

**Solutions**:
- Verify pod labels match service selector
- Check pod readiness
- Review network policies
- Test from within cluster

### Ingress Not Working
**Diagnosis**:
```bash
kubectl get ingress -n <namespace>
kubectl describe ingress <ingress-name> -n <namespace>
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

**Solutions**:
- Verify ingress class
- Check DNS configuration
- Review TLS certificates
- Validate ingress rules

### Shared ALB group: a catch-all '/' ingress shadows specific paths (breaks SSO)

**Symptom**: After exposing a service at the host root (path `/`, pathType `Prefix`) on the
shared `platform` ALB group, OIDC/SAML logins break — `/keycloak/*` (and other specific paths)
return the catch-all service's content instead of Keycloak. Backstage OIDC, ArgoCD SSO, Grafana
SAML and Argo Workflows SSO all fail because the Keycloak login form is unreachable.

**Root cause**: All these ingresses share one ALB (`ingressClassName: platform`). The AWS Load
Balancer Controller orders listener rules within a group by
`alb.ingress.kubernetes.io/group.order` (ascending). An ingress **without** that annotation is
interleaved by creation order, so a `/*` catch-all (e.g. Kargo) can land at a LOWER priority
number than `/keycloak` and match everything first.

**Diagnosis**:
```bash
# List the live rule priorities (lower number = evaluated first)
ALB=$(aws elbv2 describe-load-balancers --query "LoadBalancers[?contains(LoadBalancerName,'k8s')].LoadBalancerArn" --output text | head -1)
L=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB" --query "Listeners[?Port==\`443\`].ListenerArn" --output text)
aws elbv2 describe-rules --listener-arn "$L" --query 'Rules[].{p:Priority,path:Conditions[?Field==`path-pattern`].Values|[0]}' --output text | sort -n
```

**Fix**: give the catch-all ingress a high `group.order` so it evaluates LAST:
```yaml
annotations:
  alb.ingress.kubernetes.io/group.order: '100'
```
For Kargo specifically this lives in
`gitops/overlays/environments/control-plane/kargo/values.yaml` under `api.ingress.annotations`.

## ACK (AWS Controllers for Kubernetes) Issues

### ACK "scheduled for deletion" loop
**Symptoms**: ACK resource stuck with `InvalidRequestException: You can't create this secret because a secret with this name is already scheduled for deletion`

**Root cause**: AWS Secrets Manager (or other services) has a deletion delay. ACK caches the error and enters a 10h backoff.

**Fix**:
1. Wait for AWS to fully purge the resource (check with `aws secretsmanager describe-secret`)
2. Delete the K8s CR (remove finalizers first if needed)
3. Let KRO/ArgoCD recreate the CR — **new K8s objects don't inherit the cached error**
4. If still stuck, patch `spec.description` or `spec.tags` to bump `.metadata.generation` which forces a fresh reconciliation cycle

### ACK "Resource already exists" after restore
**Symptoms**: ACK tries `CreateSecret` but gets `Resource already exists`

**Fix**: Delete the secret from AWS (`force-delete-without-recovery`), then bump the CR's generation by patching a mutable spec field.

### IAMRoleSelector not taking effect
**Symptoms**: ACK uses the default capability role instead of the cluster-mgmt role

**Fix**: Verify IAMRoleSelector exists with correct `namespaceSelector` and `resourceTypeSelector`. After creating/updating selectors, delete the stuck ACK resource CR to force recreation — ACK picks up selectors only on fresh reconciliation.

### Force ACK reconciliation
The `services.k8s.aws/force-reconcile` annotation does NOT always work (especially with capability-managed ACK). The reliable method is to **patch a mutable spec field** (e.g., `spec.description`, `spec.tags`) to increment `.metadata.generation`.

## ArgoCD 3.x (EKS Capability) Issues

### `dig` function fails on annotations
**Symptoms**: `error calling dig: interface conversion: interface {} is map[string]string, not map[string]interface {}`

**Root cause**: ArgoCD 3.x strict Go template typing. `dig` doesn't work on `map[string]string` (annotations).

**Fix**: Replace `{{ dig "key" default .metadata.annotations }}` with `{{ or (index .metadata.annotations "key") default }}`

### Cluster secret ignored by ArgoCD
**Symptoms**: `controller is configured to ignore cluster`

**Fix**: Add `project: default` to the cluster secret's `stringData`. ArgoCD 3.x requires this field.

### `missingkey=error` with optional annotations
**Symptoms**: `map has no entry for key "annotation_name"`

**Fix**: Use `index` instead of dot notation: `{{ or (index .metadata.annotations "key") "default" }}`

### KRO RGD "breaking changes detected" on CRD update
**Symptoms**: RGD shows `Inactive` with message `cannot update CRD: breaking changes detected: Property X was removed`

**Fix**: Delete the CRD manually (`kubectl delete crd <name>.kro.run`), then sync to let KRO recreate it. **Warning**: This deletes all instances of that CRD — may trigger resource deletion in AWS. Only do this when safe.

## Crossplane Issues

### NAT Gateway reference resolution race condition
**Symptoms**: Route stuck with `referenced field was empty (referenced resource may not yet be ready)` for hours

**Root cause**: `managementPolicies` excludes `LateInitialize` on NATGateway, so the provider never backfills the ID field that `natGatewayIdSelector` needs.

**Fix**: Use composite field patching (`ToCompositeFieldPath` from NATGateway status → `FromCompositeFieldPath` to Route) with `policy.fromFieldPath: Required`.

## Spoke Cluster Stuck Deletion / Recovery

**Symptoms**: A spoke is stuck and won't finish deleting OR won't re-provision:
- `EksclusterWithVpc` (KRO) stuck `state=DELETING` for a long time with finalizers
  `["kro.run/finalizer","foregroundDeletion"]`, even though the EKS cluster and
  child resources are already gone.
- A re-created instance is blocked with `... node "vpc" is currently being deleted;
  waiting for deletion to complete`.
- The child ACK VPC CR (`vpcs.ec2.services.k8s.aws`) stuck deleting with a frozen
  `ACK.Recoverable: DependencyViolation: The vpc '...' has dependencies and cannot
  be deleted` (ACK is an EKS Capability — it backs off and stops re-reconciling, and
  cannot be restarted).
- New VPC creation fails with `VpcLimitExceeded: The maximum number of VPCs has
  been reached` (the orphaned VPC is consuming a slot).

**Root cause**: An empty/transient generation removed a cluster's Application while
its template still carried `resources-finalizer.argocd.argoproj.io`, which cascade
-deleted the live cluster. Mid-teardown, the KRO/ACK finalizers froze, leaving
tombstone CRs and an orphaned VPC. (The cluster appsets are now hardened — see
`cluster-lifecycle.md` — so this should not recur; this runbook is for clearing an
already-stuck state.)

**Recovery** (only force-remove a finalizer once the underlying resources are
confirmed gone — i.e. it is a tombstone):

```bash
NS=<cluster>            # e.g. peeks-spoke-prod (namespace == cluster name)
R=us-west-2

# 1. Confirm the tombstone: children gone, namespace empty, EKS already deleted
kubectl get eksclusterwithvpcs.kro.run $NS -n $NS \
  -o jsonpath='{.metadata.deletionTimestamp} {.metadata.finalizers} {.status.state}{"\n"}'
kubectl get all -n $NS                                  # expect: no resources
aws eks describe-cluster --name $NS --region $R         # expect: not found

# 2. Clear the stuck EksclusterWithVpc tombstone. The clusters-kro app (hardened,
#    no finalizer) then re-creates a fresh instance and provisioning restarts.
kubectl patch eksclusterwithvpcs.kro.run $NS -n $NS \
  --type merge -p '{"metadata":{"finalizers":[]}}'

# 3. If a child ACK VPC CR is still a frozen tombstone, verify the VPC truly has no
#    deps, then clear its finalizer so KRO can proceed.
VPC=<vpc-id-from-the-stuck-cr>
for q in subnets network-interfaces nat-gateways internet-gateways; do
  aws ec2 describe-$q --region $R --filters Name=vpc-id,Values=$VPC --output text; done
kubectl patch vpcs.ec2.services.k8s.aws ${NS}-vpc -n $NS \
  --type merge -p '{"metadata":{"finalizers":[]}}'

# 4. If the new provision then fails with VpcLimitExceeded, the orphaned VPC is
#    holding a slot. CONFIRM the new ACK VPC CR is creating a NEW vpc (its
#    .status.vpcID differs from the orphan — i.e. it is NOT adopting the orphan),
#    then delete the orphan by its specific ID.
kubectl get vpcs.ec2.services.k8s.aws ${NS}-vpc -n $NS -o jsonpath='{.status.vpcID}{"\n"}'
aws ec2 describe-vpcs --region $R --query "Vpcs[].{Id:VpcId,CIDR:CidrBlock,Name:Tags[?Key=='Name']|[0].Value}" --output table
for rt in $(aws ec2 describe-route-tables --region $R --filters Name=vpc-id,Values=$VPC \
    --query "RouteTables[?Associations[0].Main!=\`true\`].RouteTableId" --output text); do
  aws ec2 delete-route-table --region $R --route-table-id $rt; done
aws ec2 delete-vpc --region $R --vpc-id $VPC

# 5. Verify recovery: a NEW VPC + subnets get created and the instance progresses.
kubectl get vpcs.ec2.services.k8s.aws ${NS}-vpc -n $NS -o jsonpath='{.status.vpcID} {.status.conditions[?(@.type=="ACK.ResourceSynced")].status}{"\n"}'
kubectl get eksclusterwithvpcs.kro.run $NS -n $NS -o jsonpath='{.status.state}{"\n"}'
aws eks describe-cluster --name $NS --region $R --query "cluster.status"   # eventually ACTIVE
```

**Safety**:
- Only patch out finalizers on a confirmed tombstone (resources already gone). It is
  irreversible and orphans anything not yet cleaned.
- Before deleting an orphaned VPC, confirm ACK is creating a **new** VPC (different
  `status.vpcID`) and delete only the orphan **by ID** — same Name tag/CIDR as the
  new one means tag/CIDR-based deletes are dangerous.
- Crossplane spokes (`clusters-<tenant>`) follow the same pattern via their claim and
  Crossplane-managed VPC (`vpcs.ec2.aws.upbound.io`).
