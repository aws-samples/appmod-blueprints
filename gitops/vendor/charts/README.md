# Vendored charts

Last-resort fallback used by `cluster-providers/common/scripts/install-eso.sh`
when both the Helm repo and OCI are unreachable. Each `*.tgz` has a sibling `*.tgz.sha256`
(sha256sum format); the script refuses a chart whose hash differs or whose `.sha256` is missing.

Scope: the vendored chart covers the github.com release-CDN 504 (chart download only). Its images
still come from `ghcr.io/external-secrets/external-secrets`, so it does not cover a ghcr.io outage.

## external-secrets-2.4.1.tgz

- Version: pinned to `gitops/addons/registry/core.yaml` `external-secrets.defaultVersion` (a test enforces it).
- Provenance: `helm pull oci://ghcr.io/external-secrets/charts/external-secrets --version 2.4.1`
  (OCI digest `sha256:dc8d9f0139d8d606e198e947a8d9db089f820065f7f56cd4064d327ddf080d7c`);
  same content as the chart served by the Helm repo `https://charts.external-secrets.io`.
- File sha256: `d432db5dd4935cc8032f6fbc1c3f33b4baaa08db2be76de41e6cf3ea651fe574`.

## Updating

```
helm pull oci://ghcr.io/external-secrets/charts/external-secrets --version <v> -d gitops/vendor/charts
(cd gitops/vendor/charts && sha256sum external-secrets-<v>.tgz > external-secrets-<v>.tgz.sha256)
```

Remove the old `.tgz` and `.sha256`, and update the digest above. `.gitignore` re-includes
`gitops/vendor/charts/*.tgz` after the global `*.tgz`; check the new file is not ignored before
committing: `git check-ignore --no-index gitops/vendor/charts/external-secrets-<v>.tgz` must print nothing.
