# Resume note — multi-cluster auth + Pod Identity + config-driven topology brainstorm

_Untracked scratch file (.local/). Not part of any PR. For resuming after context compaction._

## Repos & branches
- **appmod-blueprints** (platform / `addonsRepo`): branch `feature/agent-platform-shapirov`, latest pushed commit `da57b60d`. PR **#756** open → base `feature/agent-platform`. The live hub tracks this branch directly (addonsRepoRevision), so pushes apply via GitOps without merging.
- **open-agentic-platform / sample-agent-platform-on-eks** (consumer / `fleetRepo`): branch `feature/oam-for-agents`. Carries fleet-member `client_provisioner` label, langfuse keycloak-clients path fix, agentcore self-provision refactor. Companion changes; would need its own PR.
- Live clusters: `peeks-hub` (hub), `spoke-dev`, `spoke-prod` (kube contexts set up with those aliases). Hub ArgoCD is the EKS managed Capability (argocd ns has no pods by design).

## What's DONE and verified (PR #756)
1. **Multi-cluster OIDC auth** design docs (MULTI_CLUSTER_AUTH.md, CONSUMER_GUIDE, HUB_NETWORKING.md). Uses platform's existing `environment` label (not `env`).
2. **fleet-secret chart**: derives `oidc_issuer_url` in-template from `oidc.issuerUrlTemplate` = `https://{domain}/keycloak/realms/{realm}`; `oidc_insecure_origin` (D7). Realm defaults to **`platform`**, customizable via `oidc.realm`.
3. **keycloak-client-provisioner chart** (`platform-charts/`): PostSync Job creates realm+clients in Keycloak, writes contract to Secrets Manager `<prefix>/<environment>/oidc/<client>`. Self-provisions its own IAM Role + PodIdentityAssociation. Realm default `platform`, customizable (`realmName`). jq bootstrapped in the aws-cli image. clients normalized (list or JSON string via fromJsonArray). Chart version 0.1.2 (user chose to keep).
4. **client-provisioner ApplicationSet** (`gitops/bootstrap/client-provisioner.yaml`): matrix hub×spoke-fleet-members; routes to `platform-charts/<client_provisioner>-client-provisioner`; passes environment/region/clusterName/keycloakUrl/secretPathPrefix/realmName + generic `clients` passthrough. Realm default `platform`.
5. **Pod Identity consistency model** (the big fix):
   - Root cause fixed: composition cel-filter removed ALL `addon-*` (incl. `eks-pod-identity-agent`) when no managed node group → Auto Mode spokes had NO pod identity. Narrowed filter to only gate vpc-cni/kube-proxy/coredns. `eks-pod-identity-agent` now ACTIVE on spokes.
   - One rule: hub bootstraps ONLY spoke `provider-aws-iam` + `provider-aws-eks` (+ eso) via `overlays/environments/{dev,prod}/pod-identities/values.yaml`. Everything else self-provisions its own Role+PodIdentityAssociation (crossplane-base for ec2/amp/grafana; workload charts for theirs), reconciled by the credentialed spoke iam/eks providers.
   - Reverted agentcore hub-overlay workaround → agentcore self-provisions (createViaChart gate removed).
   - Dropped redundant `argocd`-namespace RBAC in crossplane-base (provider-kubernetes:system ClusterRole already grants secrets:* cluster-wide). Removed the `createArgoCDRBAC` flag + control-plane override.
   - keycloak-client-provisioner self-provisions (templates/pod-identity.yaml), removed from control-plane overlay.
6. **Steering**: added "Working Agreement" to `.kiro/steering/project.md` (verify-don't-speculate, no sleep, solutions-in-git, question-necessity, consistency, customer-neutral). Plus existing Operational Invariants (managed ArgoCD, Pod Identity not IRSA, EKS ARN cluster secrets).
7. PR #756 has a comment explaining pod-identities ↔ fleet members ↔ overlays wiring.

## Realm decision (settled)
- **Option A**: default to the shared `platform` realm (where keycloak config Job provisions users/groups/roles/mappers). Customizable per hub/spoke via fleet-member `oidc.realm` → flows to both provisioner `realmName` and fleet-secret issuer. Verified: default `realms/platform`, override `realms/acme-corp`.
- Per-env realms (original design idea) abandoned — would require replicating realm config per env.

## Live state confirmed
- spoke-dev `oidc_issuer_url` = `https://peeks.dev.shapirov.people.a2z.com/keycloak/realms/platform` (after refresh).
- client-provisioner-spoke-{dev,prod}: realmName=platform, clients=[] (no OAP client declared yet). Provisioner Jobs created `dev`/`prod` realms, no-op on empty clients.
- crossplane-base + crossplane-agentcore: Synced/Healthy; AgentCore memory/browser/code-interpreter READY.

## Deferred / owned elsewhere
- **bifrost** spoke rework (StatefulSet→postgres) — owned by a DIFFERENT agent session in OAP. I made NO bifrost chart changes. Only shared fix benefiting it: spoke eks provider now credentialed. Live `bifrost-secrets` ExternalSecret reading `spoke-prod/bifrost` is a leftover from old chart (current chart has no ES); hub bifrost works without it.
- **langfuse** spoke keycloak-clients path + empty `peeks-hub/keycloak-clients` SecretString (stored as SecretBinary) — deferred.
- **grafana-dashboards** AMG datasource "NO MATCHING INSTANCES" — deferred (AMG connectivity, not pod identity).
- **agentgateway client** creation waits for OAP to declare it in a fleet member `clients:` list. Realm mismatch resolved (default platform). **Open**: hub has no fleet member, so a hub-resident agent gets no provisioned client — architectural decision pending.

## ACTIVE BRAINSTORM (no changes yet) — consumer-driven topology via config file

**Goal:** consumer provides a `config.local.yaml` describing control plane + spokes with ARBITRARY names. Platform must not hardcode env names like `dev`/`prod`.

**Key finding that motivated this:** pod-identities overlays are read from the PLATFORM repo (appmod, `$values` ref = addonsRepo), but the `environment` name is declared by the CONSUMER (OAP fleet members). So the platform hardcodes consumer env names via `overlays/environments/<env>/` directories. The `dev`/`prod` pod-identities overlays are byte-for-byte identical (eso+iam+eks) — "spoke bootstrap" duplicated under two hardcoded names, not real per-env config.

**Existing patterns to build on:**
- `hub-config.yaml` + local override already exists (Taskfile reads CONFIG_FILE via yq) — extend hub→spokes.
- appset value layering already: `configs/<addon>` (base) → `overlays/environments/<env>` → `overlays/clusters/<clusterName>`. The per-CLUSTER layer is ALREADY name-agnostic. Only the per-ENVIRONMENT layer hardcodes names.
- Spokes currently defined in 3 scattered places: `kro-values/tenants/<tenant>/kro-clusters/values.yaml` (CIDR/version/autoMode), `fleet/members/<spoke>/values.yaml` (labels), `overlays/environments/<env>/` (addon config). Config file would collapse these.

**Proposed model (the shape):**
```yaml
# config.local.yaml — consumer-owned, arbitrary names
hub:
  name: acme-control
  region: us-west-2
  domain: platform.acme.com
  vpcCidr: 10.0.0.0/16
resourcePrefix: acme          # AWS resource scoping only (collision avoidance)
spokes:
  - name: mydev
    profile: standard         # references platform-provided template
    region: us-west-2
    vpcCidr: 10.1.0.0/16
  - name: myprod
    profile: production       # bigger compute, licensed, stricter
    region: us-west-2
    vpcCidr: 10.2.0.0/16
    overrides:
      addons:
        some-commercial-thing: true
```

**Core idea: PROFILES (templates), not hardcoded env names.**
- Platform ships a small, opinionated set of name-agnostic spoke profiles: `standard` (modest, OSS), `production` (bigger, HA, licensed, stricter).
- Consumer assigns a profile to each arbitrarily-named spoke. Many spokes share one profile.
- `overrides:` handles per-spoke long tail.
- Layering maps onto existing 3-layer merge: platform base (universal) → profile/template (≈ rename of `overlays/environments/<env>` to `profiles/<profile>`) → per-spoke overrides (from consumer config, via the already-name-agnostic per-cluster layer).
- "prod is genuinely different" handled by the `production` PROFILE, not a hardcoded `prod` dir.

**Ownership split:**
- Consumer: names, topology, regions/CIDRs, profile selection, per-spoke overrides.
- Platform: mechanism (appsets/charts/layering), universal spoke bootstrap (iam/eks/eso, keyed on is-a-spoke NOT env name), profile templates, the hub's own config.
- `dev`/`prod` dirs stop being load-bearing; become example values.

**Open questions (to decide next):**
1. What turns `config.local.yaml` into fleet members/kro-values/overlays? Taskfile generator (extends yq pattern) vs Kro RGD vs bootstrap script. Generate-and-commit (git source of truth, auditable) vs generate-at-apply (less commit, more magic).
2. Profiles: how many, how rigid? Lean = couple of opinionated profiles + free-form override. Avoid profile sprawl.
3. What do appsets key on once env names are arbitrary? Likely `profile` label + name-agnostic per-cluster layer + universal bootstrap keyed on hub-vs-spoke.
4. Can profiles swap WHAT is deployed (chart versions/images for licensed/commercial), not just how much?
5. Migration: current `dev`/`prod` → `profile: standard`/`production` with names `spoke-dev`/`spoke-prod`. Translates cleanly, de-risks.

**Caution:** keep profile set small and opinionated. Value = "consumer says one word, gets a sensible environment," NOT "consumer rebuilds Helm values in a new dialect."

**Two branches most affecting cleanliness:** (Q1) the generator mechanism, (Q3) appset re-keying away from env-name.

## Next step on resume
Decide Q1 (generator mechanism) and Q3 (appset re-keying) before any implementation. Nothing to implement until the topology/config model is shaped.
