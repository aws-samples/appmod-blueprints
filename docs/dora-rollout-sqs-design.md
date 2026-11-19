# Design: Record DORA deployments from Argo Rollouts via SQS

Status: Proposed
Scope: `cicd-pipeline` RGD, `appmod-service` RGD, `argo-rollouts` addon, `crossplane-pod-identity` (argo-rollouts identity)

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

## Design

```
spoke (dev|prod)                         hub (per CICDPipeline, team-<app> ns)
Rollout ─ Healthy / Degraded ─┐
argo-rollouts notifications ──┴─awssqs──▶ SQS <prefix>-dora-team-<app>-<spoke cluster>
                                              │   (one queue per app per environment)
                                              │ long-poll (pod identity, SQS read only)
                                    EventSource <name>-dora-sqs (dev + prod sources)
                                              │
                                    existing Sensor: filter image = this app's ECR repo + SHA tag;
                                                     environment = which queue it came from
                                              │
                                    slim doradeploy Workflow: jq → POST DevLake /deployments
```

Principles:

- The spoke sends a **plain rollout event that knows nothing about DevLake**. All DevLake details (IDs, repo URL, payload shape) stay on the hub.
- **One queue per app per environment.** Each CICDPipeline has its own DevLake project and webhook connection, and SQS delivers each message to only one consumer. Per-app queues let the existing per-pipeline Sensor and `devlake-webhook-secret` keep working without a routing layer.
- **The environment comes from the queue, not from the sender.** Each spoke's argo-rollouts role can write only to queues named for its own cluster, so a dev spoke can't produce PRODUCTION records.
- Queue name convention: `<resourcePrefix>-dora-team-<app>-<spoke cluster name>`. Both RGDs derive it independently:
  - `appmod-service`: `${resourcePrefix}-dora-${namespace}-${clusterName}`, using the existing `clusterName` field.
  - `cicd-pipeline`: one queue for `deployClusterName` (DEVELOPMENT) and one for `prodClusterName` (PRODUCTION).
  - SQS names are limited to 80 characters; check the longest app name plus cluster name fits.
- DevLake stays private. The hub pulls from SQS, so nothing is exposed.

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

The `service.awssqs` notifier is set per cluster in the registry's `valuesObject` (`gitops/addons/registry/gitops.yaml`, next to the existing `serviceAccount` annotation). That file is templated per cluster:

```yaml
  valuesObject:
    notifications:
      notifiers:
        service.awssqs: |
          region: '{{.metadata.annotations.aws_region}}'
```

`aws_region` is the spoke's region, and the queue lives in the hub's region. This works while hub and spokes share a region (see open questions).

No environment overlays are needed: the hub sets the environment from the queue.

### 2. Spoke: argo-rollouts IAM

`gitops/addons/charts/crossplane-pod-identity/values.yaml`, the `argo-rollouts` identity (IRSA, `skipPIA: true`):

- Add a statement with `sqs:SendMessage` and `sqs:GetQueueUrl` on **only this cluster's queues**: `arn:aws:sqs:<region>:<account>:<prefix>-dora-*-{{ .Values.aws.clusterName }}`. The policy document is rendered through `tpl` and the role is already per cluster (`<cluster>-argo-rollouts`), so each spoke can write only to queues ending in its own cluster name. The prod queues allow only the prod spoke's role.
- Make sure no cluster name is a suffix of another (for example `spoke-dev` and `x-spoke-dev`); otherwise the wildcard would match the other cluster's queues.
- This role is currently enabled only in `overlays/environments/dev/pod-identities`. Prod needs it as well. The prod overlay asks that workload identities self-provision rather than be added there, so decide which way to create it (see open questions).

The SA already carries `eks.amazonaws.com/role-arn: …/<cluster>-argo-rollouts` (`gitops/addons/registry/gitops.yaml`).

### 3. Spoke: `appmod-service` RGD

`gitops/addons/charts/kro/resource-groups/manifests/appmod-service.yaml`. Add these annotations to the Rollout metadata in all four variants (`rolloutWithDynamoDB`, `rolloutWithoutDynamoDB`, `rolloutWithGatesAndDynamoDB`, `rolloutWithGatesWithoutDynamoDB`):

```yaml
annotations:
  notifications.argoproj.io/subscribe.on-dora-success.awssqs: ${schema.spec.resourcePrefix}-dora-${schema.metadata.namespace}-${schema.spec.clusterName}
  notifications.argoproj.io/subscribe.on-dora-failure.awssqs: ${schema.spec.resourcePrefix}-dora-${schema.metadata.namespace}-${schema.spec.clusterName}
```

`clusterName` must be the name of the spoke the Rollout runs on; it already feeds the AMP query's `cluster` label. A wrong value doesn't mislabel records: that spoke's role is denied on the other cluster's queue.

Apps with no CICDPipeline (and so no queue) will record `NotificationFailed` events. If that's too noisy, add a `dora.enabled: boolean | default=true` schema field and use it to choose between annotated and unannotated variants.

### 4. Hub: `cicd-pipeline` RGD

#### Add

| id | Resource | Notes |
|---|---|---|
| `doraqueuedev`, `doraqueueprod` | ACK `sqs.services.k8s.aws/v1alpha1` `Queue`s: `<prefix>-dora-team-<app>-${deployClusterName}` and `…-${prodClusterName}` | `receiveMessageWaitTimeSeconds: "20"`, `messageRetentionPeriod: "345600"` (4 days), so events wait in the queue while the hub or DevLake is down. Like `amp-incident`, they rely on the ACK capability role (there is no `cluster-mgmt-sqs` role or IAMRoleSelector). |
| `dorasqspolicy` | ACK IAM `Policy` | Only `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueUrl`, `sqs:GetQueueAttributes` on the two queue ARNs. |
| `dorasqsrole` | ACK IAM `Role` with a pod identity trust policy | Same pattern as `iamrole`. |
| `dorasqssa` | ServiceAccount `<name>-dora-sa` | **Dedicated.** Don't reuse `<name>-sa`, which can push to ECR. |
| `dorasqspia` | ACK `PodIdentityAssociation` | Binds `dorasqsrole` to `<name>-dora-sa`. |
| `dorasqseventsource` | Argo Events `EventSource` `<name>-dora-sqs`, `spec.template.serviceAccountName: <name>-dora-sa` | Keep it separate from the GitLab EventSource, which faces the internet and is deliberately kept free of credentials. |

EventSource:

```yaml
spec:
  template:
    serviceAccountName: ${dorasqssa.metadata.name}
  sqs:
    rollout-dev:
      region: ${schema.spec.aws.region}
      queue: ${doraqueuedev.spec.queueName}
      waitTimeSeconds: 20
      jsonBody: true
    rollout-prod:
      region: ${schema.spec.aws.region}
      queue: ${doraqueueprod.spec.queueName}
      waitTimeSeconds: 20
      jsonBody: true
```

#### Sensor (`sensor`)

Add two dependencies, `rollout-event-dev` (`eventName: rollout-dev`) and `rollout-event-prod` (`eventName: rollout-prod`), each with the same filter:

```yaml
- name: rollout-event-dev
  eventSourceName: ${dorasqseventsource.metadata.name}
  eventName: rollout-dev
  filters:
    data:
      # string filter values are regex
      - path: body.image
        type: string
        value: ['^${ecrmainrepo.status.repositoryURI}:[0-9a-f]{40}$']
```

This filter replaces `resolve-deployed-tag`. The `httpd:alpine` prod placeholder, gate images and other apps' images never match it.

Add two triggers, `dora-rollout-dev-trigger` and `dora-rollout-prod-trigger`. Each submits `doradeploy`, passes `body` exactly as the existing triggers do, and sets the `environment` parameter (`DEVELOPMENT` or `PRODUCTION`) from which dependency fired.

#### Rewrite `doradeploy`

Replace the three templates (`handle-rollout-check-and-process-deploy`, `check-rollout-status`, `resolve-deployed-tag`, about 280 lines) with one script step:

- Parameters: `body`, `environment` (set by the trigger, never read from the body), `dryRun` (default `"true"` during migration).
- `BODY` comes in as an env var (it is untrusted input, so never inline it in the script).
- `envFrom` `devlake-webhook-secret` / `devlake-webhook-id`.
- Payload:

```
id:            <namespace>-<environment>-<revision>-<result lowercased>
name:          deployment-<sha[0:7]>
environment:   the environment parameter
result:        body.result
createdDate / startedDate / finishedDate: body.finishedAt
deploymentCommits: [{
  repoUrl:      https://<gitlab.hostname>/<gitlab.username>/<app>.git   # must match today's repository.git_http_url
  refName:      main
  commitSha:    ${image##*:}
  startedDate / finishedDate: body.finishedAt
  result:       body.result
}]
```

- `dryRun=true` → print the payload only. `dryRun=false` → `curl` POST to `devlake-ui.devlake.svc.cluster.local:4000/api/rest/plugins/webhook/connections/$DEVLAKE_HOOK_ID/deployments`, then fail the step on a non-2xx response.
- Keep `podGC` and `ttlStrategy` as they are today.

#### Remove (Phase 2)

- Sensor triggers `gitlab-dora-trigger` and `gitlab-dora-prod-trigger`, plus the `prod-deploy-webhook` dependency (first check nothing else uses it).
- `prodaccessentry`: its comment says it exists only for the DORA check.
- `accessentry`: cluster-admin on the dev spoke. The only `update-kubeconfig` call found is in `doradeploy`; confirm in a test run before deleting.
- The `eks:DescribeCluster` statement in `iampolicy`.
- The workflow parameters `target-cluster-name`, `target-cluster-region`, `target-role-arn`.

Keep: `doraincident`, `dorapullrequest`, `dorasetuptemplate`, `dorasetupworkflow`.

## Behavior changes

- **Deployment frequency goes up.** Every rollout gets recorded, including rollbacks, re-promotes, and Kargo promotions, not only pushes. That's more accurate, but trends will step up after the cutover.
- **Start time becomes the finish time.** You lose the ReplicaSet-creation start time. DevLake measures lead time to `finishedDate`, so the impact is small.
- **One commit per deployment.** Only the image commit is recorded, not every commit in the push. DevLake links lead time to PRs through `mergeCommitSha`, and for a merge to main that is the image commit.
- **No timeout.** A rollout paused for manual promotion is recorded whenever it resolves.
- **Same commit, several records.** Records are keyed by Rollout revision, so redeploying a commit, or rolling back to it, adds a new record instead of overwriting the old one. A SUCCESS and a FAILURE at the same revision (an aborted canary that is then retried) are also kept separate by the `result` suffix.
- **A second abort of the same revision isn't recorded.** `oncePer` sends one FAILURE per revision. Retrying an aborted canary and aborting it again doesn't change the revision.

## Spike: verify before building

Run these on a dev spoke with one app.

1. **IRSA credentials:** the Rollouts `awssqs` service on chart 2.40.9 picks up credentials through the default chain. Send a test message to a hand-made queue. Also confirm a send to another cluster's queue is denied.
2. **Values merge:** the `service.awssqs` notifier from the registry `valuesObject` and the triggers and templates from `configs/argo-rollouts/values.yaml` both end up in `argo-rollouts-notification-configmap`.
3. **kro and the `notified` annotation:** kro keeps the controller's `notified.notifications.argoproj.io` annotation on the Rollout through reconciles. If kro strips it, `oncePer` can't track what it already sent, and notifications repeat on every reconcile. That would block this design; you'd have to move the subscription or tracking elsewhere.
4. **Queue creation:** the ACK capability role can create SQS queues in `team-*` namespaces.
5. **Trigger expressions:** `rollout.status.abort` and `phase == 'Degraded'` both fire for an aborted canary, and only one FAILURE is sent.
6. **Rollback:** deploy A, deploy B, then roll back to A (`kubectl argo rollouts undo`). Confirm three SUCCESS messages arrive with three different `revision` values, and that the rollback reuses A's pod hash but not its revision.

## Migration

1. **Phase 1:** ship changes 1–4 with `dryRun=true`. Compare the logged payloads with the records the old path sends for one app across a dev push, a prod promotion, an abort, and a rollback.
2. **Phase 2:** in one PR, set `dryRun=false` and delete the items under "Remove". Running both paths live would double-count deployment frequency.
3. **Tests and docs:**
   - Replace `workshop/scripts/tests/test_dora_prod_skip_placeholder.py` with a test of the Sensor image-filter regex: own repo + SHA matches; `httpd:alpine`, another repo, or a non-SHA tag doesn't.
   - Review `test_dora_setup_rerun.py`; setup is unchanged.
   - Update the workshop DORA troubleshooting text: check SQS depth or the EventSource logs, then the `doradeploy` workflow.

## Open questions

- Prod `argo-rollouts` IAM role: enable it in the prod `pod-identities` overlay (fast) or self-provision it (matches the prod convention)?
- Spoke and hub in different regions or accounts? The design assumes the same account and region. A different region needs the hub's region in `service.awssqs`: add a hub-region annotation to the spoke cluster secrets instead of using `aws_region`. Cross-account also needs an SQS queue policy that allows the spoke roles, plus `account` in `service.awssqs`.
- Add a DLQ? Probably not: the EventSource deletes each message once it's handed to the event bus, so failures show up as failed workflows, not redeliveries.

## Related fixes (independent of this design)

These don't depend on the spike. Track each one as its own issue (links to be added) so it can land separately.

- **PR sensor filter likely never matches:** `pull-request-webhook` filters `body.object_attributes.target_branch` as both string `main` and bool `false`. Data filters must all pass, so merge-request events are dropped. The bool filter was probably meant for `draft`.
- **`dorapullrequest` IDs:** `pullRequestKey` should use `object_attributes.iid`, and `headRepoId` should be `.project.id`, matching `repoId`.
- **Incident filter:** only count GitLab issues with `issue_type == "incident"` (or a label) toward change failure rate.
- **DevLake version:** upgrade from `v1.0.3-beta7` to `v1.0.3-beta14` (not beta15, which has a broken migration). Bump both `configs/devlake/values.yaml` and `devlake_version` in `registry/observability.yaml`.
- **Lake memory:** re-measure; the 512Mi limit is likely too low.
- **Docs:** state that DevLake computes change failure rate and recovery time from incidents linked by timestamp, not from rollout failures (workshop content and `.kiro/skills/eks-platform-engineering/references/measuring-success.md`).
