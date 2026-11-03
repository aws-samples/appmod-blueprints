# EKS cluster RGDs (`EksCluster`, `EksclusterWithVpc`)

## Day-2: editing a spoke's values does not reach Secrets Manager on its own

A spoke's cluster registration flows through these steps:

1. kro renders the data Secret `<cluster>/<cluster>-config-data` (`clusterConfigK8sSecretFleet` in `rg-eks.yaml`).
2. The ACK Secrets Manager `Secret` `<cluster>/<cluster>-config` (`clusterConfigSecretFleet`) pushes it to SM `<cluster>/config`.
3. The fleet-secret ExternalSecret turns it into the Argo CD cluster secret.

The ACK CR only *references* the data Secret (`spec.secretString` = name/key). When you change a spoke's values after creation, for example the `gitops:` block of a cluster in the fleet-config `kro-clusters/values.yaml`, kro updates the data Secret but the ACK CR spec does not change. ACK then never pushes the new content, and SM, the ExternalSecret and the cluster secret stay stale. Annotations, `services.k8s.aws/force-resync` included, do not help. A first install is not affected.

After the data Secret has picked up the change, bump the ACK CR spec once, then force the ExternalSecret:

```bash
C=<spoke-cluster-name>
# 1. confirm kro re-rendered the data Secret (look at the managedFields time)
kubectl -n $C get secret $C-config-data --show-managed-fields \
  -o jsonpath='{range .metadata.managedFields[*]}{.manager} {.time}{"\n"}{end}'
# 2. change the ACK CR spec: generation +1, ACK calls UpdateSecret with the resolved secretString
kubectl -n $C patch secrets.secretsmanager.services.k8s.aws $C-config --type merge \
  -p "{\"spec\":{\"description\":\"$C cluster config $(date -u +%Y%m%dT%H%M%SZ)\"}}"
kubectl -n $C get secrets.secretsmanager.services.k8s.aws $C-config \
  -o jsonpath='{.metadata.generation} {.status.conditions[?(@.type=="ACK.ResourceSynced")].status}{"\n"}'
# 3. refresh the ExternalSecret that builds the Argo CD cluster secret
kubectl -n argocd annotate externalsecret fleet-secret-$C force-sync=$(date +%s) --overwrite
```

Only do this for **spokes** (`fleetMember != control-plane`). Never do it for the hub's own `<hub>-config` CR on a pivoted hub. The installer enriches SM `<hub>/config` out of band (overlay repo, OAP revision, NAT CIDRs, Argo CD URL...), and an ACK push from the kro data Secret would wipe those keys.

Why this is not automatic: carrying a change marker in the ACK CR spec would also bump the hub's CR once at rollout, with the effect above. The clean conditional form (`omit()` on the hub) needs kro's `CELOmitFunction` feature gate, and the EKS managed kro capability (0.9.4-eks-2) does not enable it.
