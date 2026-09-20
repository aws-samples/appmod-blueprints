# Backstage (CNOE-based)

This directory contains a thin overlay on top of the [CNOE backstage-app](https://github.com/cnoe-io/backstage-app) image.

## Customizations

The `patches/cnoe-customizations.patch` applies the following changes:

1. **`/backstage` sub-path** — Sets `app.baseUrl` and `backend.baseUrl` to include `/backstage` so the app works behind an ingress path prefix.

2. **GitLab scaffolder module** — Adds `@backstage/plugin-scaffolder-backend-module-gitlab` for `publish:gitlab` and `publish:gitlab:merge-request` actions.

3. **`kube:apply` action** — Registers a `kube:apply` alias for `cnoe:kubernetes:apply` that:
   - Accepts `manifest` as an input field (in addition to `manifestString`/`manifestObject`/`manifestPath`)
   - Falls back to in-cluster `kubectl apply` when no `clusterName` is specified

## Building

```bash
docker build -t <your-ecr-repo>:latest backstage/
```

## Upstream contribution

These patches are transitional. The goal is to contribute them upstream to [cnoe-io/backstage-app](https://github.com/cnoe-io/backstage-app) so this overlay becomes unnecessary.
