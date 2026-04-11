# Bring Your Own Cluster

Use this approach when you already have a Kubernetes cluster with ArgoCD installed.

## Prerequisites

- A running Kubernetes cluster (EKS, AKS, GKE, on-prem, etc.)
- ArgoCD installed and accessible
- `kubectl` configured to access the cluster
- `helm` 3.x installed

## Quick Start

### 1. Create the hub cluster secret

ArgoCD needs a cluster secret that identifies the hub and carries the annotations
the addon management system uses. Apply this to your cluster:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
type: Opaque
metadata:
  name: hub
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    environment: control-plane
    fleet_member: control-plane
    tenant: control-plane
  annotations:
    addonsRepoURL: "https://github.com/YOUR_ORG/YOUR_REPO.git"
    addonsRepoRevision: "main"
    addonsRepoBasepath: "gitops/"
    fleetRepoURL: "https://github.com/YOUR_ORG/YOUR_REPO.git"
    fleetRepoRevision: "main"
    fleetRepoBasepath: "gitops/"
stringData:
  name: hub
  server: https://kubernetes.default.svc
  config: '{"tlsClientConfig":{"insecure":false}}'
EOF
```

Replace `YOUR_ORG/YOUR_REPO` with your actual git repository.

### 2. Apply the root ApplicationSet

```bash
kubectl apply -f gitops/bootstrap/root-appset.yaml
```

This discovers the other bootstrap files (`addons.yaml`, `fleet-secrets.yaml`, `clusters.yaml`)
and the entire addon pipeline starts automatically.

### 3. Verify

```bash
kubectl -n argocd get applicationsets
kubectl -n argocd get applications
```

You should see `cluster-addons`, `fleet-secrets`, and `clusters` ApplicationSets,
and Applications being created for each enabled addon.

## What happens next

1. `fleet-secrets` reads `fleet/members/hub/values.yaml` + `overlays/environments/control-plane/enabled-addons.yaml`
2. The fleet-secret chart generates a new cluster secret with `enable_*` labels
3. `cluster-addons` renders the appset-chart with registry domain files
4. ApplicationSets match the `enable_*` labels and create Applications per addon
5. ArgoCD syncs each addon to the hub cluster

## Customization

- Edit `overlays/environments/control-plane/enabled-addons.yaml` to enable/disable addons
- Edit `fleet/members/hub/values.yaml` to change cluster annotations
- Edit `addons/registry/*.yaml` to add/modify addon definitions
- Add environment overlays in `overlays/environments/<env>/`
