# fleet-config

This is **your** GitOps configuration repository (the *overlay*) for a platform built on
Amazon EKS. It is where you enable, configure, and tune platform add-ons and declare the
clusters in your fleet — **without forking or maintaining the platform itself**.

The platform engine (add-on catalog, Helm charts, ApplicationSets, cluster blueprints) is
maintained upstream by **AWS Solutions Architects** in the public GitHub repository
[`aws-samples/appmod-blueprints`](https://github.com/aws-samples/appmod-blueprints). You
consume it directly over Git and keep your customizations here, in this overlay.

> This README is seeded from the platform source
> (`platform/fleet-config/README.md` in `aws-samples/appmod-blueprints`). Edit it there,
> not in this repo — the seeding job overwrites it.

---

## How it works: upstream base + your overlay

Argo CD assembles every add-on and cluster from **two layered sources**:

| Source | Repository | Owner | What it provides |
|--------|-----------|-------|------------------|
| `defaults` (base) | `aws-samples/appmod-blueprints` | AWS Solutions Architects | The add-on **registry** (catalog), the Helm **charts**, default versions, and the ApplicationSets that deploy them |
| `overlay` | **this repo** (`fleet-config`) | **You** | Your overrides: which add-ons to enable, version pins, per-environment / per-cluster values, and your cluster definitions |

Values are merged with **the overlay winning over the base**:

```
base defaults  →  base env/cluster overrides  →  overlay env/cluster overrides (this repo)
                                                  ▲ highest precedence
```

Because the base is referenced directly over Git, you get upstream fixes and new add-ons
automatically — there is **no fork to rebase**. You only ever edit this overlay.

> Override files are optional. Argo CD is configured with `ignoreMissingValueFiles: true`,
> so you add a file only when you actually need to change something.

---

## Add-ons

Each add-on is declared once in the upstream **registry**
(`gitops/addons/registry/*.yaml` in the base repo) with its Helm chart, a default version,
and baseline values. You do not edit the registry — you layer values on top from this repo.

### Where to put overrides (this repo)

```
configs/<addon>/values.yaml                          # applies to ALL clusters
overlays/environments/<env>/<addon>/values.yaml      # all clusters in an environment (e.g. dev, prod)
overlays/clusters/<clusterName>/<addon>/values.yaml  # a single cluster
```

`<addon>` is the add-on name from the registry (for example `aws-load-balancer-controller`,
`external-dns`, `kyverno`). `<env>` matches a cluster's `environment` label.

### Common tasks

- **Enable / disable an add-on** — set the matching `enable_<addon>` flag on the target
  cluster (via the cluster definition under `gitops/fleet/`, see below). The registry
  add-on entry is gated on that label.
- **Pin or change a chart version** — set the version for that add-on in the appropriate
  `configs/` or `overlays/.../<addon>/values.yaml` file.
- **Change add-on values** — add the Helm values you want under the same `<addon>/values.yaml`
  file at the scope (global / environment / cluster) you need.

---

## Hub and spoke clusters

The platform is a **hub-and-spoke** fleet, all driven from one control plane:

- **Hub (control plane)** — the management cluster. It runs Argo CD and the orchestrating
  ApplicationSets that read this overlay and reconcile every cluster. It is labeled
  `fleet_member: control-plane`, `tenant: control-plane`. The `control-plane` value is
  reserved for the hub.
- **Spokes (workload clusters)** — provisioned and managed *from the hub*. They are labeled
  `fleet_member: spoke` and grouped by `tenant` (e.g. `workshop`) and `environment`
  (e.g. `dev`, `prod`). Spokes inherit the same add-on catalog and this same overlay;
  you differentiate them with the environment / cluster override files above.

The hub provisions spokes through one of two cluster blueprints (both consume this overlay):

- **kro** — `EksclusterWithVpc` instances. Cluster definitions live under
  `gitops/fleet/spoke-values/tenants/<tenant>/kro-clusters/`.
- **Crossplane** — composite cluster claims (`XPlatformCluster`). Cluster definitions live
  under `gitops/fleet/spoke-values/tenants/<tenant>/crossplane-clusters/`.

### How spokes are enabled

You normally enable a spoke with the workshop `task` commands (these run as part of
`task install`). **The tasks only commit cluster values into this overlay repo — the hub
does all the actual provisioning** by reconciling what you commit here:

- **`task spokes:enable-crossplane -- <cluster>`**
  Commits Crossplane cluster values to
  `gitops/fleet/spoke-values/tenants/<tenant>/crossplane-clusters/values.yaml`.
  The hub's Argo CD then renders the `XPlatformCluster` claim → the hub's **Crossplane**
  reconciles the spoke (VPC + EKS infra), and the capabilities Job runs **on the hub**.
  (This is how `spoke-dev` is created.)

- **`task spokes:enable-kro -- <cluster>`**
  Commits KRO cluster values
  (`gitops/fleet/spoke-values/tenants/<tenant>/kro-clusters/clusters/<cluster>.json` and
  `.../kro-clusters/values.yaml`) **plus the multi-acct CARM mapping**
  (`configs/multi-acct/values.yaml`, mapping the spoke's namespace → AWS account).
  The hub's **KRO + ACK** controllers then provision the spoke, assuming the
  `<prefix>-cluster-mgmt-<svc>` roles per the CARM mapping. (This is how `spoke-prod` is
  created. The CARM mapping is KRO-only — Crossplane spokes don't use it.)

Both tasks are idempotent (they keep an already-enabled spoke's existing VPC CIDR) and end
by committing/pushing to this repo. From there it is pure GitOps: the hub detects the new
values, provisions and registers the cluster, and rolls out the enabled add-ons.

You can also do this by hand: add/edit the same files under
`gitops/fleet/spoke-values/...` (and optionally per-cluster add-on values under
`overlays/clusters/<clusterName>/`), then commit and push.

---

## Repository layout

```
fleet-config/
├── configs/
│   ├── <addon>/values.yaml      # global per-add-on value overrides            (optional)
│   └── multi-acct/values.yaml   # ACK CARM namespace → AWS account map (KRO spokes)
├── overlays/
│   ├── environments/<env>/<addon>/values.yaml   # per-environment add-on values (optional)
│   └── clusters/<cluster>/<addon>/values.yaml   # per-cluster add-on values      (optional)
├── gitops/
│   └── fleet/spoke-values/tenants/<tenant>/
│       ├── crossplane-clusters/values.yaml      # Crossplane spoke definitions
│       └── kro-clusters/
│           ├── clusters/<cluster>.json          # KRO spoke (one file per cluster)
│           └── values.yaml                      # KRO spoke definitions
└── platform/
    └── backstage/templates/     # Backstage software templates (self-service scaffolding)
```

> Note the two roots: add-on overrides (`configs/`, `overlays/`) sit at the repo root, while
> cluster definitions live under `gitops/fleet/...`. This matches how the platform's
> ApplicationSets resolve overlay paths.

---

## Workflow

1. Edit the relevant override or cluster-definition file in this repository.
2. Commit and push to the branch this overlay is wired to (the hub's Argo CD tracks it).
3. Argo CD detects the change and reconciles the affected clusters and add-ons.

Prefer changing Git and letting Argo CD sync over applying anything by hand — this repo is
the source of truth for your fleet's configuration.
