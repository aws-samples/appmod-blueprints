# Privileged steps on a separate runner (`privilegedSteps: external`)

Some install steps call AWS write APIs from the install host with the AWS CLI, not through
the kind bootstrap cluster: they create IAM roles and the EKS capability log delivery.
`privilegedSteps: external` in `config.local.yaml` moves those steps to a separate runner
with its own IAM role, so the install host can run with fewer permissions.

Supported providers: `kind-kro-ack` and `kind-crossplane`. Default: `inline` (or no key),
where `task install` does everything itself, as before. Any other value is refused by the
root entry points (`task install`, `task install:hub`, `task install:complete`,
`task privileged:*`) before their first AWS call. The provider-level entry points
(`task kind-kro-ack:install`, ...) refuse it only at their first role step, after kind has
started; use the root entry points.

## The runner tasks

Run these from the repository root on the runner, with a `config.local.yaml` that has the
same `clusterProvider`, `resourcePrefix`, `aws` and `hub` values as the install host and
**no** `privilegedSteps` key (or `privilegedSteps: inline`). The `privileged:*` tasks refuse
a config that says `external`.

| When | Runner task | What it does |
|---|---|---|
| Before `task install` | `task privileged:pre` | Creates the IAM roles the host would create: the `<prefix>-cluster-mgmt-<service>` roles, the Ray `<prefix>-model-prestage-role` and `<prefix>-ray-worker-role`, and on `kind-kro-ack` the `<hub>-crossplane-provider` role. Needs no hub. |
| After `task install` | `task privileged:post` | Applies the cluster-mgmt roles again (the hub's ACK capability role exists now, and gets the `ack-assume-role` policy) and enables the EKS capability log delivery. |
| After `task destroy` | `task privileged:destroy` | Deletes the capability-log deliveries of the removed clusters, then the roles `privileged:pre` created, by exact name. Refuses to delete roles while the hub cluster exists. Fails, naming what it could not delete, when any delete fails. |

On the install host, `task install` (and `task install:hub`) first checks, read-only, that
every role `privileged:pre` creates exists. A missing role stops the install before kind
starts and names the role. An AWS read error (expired credentials, access denied) is
reported as such, not as a missing role. `task install:external` (root; `install:codebuild`
is an alias) runs `task install` and requires `external`. The workshop's
`task install:codebuild` writes `privilegedSteps: external` into `config.local.yaml`; later
`task install` runs on that host stay external until the key is removed.

## IAM the runner needs

The runner's role must allow, on the role names above (`<prefix>-cluster-mgmt-*`,
`<hub>-crossplane-provider`, `<prefix>-model-prestage-role`, `<prefix>-ray-worker-role`):

- `privileged:pre`: `iam:GetRole`, `iam:CreateRole`, `iam:UpdateAssumeRolePolicy`,
  `iam:AttachRolePolicy` (the managed policies each role gets, see `get_policies()` in the
  provider's `hub:create-mgmt-roles:apply` and `hub:crossplane-provider-role:apply`),
  `iam:PutRolePolicy`; `eks:DescribeCapability` on the hub (read; it may not exist yet).
- `privileged:post`: the same, plus `iam:PutRolePolicy` on the hub's ACK capability role, and
  what `task enable-capability-logs` calls (`eks:DescribeCapability`, `eks:ListClusters`, the
  CloudWatch Logs delivery and resource-policy actions).
- `privileged:destroy`: `eks:DescribeCluster`, `eks:ListClusters`, `iam:GetRole`,
  `iam:ListAttachedRolePolicies`, `iam:DetachRolePolicy`, `iam:ListRolePolicies`,
  `iam:DeleteRolePolicy`, `iam:DeleteRole`, and the CloudWatch Logs `Describe*`/`Delete*`
  delivery actions. It needs `python3` with `boto3`.

A runner role scoped to `<prefix>-cluster-mgmt-*` only is not enough since the
crossplane-provider and Ray roles moved to `privileged:pre`.

## IAM the install host still needs in external mode

`external` removes the IAM role creates, policy attachments and capability-log writes listed
above from the host. The host still needs:

- Read access to those roles: `iam:GetRole`, `iam:ListAttachedRolePolicies`,
  `iam:GetRolePolicy`.
- `eks:CreatePodIdentityAssociation` and `iam:PassRole` on the roles it associates: the
  `<hub>-crossplane-provider` role (`kind-kro-ack`) and the two Ray roles.
- What the kind bootstrap cluster's ACK and Crossplane controllers do with the host's
  credentials: they create the hub (VPC, EKS cluster, its IAM roles, capabilities). This
  mode does not change that.
- The other AWS calls of the install that are not IAM role or capability-log writes, for
  example Secrets Manager seeding, the Ray S3 bucket, ECR repositories and the S3 CSI addon.
- Teardown: `task destroy` still deletes the platform's remaining `<prefix>-*` IAM roles and
  policies from the host. If the host may not delete them, the `kind-kro-ack` destroy names
  each role it could not delete and does not report success (the `kind-crossplane` destroy
  still ignores these errors). Delete them with the runner (`task privileged:destroy` for
  the roles above) or a stack-level sweep.

Not covered: `spokes:seed-provider-identity` (both providers), a manual task, still creates
its roles from wherever it runs. The Ray roles are created and verified in external mode
even when the install does not use Ray.
