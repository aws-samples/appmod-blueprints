# Design: Record DORA deployments from Argo Rollouts via SQS

Status: Proposed
Scope: `argo-rollouts` addon, `ack-pod-identity` and `crossplane-pod-identity` (argo-rollouts identity), a new hub-side `devlake-spoke-queue` addon and `DevlakeSpokeQueue` RGD, `devlake` chart (shared consumer), `cicd-pipeline` RGD (one ConfigMap added, DORA polling removed), and both cluster providers, `kind-kro-ack` and `kind-crossplane` (a new `<prefix>-cluster-mgmt-sqs` role)

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
| Per-app queues created by `cicd-pipeline` | Every pipeline would carry 2 queues, an IAM policy, role, SA, pod identity association and EventSource, and the spoke IAM would need a wildcard per cluster. Its only advantage, per-app isolation, is weak: a spoke's role could write every app's queue on its cluster anyway. |
| Spoke names listed in DevLake chart values | Cluster names are customer-supplied and can't be derived from `resourcePrefix`. A hand-maintained list also misses new spokes. Queues come from the fleet instead (section 3). |

## Design

```
spoke (labeled enable_devlake_spoke_queue=true,      hub
       environment=dev|prod)
Rollout ─ Healthy / Degraded ─┐
argo-rollouts notifications ──┴─awssqs──▶ SQS <prefix>-dora-<spoke cluster>
  (default subscription: every Rollout)        │   created per spoke from its cluster secret
                                               │   (devlake-spoke-queue addon, destinationHub)
                                     EventSource + Sensor dora-<spoke cluster>   (devlake ns, per spoke)
                                               │   environment = this spoke's label (dev → DEVELOPMENT, prod → PRODUCTION)
                                               ▼
                                     WorkflowTemplate dora-record-deployment     (devlake chart, shared)
                                       look up ConfigMap dora-app-<namespace>    (written by cicd-pipeline)
                                       → connection name, repo URL, image repository
                                       POST devlake-lake:8080/plugins/webhook/connections/by-name/<connection>/deployments
```

Principles:

- The spoke sends a **plain rollout event that knows nothing about DevLake**. All DevLake details stay on the hub.
- **One queue per spoke, created from the fleet.** Each spoke's cluster secret, through its `environment` label, produces that spoke's queue, EventSource and Sensor on the hub. No cluster names are hard-coded or derived from `resourcePrefix`; `resourcePrefix` only namespaces the queue name within the account. New spokes get a queue automatically.
- **The environment comes from the hub's view of the spoke, not from the sender.** It is the spoke cluster secret's `environment` label, mapped to a DevLake environment. Each spoke's argo-rollouts role can send only to its own queue (exact ARN), so a dev spoke can't produce PRODUCTION records.
- **The pipeline owns everything app-specific.** The consumer is generic: it knows nothing about GitLab, the `team-` namespace convention, or ECR naming. `cicd-pipeline` records, per app, the DevLake connection name, the real repo URL and the image repository in one ConfigMap in `devlake`. Events from namespaces without such a ConfigMap are skipped.
- DevLake stays private. The hub pulls from SQS, so nothing is exposed.

### DevLake API support (checked against the source)

- `v1.0.3-beta14` (`backend/plugins/webhook/impl/impl.go`) registers:
  - `connections/by-name/:connectionName/deployments`;
  - `connections/by-name/:connectionName/pull_requests`;
  - `connections/by-name/:connectionName/issues`;
  - the existing `connections/:connectionId/…` routes, so the `dorapullrequest` and `doraincident` workflows keep working unchanged.
- `v1.0.3-beta7` already has the same `by-name` routes, so this doesn't depend on the upgrade.
- beta14 also adds `projects/:projectName/deployments`. Don't use it: it finds or creates a separate connection named `<project>_deployments`. Deployments would land in a different connection from the PRs and incidents in `<app>_webhook`.
- **Auth:** beta14 adds an auth chain to the lake API (`RestAuthentication` for `/rest/*`, a push-key gate for `/push/*`, OIDC, then `RequireAuth`). `RequireAuth` is a no-op unless `AUTH_ENABLED=true`, and `AUTH_ENABLED` defaults to false (`helpers/oidchelper/config.go`). Calls to `devlake-lake:8080/plugins/...` without a key keep working, as the setup workflow already relies on.
  - If `AUTH_ENABLED` is ever turned on, the consumer must call `/rest/plugins/webhook/connections/by-name/...` with an API key whose allowed path covers `/plugins/webhook/.*`.
- **Which deployments count:** DevLake links incidents only to successful `PRODUCTION` deployments (`plugins/dora/tasks/incident_deploy_connector.go`), and lead time also only uses `PRODUCTION` deployments (`change_lead_time_calculator.go`). `DEVELOPMENT` records are stored but don't move the DORA dashboards.

### Event schema (spoke → SQS)

```json
{
  "result": "SUCCESS | FAILURE",
  "rollout": "<rollout name>",
  "uid": "<rollout.metadata.uid>",
  "namespace": "<rollout namespace>",
  "images": ["<image of each container in the pod template>", "..."],
  "revision": "<rollout.argoproj.io/revision annotation>",
  "podHash": "<rollout.status.currentPodHash>",
  "finishedAt": "<condition lastTransitionTime, else the notification time>"
}
```

- There's no `environment` field: the hub sets it from the spoke's cluster secret.
- `images` lists **every** container, so a sidecar listed first doesn't hide the app image. The consumer picks the one from the app's image repository.
- `finishedAt` is the time the rollout reached the state, not when the notification was sent:
  - SUCCESS: `lastTransitionTime` of the `Healthy` condition;
  - FAILURE: `lastTransitionTime` of the `Progressing` condition (reason `RolloutAborted` when aborted);
  - if the condition is missing, the notification time.
- `uid` and `revision` together identify one rollout of one Rollout object. `uid` keeps record ids unique across two spokes with the same `environment` label and after a Rollout is deleted and re-created, which restarts its revisions at 1. `podHash` is for debugging only.
- `result` is `SUCCESS` or `FAILURE`, the only deployment results DevLake beta14 defines (`core/models/domainlayer/devops/cicd_pipeline.go`). There's no `ABORT`, so an aborted canary is a `FAILURE`.

### Why `oncePer` uses the revision, not the pod hash

notifications-engine never clears an `oncePer` entry when the condition goes false (`pkg/controller/state.go`). It keeps up to 100 entries (`notifiedHistoryMaxSize`), keyed by the `oncePer` value. Keying on `currentPodHash` would therefore drop rollbacks: rolling back to a revision that was Healthy before brings back a pod hash that already has an entry, so no SUCCESS is sent.

`rollout.argoproj.io/revision` on the Rollout increments on every rollout, including a rollback to an older ReplicaSet. Keying `oncePer` on it records every rollout once. Keying the DevLake record `id` on it, together with the Rollout `uid`, means a rollback gets its own record instead of overwriting an earlier one.

`oncePer` doesn't need the `uid`: the controller keeps its `notified` state in an annotation on the Rollout, so a re-created Rollout starts with fresh state.

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
        {{- $at := "" -}}
        {{- range .rollout.status.conditions -}}{{- if eq .type "Healthy" -}}{{- $at = .lastTransitionTime -}}{{- end -}}{{- end -}}
        {"result":"SUCCESS",
         "rollout":"{{.rollout.metadata.name}}",
         "uid":"{{.rollout.metadata.uid}}",
         "namespace":"{{.rollout.metadata.namespace}}",
         "images":[{{range $i, $c := .rollout.spec.template.spec.containers}}{{if $i}},{{end}}"{{$c.image}}"{{end}}],
         "revision":"{{index .rollout.metadata.annotations "rollout.argoproj.io/revision"}}",
         "podHash":"{{.rollout.status.currentPodHash}}",
         "finishedAt":"{{if $at}}{{$at}}{{else}}{{dateInZone "2006-01-02T15:04:05Z" now "UTC"}}{{end}}"}
    template.dora-event-failure: |
      # same, with "result":"FAILURE" and $at from the Progressing condition
```

The per-cluster parts go in the registry's `valuesObject` (`gitops/addons/registry/gitops.yaml`, next to the existing `serviceAccount` annotation), which is templated per cluster from its cluster secret. They are the `service.awssqs` notifier, and a **default subscription** that sends every Rollout's events to this cluster's queue.

The subscription uses the chart's own `notifications.subscriptions` list. Chart 2.40.9 renders it into the ConfigMap's `subscriptions` key (`templates/controller/notifications-configmap.yaml`), so there's no need to pass it through `notifiers`:

```yaml
  valuesObject:
    notifications:
      notifiers:
        service.awssqs: |
          region: '{{default .metadata.annotations.aws_region (index .metadata.annotations "hub_region")}}'
      # Only for clusters that have a queue: the same gate and environment mapping as
      # the devlake-spoke-queue addon (section 3). Otherwise Rollouts would send to a
      # queue that doesn't exist.
      subscriptions: '{{ if and (eq (index .metadata.labels "enable_devlake_spoke_queue") "true") (has (index .metadata.labels "environment") (list "dev" "prod")) }}[{"recipients":["awssqs:{{.metadata.annotations.resource_prefix}}-dora-{{.metadata.annotations.aws_cluster_name}}"],"triggers":["on-dora-success","on-dora-failure"],"selector":"!dora.platform/exclude"}]{{ else }}[]{{ end }}'
```

- With a default subscription, Rollouts need no per-app annotations, so **`appmod-service` doesn't change**. It also covers Rollouts KubeVela creates.
- **Selector:** `!dora.platform/exclude` skips any Rollout labeled `dora.platform/exclude`, so Rollouts that aren't app deployments don't send a message each. App Rollouts need no label, so KubeVela coverage stays. The consumer drops non-pipeline Rollouts anyway; the selector just saves the messages. If most Rollouts on a spoke turn out not to be apps, switch to an opt-in label instead.
- How the ApplicationSet passes a list through `valuesObject` (a JSON string as above, or a templated YAML list) is checked in spike check 2.
- `hub_region` is a new cluster secret annotation (section 3): the region of the hub's DevLake RDS, where the queues live. Until it exists, the spoke's own `aws_region` is used, which is only right while hub and spokes share a region.

### 2. Spoke: argo-rollouts IAM (both providers)

The argo-rollouts role is created by whichever pod identity chart the cluster's provider uses. It is IRSA (`skipPIA: true`), because the AMP analysis gate's sigv4 library only supports web identity tokens.

| Provider | Chart and overlays | Trust policy today |
|---|---|---|
| kro-ack (default) | `gitops/addons/charts/ack-pod-identity`, enabled in `overlays/environments/{dev,prod}/ack-pod-identities/values.yaml` | IRSA when `skipPIA` and `aws.oidcIssuer` are set (`templates/role.yaml:22-40`). Works. |
| Crossplane | `gitops/addons/charts/crossplane-pod-identity`, enabled in `overlays/environments/{dev,prod}/pod-identities/values.yaml` | Only `pods.eks.amazonaws.com` (`templates/role.yaml:27`). **The IRSA annotation can't assume it**, so on this path the role is unusable for Rollouts today (the AMP gate included). |

Changes:

- **Both charts:** add `sqs:SendMessage` and `sqs:GetQueueUrl` on exactly this cluster's queue, `arn:aws:sqs:<hub region>:<account>:<prefix>-dora-{{ .Values.aws.clusterName }}`, to the argo-rollouts policy. Both charts render the policy document through `tpl`, and the role is per cluster, so the dev spoke can't write to the prod queue, and the reverse.
- **`crossplane-pod-identity`:** add the IRSA trust branch the ACK chart has (`Federated` OIDC provider, `sts:AssumeRoleWithWebIdentity`, `sub` = `system:serviceaccount:<ns>:<sa>`) when `skipPIA` is true and `aws.oidcIssuer` is set, and pass `oidcIssuer` from the registry as `ack_pod_identities` does. This is a bug fix in its own right: it also unblocks the AMP gate on Crossplane spokes.

The SA already carries `eks.amazonaws.com/role-arn: …/<cluster>-argo-rollouts` (`gitops/addons/registry/gitops.yaml`).

### 3. Hub, per spoke: new `devlake-spoke-queue` addon

A separate addon, not a values field in the `devlake` addon. The `devlake` addon is one Application rendered from the hub's own cluster secret, and Helm under Argo CD can't look up other clusters' secrets, so it can't list the spokes. A list in its values would be hand-maintained cluster names again.

Instead, a registry entry with `destinationHub: true`, the pattern `pod_identities` and `ack_pod_identities` already use. The ApplicationSet generates one Application per matching spoke from its cluster secret and deploys it to the hub. Removing a spoke from the fleet prunes its Application, and with it the queue, identity, EventSource and Sensor.

It is named and labeled for DevLake, because it only works alongside it:

- **Name:** `devlake-spoke-queue` (registry key `devlake_spoke_queue`, chart `gitops/addons/charts/devlake-spoke-queue`). Every resource it renders carries `app.kubernetes.io/part-of: devlake`.
- **Gate:** a spoke opts in with the label `enable_devlake_spoke_queue: 'true'`, following the `enable_<addon>` convention. The selector can only see the spoke's labels, not the hub's. So set the label only on spokes whose hub runs DevLake (`enable_devlake: 'true'`). Otherwise the per-spoke Sensors would land in a `devlake` namespace with no EventBus and no `dora-record-deployment`.
- **Order:** sync wave `8`, after `devlake` (wave `7`), so the namespace, EventBus and WorkflowTemplate exist before the first per-spoke EventSource and Sensor. Waves only order Applications synced together. On a spoke added later, DevLake is already running, and Argo CD retries a Sensor whose EventBus isn't ready yet.

```yaml
devlake_spoke_queue:
  namespace: devlake
  path: '{{.metadata.annotations.addonsRepoBasepath}}addons/charts/devlake-spoke-queue'
  destinationHub: true
  annotationsAppSet:
    # After devlake (wave 7): needs its namespace, EventBus and dora-record-deployment.
    argocd.argoproj.io/sync-wave: '8'
  selector:
    matchExpressions:
      - key: enable_devlake_spoke_queue
        operator: In
        values: ['true']
      - key: fleet_member
        operator: In
        values: ['spoke']
      - key: environment
        operator: In
        values: ['dev', 'prod']        # keep in step with environmentMap below
  valuesObject:
    clusterName: '{{.metadata.annotations.aws_cluster_name}}'
    resourcePrefix: '{{.metadata.annotations.resource_prefix}}'
    environment: '{{index .metadata.labels "environment"}}'
    region: '{{default .metadata.annotations.aws_region (index .metadata.annotations "hub_region")}}'
    accountId: '{{.metadata.annotations.aws_account_id}}'
    hubClusterName: '{{.metadata.annotations.hub_cluster_name}}'
```

Chart `gitops/addons/charts/devlake-spoke-queue` renders one `DevlakeSpokeQueue` instance into `devlake` on the hub. The new RGD `gitops/addons/charts/kro/resource-groups/manifests/devlake-spoke-queue/` builds the graph below. It's a kro graph rather than plain Helm templates for one reason: `peeks/depends-on` (the convention `cicd-pipeline` uses) orders each ACK resource after its `IAMRoleSelector`. kro then deletes the resource **before** its selector, so a teardown can't leave a Queue, Role or PodIdentityAssociation CR stuck with no role to delete it. Helm can't express that order, least of all across two Applications.

| Resource id | Resource | Notes |
|---|---|---|
| `selectorSqs`, `selectorIam`, `selectorEks` | Cluster-scoped `IAMRoleSelector`s for `sqs` → `<prefix>-cluster-mgmt-sqs`, `iam` → `<prefix>-cluster-mgmt-iam`, `eks` → `<prefix>-cluster-mgmt-eks` | `namespaceSelector: [devlake]`, plus `resourceLabelSelector: kro.run/instance-name: <instance>`, as `cicd-pipeline` does. Each spoke's selectors match only that spoke's resources, so the instances never conflict. |
| `queue` | ACK `Queue` `<prefix>-dora-<clusterName>`, annotated `peeks/depends-on: ${selectorSqs.metadata.name}` | In `region`. A **Standard** queue. `receiveMessageWaitTimeSeconds: "20"`; `messageRetentionPeriod: "345600"` (4 days), so events wait while the hub or DevLake is down; `sqsManagedSSEEnabled: "true"`; a queue policy that denies any request with `aws:SecureTransport` false. |
| `consumerPolicy`, `consumerRole` | ACK IAM `Policy` + `Role` (pod identity trust), `peeks/depends-on: ${selectorIam.metadata.name}` | Only `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueUrl`, `sqs:GetQueueAttributes` on **this** queue's ARN. One identity per spoke, so no policy has to list every queue. |
| `consumerPia` | ACK `PodIdentityAssociation` on `hubClusterName` for SA `dora-<clusterName>`, `peeks/depends-on: ${selectorEks.metadata.name}` | |
| `consumerSa` | ServiceAccount `dora-<clusterName>` | |
| `eventsource` | `EventSource` `dora-<clusterName>` | `sqs.rollout`: this queue, `region`, `waitTimeSeconds: 20`, `jsonBody: true`; runs as `dora-<clusterName>`. |
| `sensor` | `Sensor` `dora-<clusterName>` | One dependency. Its trigger submits `dora-record-deployment` with `body` and `environment`, from `environmentMap`. |

**Delivery semantics.**

- The queue is Standard, so delivery is at-least-once and unordered. The Rollouts SQS notifier sends no message group or deduplication id, so a FIFO queue wouldn't help.
- Duplicates are harmless: the record `id` is deterministic, so a repeated message updates the same DevLake row.
- Order doesn't matter: each record carries its own timestamps.
- The EventSource deletes a message once it has handed it to the event bus. A `dora-record-deployment` failure after that point is **not** redelivered from SQS, so retries live in the workflow (section 4).

**Provisioning role `<prefix>-cluster-mgmt-sqs`.**

- The ACK capability role can't create SQS resources: it only has `AssumeWorkloadRoles` and `ManageIRSARoles`. `amp-incident` routes its SQS/SNS CRs through a dedicated `cluster-mgmt-incident-bridge` role for the same reason (`workshop/aiops-agent/chart/files/aiops-agent-app.yaml:631-665`).
- So both cluster providers create `<prefix>-cluster-mgmt-sqs` next to the existing `cluster-mgmt-*` roles: `cluster-providers/kind-kro-ack/Taskfile.yaml` and `cluster-providers/kind-crossplane/Taskfile.yaml`, including the `privilegedSteps: external` path.
- It is trusted by the ACK capability role, like the other `cluster-mgmt-*` roles. The capability's `AssumeWorkloadRoles` already covers `<prefix>-cluster-mgmt-*`.
- Its policy allows only `sqs:CreateQueue`, `DeleteQueue`, `GetQueueAttributes`, `SetQueueAttributes`, `GetQueueUrl`, `TagQueue`, `UntagQueue` and `ListQueueTags`, on `arn:aws:sqs:*:<account>:<prefix>-dora-*`.
- Update `workshop/scripts/tests/test_install_no_admin_managed_policies.py`, and the teardown sweep (add an SQS reaper for `<prefix>-dora-*`), to match.

```yaml
# chart values
environmentMap:           # cluster secret environment label → DevLake environment
  dev: DEVELOPMENT
  prod: PRODUCTION
```

- A label with no mapping renders nothing, rather than guessing an environment. Keep the selector and the spoke subscription condition (section 1) in step with this map and with the `enable_devlake_spoke_queue` gate.
- **New annotation `hub_region`** on spoke cluster secrets, next to `hub_cluster_name`, from both providers (the `EksCluster` RGD and the Crossplane fleet-secret chart). It is the hub's region, the same `aws_region` the registry passes to the DevLake chart as `clusterRegion` for the RDS. Until it exists, `aws_region` is the fallback.
- `hub_cluster_name` (where `destinationHub` apps go and where the pod identity association is created) is itself built from `resourcePrefix` today (`rg-eks.yaml:649`). That predates this design, but it has the same customer-supplied-name problem, and it should be fixed with `hub_region`.

### 4. Hub, shared: `devlake` chart

Pieces every spoke's Sensor uses, in `gitops/addons/charts/devlake`, in the `devlake` namespace:

| Template | Resource | Notes |
|---|---|---|
| `dora-eventbus.yaml` | Argo Events `EventBus` `default` | EventBuses are per namespace, and `devlake` has none. Use the same JetStream spec and PDB as the team namespaces. |
| `dora-sensor-rbac.yaml` | ServiceAccount + Role for the Sensors to submit Workflows in `devlake` | |
| `dora-workflowtemplate.yaml` | `WorkflowTemplate` `dora-record-deployment` + an SA allowed only `workflowtaskresults` and `get` on ConfigMaps in `devlake` | See below. |

The `sqs`, `iam` and `eks` `IAMRoleSelector`s live in each `DevlakeSpokeQueue` instance (section 3), not in this chart, so `peeks/depends-on` can order them.

**`dora-record-deployment`**: one script step, generic.

- Parameters: `body`, `environment` (set by the trigger, never read from the body), `dryRun` (from `.Values.dora.dryRun`, default `true` in Phase 1).
- `BODY` comes in as an env var (it is untrusted input, so never inline it in the script).
- Steps:
  1. Validate the message; on any failure, log and exit 0:
     - `namespace` is a valid Kubernetes namespace name (`^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$`);
     - `result` is `SUCCESS` or `FAILURE`;
     - `finishedAt` is an RFC 3339 timestamp;
     - `revision` is a positive integer;
     - `uid` is a UUID.
  2. `GET` ConfigMap `dora-app-<namespace>` in `devlake`. If it's missing (no pipeline for this namespace), log and exit 0.
  3. From the ConfigMap, take `connectionName`, `repoUrl` and `imageRepository`. Pick the entry in `images` that is `<imageRepository>:<40-hex>`. If there's none (placeholder image, gate image, another app's image), log and exit 0.
  4. Check the connection exists (`GET …/connections/by-name/<connectionName>`). If it doesn't, log and exit 0. On any other error, fail.
  5. Build the payload and, unless `dryRun`, `POST …/connections/by-name/<connectionName>/deployments`. Fail on a non-2xx response.
- **Retries:** the template sets `retryStrategy` (`limit: 6`, `retryPolicy: Always`, exponential backoff from 10s with `factor: 2` up to 10m), because DevLake restarts are routine. SQS won't redeliver once the EventSource has consumed the message (section 3).
- **Alerting:** the template emits an Argo Workflows Prometheus counter on failure (`dora_record_deployment_failed_total`, labeled by environment). An alert fires when it increases. A failed workflow after all retries is a lost record; re-run it from the Argo UI.
- Payload:

```
id:            <rollout uid>-<revision>-<result lowercased>
name:          deployment-<sha[0:7]>
environment:   the environment parameter
result:        body.result
createdDate / startedDate / finishedDate: body.finishedAt
deploymentCommits: [{
  repoUrl:      ConfigMap repoUrl
  refName:      main
  commitSha:    the matched image's tag
  startedDate / finishedDate: body.finishedAt
  result:       body.result
}]
```

- `repoUrl` is required by the webhook API and is part of the deployment-commit ID hash, so it comes from the pipeline (section 5), not from a convention in the consumer.
- Set `podGC` and `ttlStrategy` as the pipeline workflows do.

### 5. Hub: `cicd-pipeline` RGD

**Add** a ConfigMap `dora-app-${schema.spec.namespace}` in the `devlake` namespace, created by kro alongside the pipeline's other resources:

```yaml
data:
  connectionName: ${schema.spec.application.name}_webhook   # the connection dorasetup creates
  repoUrl: <the repo URL the pipeline clones (workflow parameter git-url)>
  imageRepository: ${ecrmainrepo.status.repositoryURI}
```

- `repoUrl` is the same URL the pipeline already uses for this app. For GitLab it equals today's `repository.git_http_url`, so deployment-commit IDs keep their current form.
- The name is keyed by the app's namespace on the spokes (`spec.namespace`, which `prodaccessentry` already scopes to), so the consumer finds it straight from the event, with no `team-` assumption. Two pipelines deploying to the same namespace would collide; kro rejects the second (see open questions).
- A cross-namespace resource can't have an `ownerReference` to the CICDPipeline. kro must delete it with the instance (spike check 4).

**Remove** (Phase 2):

- Sensor triggers `gitlab-dora-trigger` and `gitlab-dora-prod-trigger`, plus the `prod-deploy-webhook` dependency (first check nothing else uses it).
- The `doradeploy` WorkflowTemplate.
- `prodaccessentry`: its comment says it exists only for the DORA check.
- `accessentry`: cluster-admin on the dev spoke. The only `update-kubeconfig` call found is in `doradeploy`; confirm in a test run before deleting.
- The `eks:DescribeCluster` statement in `iampolicy`.

Keep: `doraincident`, `dorapullrequest`, `dorasetuptemplate`, `dorasetupworkflow`. The setup still creates the project and the `<app>_webhook` connection the consumer posts to.

## Behavior changes

- **Deployment frequency goes up.** Every rollout gets recorded, including rollbacks, re-promotes, and Kargo promotions, not only pushes. That's more accurate, but trends will step up after the cutover.
- **Only production moves the dashboards.** `DEVELOPMENT` records are kept, but DevLake's DORA calculations only use `PRODUCTION` deployments (see DevLake API support).
- **Start time becomes the finish time.** Lead time is measured to `finishedDate`, so the impact is small.
- **One commit per deployment.** Only the image commit is recorded, not every commit in the push. In beta14, lead time matches a PR to its first production deployment through `commits_diffs` and the PR's `mergeCommitSha`, not through the list of commits on the deployment.
- **No timeout.** A rollout paused for manual promotion is recorded whenever it resolves.
- **Same commit, several records.** Records are keyed by Rollout `uid` and revision, so redeploying a commit, or rolling back to it, adds a new record instead of overwriting the old one. A SUCCESS and a FAILURE at the same revision (an aborted canary that is then retried) are also kept separate by the `result` suffix.
- **A second abort of the same revision isn't recorded.** `oncePer` sends one FAILURE per revision. Retrying an aborted canary and aborting it again doesn't change the revision.
- **One consumer template for all apps.** If it's broken, no app records deployments, but events wait in SQS for 4 days. Watch each queue's `ApproximateAgeOfOldestMessage`.

## Spike: verify before building

Run these on a dev spoke with one app, **on both providers** where marked.

1. **IRSA credentials (kro-ack and Crossplane):** the Rollouts `awssqs` service on chart 2.40.9 gets credentials from the IRSA role through the default chain. Send a test message to a hand-made queue, and confirm a send to another cluster's queue is denied. On Crossplane, do this after adding the IRSA trust branch (section 2).
2. **Values merge:** `service.awssqs` and the `notifications.subscriptions` list from the registry `valuesObject`, and the triggers and templates from `configs/argo-rollouts/values.yaml`, all end up in `argo-rollouts-notification-configmap`. The default subscription fires for a Rollout with no annotations, and the `!dora.platform/exclude` selector skips a labeled one.
3. **kro and the `notified` annotation:** kro keeps the controller's `notified.notifications.argoproj.io` annotation on the Rollout through reconciles. If kro strips it, `oncePer` can't track what it already sent, and notifications repeat on every reconcile. That would block this design; you'd have to move the subscription or tracking elsewhere.
4. **Cross-namespace ConfigMap:** kro (capability) can create `dora-app-<namespace>` in `devlake` from a CICDPipeline in another namespace, and deletes it when the instance is deleted.
5. **`destinationHub` + ACK in `devlake`:** with `enable_devlake_spoke_queue: 'true'` on the spoke, the `devlake-spoke-queue` app lands on the hub at wave 8, after `devlake`. ACK creates the queue through `<prefix>-cluster-mgmt-sqs`, and the IAM role and pod identity association through the instance's `iam`/`eks` selectors. Then delete the instance and confirm kro removes the Queue, Role and PodIdentityAssociation CRs before their selectors, with none left stuck. Without the label, no app is generated and the spoke's ConfigMap has no `dora` subscription.
6. **Trigger expressions and conditions:**
   - `rollout.status.abort` and `phase == 'Degraded'` both fire for an aborted canary, and only one FAILURE is sent.
   - The `Healthy` and `Progressing` conditions carry the expected `lastTransitionTime` on argo-rollouts v1.8.
7. **Rollback:** deploy A, deploy B, then roll back to A (`kubectl argo rollouts undo`). Confirm three SUCCESS messages arrive with three different `revision` values, and that the rollback reuses A's pod hash but not its revision.
8. **By-name POST:** `POST devlake-lake:8080/plugins/webhook/connections/by-name/<app>_webhook/deployments` without a key returns 2xx, and the record shows up under the app's project after the blueprint runs.
9. **Lead time in webhook-only mode (existing behavior, not new):** beta14 computes lead time through `commits_diffs` (git data) and maps PRs to the project through `project_mapping` repos. A project fed only by webhooks may show no lead time whatever this design does. Check what today's setup actually produces before comparing.

## Migration

1. **Phase 1:** ship changes 1–5 (without the removals) with `dora.dryRun: true`. Compare the logged payloads with the records the old path sends for one app across a dev push, a prod promotion, an abort, and a rollback.
   - **Compare:** `environment`, `result`, the deployment commit's `commitSha`, and `finishedDate` within a window (about 2 minutes: the old path stamps the time its poll saw the result, the new one the condition's transition time).
   - **Expected to differ, by design:**
     - the record `id`;
     - `refName`: `main` here, `refs/heads/main` today (`cicd-pipeline.yaml:1909`);
     - the commit list: one image commit here, every commit in the push today;
     - `startedDate`: equal to the finish time here, the ReplicaSet creation time today.
   - **Extra records the old path never sent** (rollbacks, re-promotes) are expected too.
2. **Phase 2:** in one PR, set `dora.dryRun: false` and make the removals in change 5. Running both paths live would double-count deployment frequency.
3. **Tests and docs:**
   - Replace `workshop/scripts/tests/test_dora_prod_skip_placeholder.py` with tests of `dora-record-deployment`. The app image + SHA matches even when it isn't the first container. A placeholder or gate image, another app's repo, a non-SHA tag, an invalid namespace, and a namespace without a `dora-app-` ConfigMap are skipped.
   - Review `test_dora_setup_rerun.py`; setup is unchanged.
   - Update the workshop DORA troubleshooting text: check SQS depth or the `dora-<spoke>` EventSource logs, then the `dora-record-deployment` workflow in `devlake`.

## Workshop content

The workshop content describes today's flow, a workflow in the team namespace that checks the Rollout right after the push. Update it in the same release as Phase 2:

- **`70_MeasuringPlatformSuccess/72_DeploymentFrequency`, practice and failure-demo steps:** the deployment record now appears as a `dora-record-deployment` workflow in `devlake`, after Argo CD syncs and the canary completes (or aborts), not as a workflow started by the push. Learners should watch that workflow, or the DevLake record, instead of the team-namespace workflow.
- **Onboarding overview:** replace "the pipeline checks the Rollout after each push" with: the Rollouts controller reports each rollout's outcome through the spoke's queue, and the hub records it.
- **Prod demos:** only `PRODUCTION` deployments move the DORA dashboards. The deployment-frequency and failure demos must deploy to the prod spoke, or say that dev deployments are recorded but not charted.

## Open questions

- **Cross-account spokes:** the design assumes hub and spokes share an account. Cross-account also needs an SQS queue policy that allows the spoke roles, plus `account` in `service.awssqs`.
- **Other `environment` labels** (for example `staging`): map them to DevLake's `STAGING`/`TESTING`, or leave them unrecorded? They're unrecorded until added to `environmentMap` and the two places that mirror it.
- **Two pipelines in one namespace:** today each pipeline deploys to its own namespace. If that ever changes, key the ConfigMap on namespace and rollout name.
- **Add a DLQ?** No: a DLQ only catches messages SQS redelivers, and the EventSource deletes each message once it's on the event bus. Failures after that are failed `dora-record-deployment` workflows, covered by the retry strategy and the failure alert (section 4). A DLQ would only help if the EventSource itself kept failing to hand off, and then the queue's `ApproximateAgeOfOldestMessage` alarm is the signal.

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
