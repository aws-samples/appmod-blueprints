# Workshop fleet-config overlay

This folder holds workshop-specific overrides that are seeded into the `fleet-config`
repo (GitLab, in the workshop) by `workshop/Taskfile.yaml`, alongside `gitops/fleet/`.

Unlike `gitops/fleet/` (which lives under `gitops/fleet/` inside fleet-config —
fleet topology: spoke clusters, membership), this folder is copied to the **root**
of fleet-config, because `overlay_repo_basepath=""` (set by `set-overlay-repo`) and
the `cluster-addons` ApplicationSet's `$overlay` source resolves value files at
`overlays/environments/<env>/overrides.yaml` and `overlays/clusters/<cluster>/overrides.yaml`
relative to that basepath (see `gitops/bootstrap/addons.yaml`).

## Why this exists

The generic solution (`gitops/overlays/environments/<env>/overrides.yaml`) must stay
free of workshop-specific choices (e.g. always exposing Kargo over an ALB in HTTP
mode). Any consumer of the solution — including the workshop — customizes addon
values for their own environment by providing an `overrides.yaml` in their own
fleet-config repo. This folder is the workshop's version of that customization,
version-controlled here and pushed to GitLab's fleet-config at bootstrap time.

## Structure

```
overlay/
└── overlays/
    └── environments/
        └── control-plane/
            └── overrides.yaml   # e.g. enables Kargo's ALB ingress, HTTP/HTTPS
                                  # picked based on the insecure annotation
```

This mirrors the path structure expected by the `$overlay` ApplicationSet source —
whatever is under `overlay/` here lands at the fleet-config repo root.
