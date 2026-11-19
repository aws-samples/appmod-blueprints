# Design: Record DORA deployments from Argo Rollouts via SQS

Status: Proposed
Scope: `devlake` chart (queues + consumer), `argo-rollouts` addon, `crossplane-pod-identity` (argo-rollouts identity), `cicd-pipeline` RGD (removals only)

## Problem

Today a GitLab push submits `<name>-dora-deployment-workflow` (`doradeploy` in
`gitops/addons/charts/kro/resource-groups/manifests/cicd-pipeline/cicd-pipeline.yaml`), which:

- logs into the dev or prod spoke (`aws eks update-kubeconfig`) and polls the Rollout for up to 20 minutes, matching on image tag;
- for prod pushes, reads `deployment/prod/*.yaml` through the GitLab API to find the deployed tag (`resolve-deployed-tag`);
- needs `eks:DescribeCluster`, an `AmazonEKSClusterAdminPolicy` access entry on the dev spoke (`accessentry`), and an `AmazonEKSAdminViewPolicy` access entry on prod (`prodaccessentry`);
- only records deployments that start with a push. Rollbacks, re-promotes and aborts that don't come from a push are missed, and a rollout that waits more than 20 minutes is never recorded.

The measuring-platform-success blog (`containers-blog-maelstrom/measuring-platform-success-blog`) records deployments with Argo Rollouts notifications instead. That approach can't post to DevLake directly here: DevLake runs on the hub and the Rollouts run on the spokes, and making DevLake reachable from the spokes would be a new network exposure.

### Alternatives rejected

| Option | Why not |
|---|---|
| Rollouts `webhook` → DevLake | DevLake would need to be reachable across clusters (new exposure). |
| Argo CD notifications (EKS Capability) | The capability has no `webhook` service, and any URL must be public `https`. It supports `awssqs` and `eventbridge`, but its health is per Application, its logs are off by default, and the capability role is managed outside this repo. |
| SNS | Rollouts notifications have no SNS service (`Publish` needs SigV4). SNS pushes to a public endpoint, so it would still need an SQS queue to deliver privately. Revisit only for fan-out, and do the fan-out on the hub Sensor instead. |
| Per-app queues created by `cicd-pipeline` | Every pipeline would carry 2 queues, an IAM policy, role, SA, pod identity association and EventSource. The spoke IAM would need a wildcard per cluster. It also doesn't fit the DevLake chart owning the queues. Its only advantage, per-app isolation, is weak: a spoke's role could write every app's queue on its cluster anyway. |

## Design

```
spoke (dev|prod)                            hub, devlake namespace (devlake chart)
Rollout ─ Healthy / Degraded ─┐
argo-rollouts notifications ──┴─awssqs──▶ SQS <prefix>-dora-<spoke cluster>   (one per environment)
  (default subscription: every Rollout)        │ long-poll (pod identity, SQS read only)
                                     EventSource devlake-dora-sqs (one source per queue)
                                               │
                                     Sensor: SHA-tagged image in a team-* namespace;
                                             environment = which queue it came from
                                               │
                                     WorkflowTemplate dora-record-deployment:
                                       app = namespace minus "team-"
                                       check image is <acct>.dkr.ecr.<region>.amazonaws.com/<prefix>/<app>:<sha>
                                       POST devlake-lake:8080/plugins/webhook/connections/by-name/<app>_webhook/deployments
```

Principles:

- The spoke sends a **plain rollout event that knows nothing about DevLake**. All DevLake details (IDs, repo URL, payload shape, routing to the app's connection) stay on the hub.
- **One queue per environment, shared by all apps.** All apps already land in the same DevLake instance and database, so one consumer routes each event to the app's existing webhook connection by name. `cicd-pipeline` gains no new resources.
- **The environment comes from the queue, not from the sender.** Each spoke's argo-rollouts role can send only to its own cluster's queue (an exact ARN, no wildcard), so a dev spoke can't produce PRODUCTION records.
- **Apps without a pipeline are dropped on the hub.** When `<app>_webhook` doesn't exist, the consumer logs and skips, so spokes need no per-app opt-in.
- DevLake stays private. The hub pulls from SQS, so nothing is exposed.

### DevLake API support (checked against the source)

- `v1.0.3-beta14` (`backend/plugins/webhook/impl/impl.go`) registers:
  - `connections/by-name/:connectionName/deployments`;
  - `connections/by-name/:connectionName/pull_requests`;
  - `connections/by-name/:connectionName/issues`;
  - the existing `connections/:connectionId/…` routes, so the `dorapullrequest` and `doraincident` workflows keep working unchanged.
- `v1.0.3-beta7`, the version in use today, already has the same `by-name` routes, so this doesn't depend on the upgrade.
- beta14 also adds `projects/:projectName/deployments`. Don't use it: it finds or creates a separate connection named `<project>_deployments`. Deployments would land in a different connection from the PRs and incidents in `<app>_webhook`.
- **Auth:** beta14 adds an auth chain to the lake API (`RestAuthentication` for `/rest/*`, a push-key gate for `/push/*`, OIDC, then `RequireAuth`). `RequireAuth` is a no-op unless `AUTH_ENABLED=true`, and `AUTH_ENABLED` defaults to false (`helpers/oidchelper/config.go`). Calls to `devlake-lake:8080/plugins/...` without a key keep working, as the setup workflow already relies on.
  - If `AUTH_ENABLED` is ever turned on, the consumer must call `/rest/plugins/webhook/connections/by-name/...` with an API key whose allowed path covers `/plugins/webhook/.*`.

### Event schema (spoke → SQS)

```json
{
  "result": "SUCCESS | FAILURE",
  "app": "<rollout name>",
  "namespace": "team-<app>",
  "image": "<ecr-repo-uri>:<40-hex sha>",
  "revision": "<rollout.argoproj.io/revision annotation>",
  "podHash": "<rollout.status.currentPodHash>",
  "finishedAt": "2026-11-17T20:00:00Z"
}
```

There's no `environment` field: the hub sets it from the queue. `revision` identifies the rollout; `podHash` is for debugging only.

### Why `oncePer` uses the revision, not the pod hash

notifications-engine never clears an `oncePer` entry when the condition goes false (`pkg/controller/state.go`). It keeps up to 100 entries (`notifiedHistoryMaxSize`), keyed by the `oncePer` value. Keying on `currentPodHash` would therefore drop rollbacks: rolling back to a revision that was Healthy before brings back a pod hash that already has an entry, so no SUCCESS is sent.

`rollout.argoproj.io/revision` on the Rollout increments on every rollout, including a rollback to an older ReplicaSet. Keying both `oncePer` and the DevLake record `id` on it records every rollout once, and a rollback gets its own record instead of overwriting an earlier one.

## Changes

### 1. Spoke: `argo-rollouts` addon

Triggers and templates go in `gitops/addons/configs/argo-rollouts/values.yaml`. This is a plain Helm values file; the ApplicationSet doesn't template it, so Go `{{ }}` templates pass through safely. Nothing in it is specific to a cluster or environment:

```yaml
notifications:
  triggers:
    trigger.on-dora-success: |
      - when: rollout.status.phase == 'Healthy'
        oncePer: rollout.metadata.annotations['rollout.argoproj.io/revision']
        send: [dora-event-success]
    trigger.on-dora-failure: |
      - when: rollout.status.phase == 'Degraded' || rollout.status.abort == true
        oncePer: rollout.metadata.annotations['rollout.argoproj.io/revision']
        send: [dora-event-failure]
  templates:
    template.dora-event-success: |
      message: |
        {"result":"SUCCESS",
         "app":"{{.rollout.metadata.name}}",
         "namespace":"{{.rollout.metadata.namespace}}",
         "image":"{{(index .rollout.spec.template.spec.containers 0).image}}",
         "revision":"{{index .rollout.metadata.annotations "rollout.argoproj.io/revision"}}",
         "podHash":"{{.rollout.status.currentPodHash}}",
         "finishedAt":"{{dateInZone "2006-01-02T15:04:05Z" now "UTC"}}"}
    template.dora-event-failure: |
      # identical, with "result":"FAILURE"
```

The parts that differ per cluster go in the registry's `valuesObject` (`gitops/addons/registry/gitops.yaml`, next to the existing `serviceAccount` annotation), which is templated per cluster. That covers the `service.awssqs` notifier and a **default subscription** that sends every Rollout's events to this cluster's queue:

```yaml
  valuesObject:
    notifications:
      notifiers:
        service.awssqs: |
          region: '{{.metadata.annotations.aws_region}}'
        subscriptions: |
          - recipients: ['awssqs:{{.metadata.annotations.resource_prefix}}-dora-{{.metadata.annotations.aws_cluster_name}}']
            triggers: [on-dora-success, on-dora-failure]
```

With a default subscription, Rollouts need no per-app annotations, so **`appmod-service` doesn't change**.

Region: the queues live in the DevLake RDS region (section 3). Using the spoke's own `aws_region` only gives the same value while hub and spokes share a region (see open questions).

If the chart doesn't render `subscriptions` through `notifiers` (spike check 2), fall back to annotating the Rollouts in `appmod-service`. Use `${schema.spec.resourcePrefix}-dora-${schema.spec.clusterName}` as the recipient in all four Rollout variants (`rolloutWithDynamoDB`, `rolloutWithoutDynamoDB`, `rolloutWithGatesAndDynamoDB`, `rolloutWithGatesWithoutDynamoDB`).

### 2. Spoke: argo-rollouts IAM

`gitops/addons/charts/crossplane-pod-identity/values.yaml`, the `argo-rollouts` identity (IRSA, `skipPIA: true`):

- Add `sqs:SendMessage` and `sqs:GetQueueUrl` on **exactly this cluster's queue**: `arn:aws:sqs:<region>:<account>:<prefix>-dora-{{ .Values.aws.clusterName }}`. The policy document is rendered through `tpl`, and the role is already per cluster (`<cluster>-argo-rollouts`). So the dev spoke can't write to the prod queue, and the reverse.
- This role is currently enabled only in `overlays/environments/dev/pod-identities`. Prod needs it as well. The prod overlay asks that workload identities self-provision rather than be added there, so decide which way to create it (see open questions).

The SA already carries `eks.amazonaws.com/role-arn: …/<cluster>-argo-rollouts` (`gitops/addons/registry/gitops.yaml`).

### 3. Hub: `devlake` chart

All new hub resources live in `gitops/addons/charts/devlake`, in the `devlake` namespace.

**Region:** the queues and the EventSource use `.Values.clusterRegion`, the same region as the DevLake RDS (`templates/rds-ack.yaml`). The registry sets it from the hub's `aws_region` (`registry/platform.yaml`). That region is the source of truth for the spoke `service.awssqs` region (section 1) and the `<region>` in the spoke IAM statement (section 2).

**New values:**

```yaml
dora:
  dryRun: true        # Phase 1: log payloads, don't POST
  environments:       # one queue per spoke; defaults match cicd-pipeline's deployClusterName / prodClusterName
    - cluster: '<prefix>-spoke-dev'
      environment: DEVELOPMENT
    - cluster: '<prefix>-spoke-prod'
      environment: PRODUCTION
```

**New templates:**

| Template | Resource | Notes |
|---|---|---|
| `dora-sqs.yaml` | ACK `sqs.services.k8s.aws/v1alpha1` `Queue` per `dora.environments` entry, `queueName: <prefix>-dora-<cluster>` | `receiveMessageWaitTimeSeconds: "20"`, `messageRetentionPeriod: "345600"` (4 days), so events wait in the queue while the hub or DevLake is down. There's no `cluster-mgmt-sqs` role: either rely on the ACK capability role as `amp-incident` does, or add the role and an `IAMRoleSelector` next to the existing ones in `iam-role-selectors.yaml`. |
| `dora-consumer-iam.yaml` | ACK IAM `Policy` + `Role` (pod identity trust) + `PodIdentityAssociation` + ServiceAccount `devlake-dora-consumer` | Only `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueUrl`, `sqs:GetQueueAttributes` on the queue ARNs. Needs `iam` and `eks` `IAMRoleSelector`s for the `devlake` namespace, which the chart doesn't have yet (it has `ec2` and `rds`). |
| `dora-eventbus.yaml` | Argo Events `EventBus` `default` | EventBuses are per namespace, and `devlake` has none. Use the same JetStream spec and PDB as the team namespaces. |
| `dora-eventsource.yaml` | `EventSource` `devlake-dora-sqs`, `spec.template.serviceAccountName: devlake-dora-consumer` | One `sqs` source per environment (`rollout-<cluster>`), each with `region: {{ .Values.clusterRegion }}`, `waitTimeSeconds: 20`, `jsonBody: true`. |
| `dora-sensor.yaml` | `Sensor` `devlake-dora` + SA/RBAC to submit Workflows in `devlake` | One dependency and one trigger per environment. Each trigger submits `dora-record-deployment` with `body` and `environment` set from the matching entry. |
| `dora-workflowtemplate.yaml` | `WorkflowTemplate` `dora-record-deployment` + SA allowed only `workflowtaskresults` | See below. |

Sensor dependency filter (per environment):

```yaml
filters:
  data:
    # string filter values are regex
    - path: body.namespace
      type: string
      value: ['^team-[a-z0-9-]+$']
    - path: body.image
      type: string
      value: ['^[0-9]{12}[.]dkr[.]ecr[.][a-z0-9-]+[.]amazonaws[.]com/.+:[0-9a-f]{40}$']
```

This drops placeholder images (such as `httpd:alpine` in a PROD manifest before its first promotion), gate images and non-team namespaces before any workflow runs. The per-app ECR check is in the workflow.

**`dora-record-deployment`**: one script step.

- Parameters: `body`, `environment` (set by the trigger, never read from the body), `dryRun` (from `.Values.dora.dryRun`).
- `BODY` comes in as an env var (it is untrusted input, so never inline it in the script).
- Steps:
  1. `APP=${namespace#team-}`. Accept only `^[a-z0-9-]+$`, since it is used in a URL path.
  2. Check `image` is exactly `<awsAccountId>.dkr.ecr.<clusterRegion>.amazonaws.com/<resourcePrefix>/<APP>:<40-hex>`: the repo `cicd-pipeline` creates (`ecrmainrepo`, `${resourcePrefix}/${application.name}`). If it isn't, log and exit 0.
  3. `GET devlake-lake.devlake.svc.cluster.local:8080/plugins/webhook/connections/by-name/${APP}_webhook`. On a 404 (no pipeline for this app), log and exit 0. On another error, fail.
  4. Build the payload and, unless `dryRun`, `POST …/connections/by-name/${APP}_webhook/deployments`. Fail on a non-2xx response.
- Payload:

```
id:            <namespace>-<environment>-<revision>-<result lowercased>
name:          deployment-<sha[0:7]>
environment:   the environment parameter
result:        body.result
createdDate / startedDate / finishedDate: body.finishedAt
deploymentCommits: [{
  repoUrl:      https://<gitlab_domain_name>/<git_username>/<APP>.git   # chart values; matches today's repository.git_http_url
  refName:      main
  commitSha:    ${image##*:}
  startedDate / finishedDate: body.finishedAt
  result:       body.result
}]
```

`repoUrl` is required by the webhook API and is part of the deployment-commit ID hash. Keep it stable and identical to today's value. The registry already knows `gitlab_domain_name` and `git_username`; pass them to the DevLake chart.

- Set `podGC` and `ttlStrategy` as the pipeline workflows do.

### 4. Hub: `cicd-pipeline` RGD (removals only, Phase 2)

- Sensor triggers `gitlab-dora-trigger` and `gitlab-dora-prod-trigger`, plus the `prod-deploy-webhook` dependency (first check nothing else uses it).
- The `doradeploy` WorkflowTemplate.
- `prodaccessentry`: its comment says it exists only for the DORA check.
- `accessentry`: cluster-admin on the dev spoke. The only `update-kubeconfig` call found is in `doradeploy`; confirm in a test run before deleting.
- The `eks:DescribeCluster` statement in `iampolicy`.

Keep: `doraincident`, `dorapullrequest`, `dorasetuptemplate`, `dorasetupworkflow`. The setup still creates the `<app>` project and the `<app>_webhook` connection that the consumer posts to by name.

## Behavior changes

- **Deployment frequency goes up.** Every rollout gets recorded, including rollbacks, re-promotes, and Kargo promotions, not only pushes. That's more accurate, but trends will step up after the cutover.
- **Start time becomes the finish time.** You lose the ReplicaSet-creation start time. DevLake measures lead time to `finishedDate`, so the impact is small.
- **One commit per deployment.** Only the image commit is recorded, not every commit in the push. In beta14, lead time matches a PR to its first production deployment through `commits_diffs` and the PR's `mergeCommitSha` (`plugins/dora/tasks/change_lead_time_calculator.go`), not through the list of commits on the deployment.
- **No timeout.** A rollout paused for manual promotion is recorded whenever it resolves.
- **Same commit, several records.** Records are keyed by Rollout revision, so redeploying a commit, or rolling back to it, adds a new record instead of overwriting the old one. A SUCCESS and a FAILURE at the same revision (an aborted canary that is then retried) are also kept separate by the `result` suffix.
- **A second abort of the same revision isn't recorded.** `oncePer` sends one FAILURE per revision. Retrying an aborted canary and aborting it again doesn't change the revision.
- **One consumer for all apps.** If it's broken, no app records deployments, but events wait in SQS for 4 days. Watch the queues' `ApproximateAgeOfOldestMessage`.

## Spike: verify before building

Run these on a dev spoke with one app.

1. **IRSA credentials:** the Rollouts `awssqs` service on chart 2.40.9 picks up credentials through the default chain. Send a test message to a hand-made queue. Also confirm a send to the other cluster's queue is denied.
2. **Values merge:** `service.awssqs` and `subscriptions` from the registry `valuesObject`, and the triggers and templates from `configs/argo-rollouts/values.yaml`, all end up in `argo-rollouts-notification-configmap`. Then confirm the default subscription fires for a Rollout with no annotations.
3. **kro and the `notified` annotation:** kro keeps the controller's `notified.notifications.argoproj.io` annotation on the Rollout through reconciles. If kro strips it, `oncePer` can't track what it already sent, and notifications repeat on every reconcile. That would block this design; you'd have to move the subscription or tracking elsewhere.
4. **Queue and IAM creation in `devlake`:** the chosen SQS role (the capability role or a new `cluster-mgmt-sqs`) can create the queues, and the new `iam`/`eks` selectors work in the `devlake` namespace.
5. **Trigger expressions:** `rollout.status.abort` and `phase == 'Degraded'` both fire for an aborted canary, and only one FAILURE is sent.
6. **Rollback:** deploy A, deploy B, then roll back to A (`kubectl argo rollouts undo`). Confirm three SUCCESS messages arrive with three different `revision` values, and that the rollback reuses A's pod hash but not its revision.
7. **By-name POST:** `POST devlake-lake:8080/plugins/webhook/connections/by-name/<app>_webhook/deployments` without a key returns 2xx, and the record shows up under the app's project after the blueprint runs.
8. **Lead time in webhook-only mode (existing behavior, not new):** beta14 computes lead time through `commits_diffs` (git data) and maps PRs to the project through `project_mapping` repos. A project fed only by webhooks may show no lead time whatever this design does. Check what today's setup actually produces before comparing.

## Migration

1. **Phase 1:** ship changes 1–3 with `dora.dryRun: true`. Compare the logged payloads with the records the old path sends for one app across a dev push, a prod promotion, an abort, and a rollback.
2. **Phase 2:** in one PR, set `dora.dryRun: false` and make the removals in change 4. Running both paths live would double-count deployment frequency.
3. **Tests and docs:**
   - Replace `workshop/scripts/tests/test_dora_prod_skip_placeholder.py` with tests of the Sensor filter and the workflow's per-app ECR check. Own repo + SHA matches. `httpd:alpine`, another app's repo, a non-SHA tag, and a non-`team-` namespace don't.
   - Review `test_dora_setup_rerun.py`; setup is unchanged.
   - Update the workshop DORA troubleshooting text: check SQS depth or the `devlake-dora-sqs` EventSource logs, then the `dora-record-deployment` workflow in `devlake`.

## Open questions

- Prod `argo-rollouts` IAM role: enable it in the prod `pod-identities` overlay (fast) or self-provision it (matches the prod convention)?
- SQS permissions for ACK in `devlake`: rely on the ACK capability role (as `amp-incident` does) or add a scoped `cluster-mgmt-sqs` role and `IAMRoleSelector`?
- Spoke and hub in different regions or accounts? The design assumes the same account and region.
  - A different region needs the DevLake RDS region (the hub's `aws_region`, as passed to the DevLake chart's `clusterRegion`) in `service.awssqs`. Add a hub-region annotation to the spoke cluster secrets instead of using `aws_region`.
  - Cross-account also needs an SQS queue policy that allows the spoke roles, plus `account` in `service.awssqs`.
- Spoke cluster names in `dora.environments`: hard-code the `<prefix>-spoke-dev` / `<prefix>-spoke-prod` defaults, or derive them from the fleet (spoke cluster secrets) so new spokes get a queue automatically?
- Add a DLQ? Probably not: the EventSource deletes each message once it's handed to the event bus, so failures show up as failed workflows, not redeliveries.

## Related fixes (independent of this design)

These don't depend on the spike and land separately on branch `fix/dora-devlake-related`.

Done on that branch:

- **No-op merge-request filter:** `pull-request-webhook` also tests `body.object_attributes.target_branch` as bool `false`. In Argo Events v1.9.10 (`pkg/sensors/dependencies/filter.go`) a bool filter parses its own value and compares it with gjson's `Bool()` of the field. For a string like `"main"` that is `false`, so the filter always passes. It doesn't drop events, as an earlier revision of this doc said; it's dead config. Removed.
- **`dorapullrequest` keys:** `pullRequestKey` now uses the MR number (`object_attributes.iid`) instead of GitLab's global `id`, and `headRepoId` uses `.project.id`, the same as `repoId`. The record `id` is unchanged, so existing rows are updated, not duplicated. DevLake decodes webhook bodies with `WeaklyTypedInput`, and sets `baseRepoId` to `webhook:<connectionId>` itself.
- **DevLake `v1.0.3-beta7` → `v1.0.3-beta14`** (not beta15, which has a broken migration):
  - Chart dependency, `Chart.lock`, image tags, and `devlake_version` in `registry/observability.yaml`.
  - beta14 moved the Grafana dashboards to `grafana/dashboards/mysql/` and renamed the detail dashboards (for example `DORADetails-ChangeFailureRate.json` → `dora-details-change-failure-rate.json`). `grafana-dashboards/templates/dora-dashboards.yaml` is updated to match. They still reference the `mysql` datasource.
  - The upstream chart's values only changed image repositories (scarf mirror → Docker Hub) and added optional keys, so our overrides are unchanged.
  - beta14 keeps the `connections/:connectionId/…` routes the current workflows use, and its new auth chain stays off unless `AUTH_ENABLED=true`.
- **Docs:** `.kiro/skills/eks-platform-engineering/references/measuring-success.md` now says DevLake derives change failure rate and recovery time from incidents linked to deployments by time, not from rollout failures.

Not done (need a decision or a running cluster):

- **Incident filter** (`issue_type == "incident"` or a label): the workshop's change-failure-rate exercise (`scripts/validation/validate-workshop-from-content.md`, Phase 70.3a) creates a plain issue. Filtering would break that exercise unless the content creates an incident-type issue or adds a label. Change the content and the filter together.
- **Lake memory:** the 512Mi limit is likely too low, but set it from measured usage on a running hub, not by guessing.
- **Lake API exposure:** `devlake-lake:8080` accepts unauthenticated calls from anywhere in the hub cluster. A NetworkPolicy on the lake alone isn't enough: `devlake-ui:4000`, which team workflows must reach for webhooks, proxies `/api/*` to the lake. Options are `AUTH_ENABLED=true` with API keys (and the consumer on `/rest/...`), or restricting the config UI's proxy to `/api/rest/*` for callers outside `devlake`.
