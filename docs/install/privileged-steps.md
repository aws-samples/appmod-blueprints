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
| After the hub EKS cluster is deleted | `task privileged:destroy` | Deletes the capability-log deliveries of the removed clusters, then the roles `privileged:pre` created, by exact name. Refuses to delete roles while the hub cluster exists. Fails, naming what it could not delete, when any delete fails. On `kind-crossplane`, `task destroy` deletes the hub. On `kind-kro-ack`, `task destroy` under `external` does not (see Teardown below): the hub is deleted by a stack sweep, or by `task destroy` run again with `privilegedSteps: inline` and credentials allowed to make its AWS deletes, before this step. |

On the install host, `task install` (and `task install:hub`) first checks, read-only, that
every role `privileged:pre` creates exists, with the policies it attaches (the scoped
policies included). A bring-your-own role (`hub.iam.*`, `kind-kro-ack`) is only checked to
exist. A missing role or scoped policy stops the install before kind starts and names it. A
policy left by an older install (`AdministratorAccess`, `IAMFullAccess`) is reported as a
warning. On `kind-kro-ack`, `privileged:pre` detaches it; `kind-crossplane` does not, so
detach it by hand there. An AWS read error (expired credentials, access denied) is
reported as such, not as a missing role. `task install:external` (root; `install:codebuild`
is an alias) runs `task install` and requires `external`. The workshop's
`task install:codebuild` writes `privilegedSteps: external` into `config.local.yaml`; later
`task install` runs on that host stay external until the key is removed.

## IAM the runner needs

The runner's role must allow, on the role names above (`<prefix>-cluster-mgmt-*`,
`<hub>-crossplane-provider`, `<prefix>-model-prestage-role`, `<prefix>-ray-worker-role`):

- `privileged:pre`: `iam:GetRole`, `iam:CreateRole`, `iam:UpdateAssumeRolePolicy`,
  `iam:AttachRolePolicy` (the AWS managed policies each role gets, see `get_policies()` in
  the provider's `hub:create-mgmt-roles:apply`, and the scoped policies below,
  `arn:aws:iam::<account>:policy/<prefix>-*-scoped[-<8 hex>]`), `iam:DetachRolePolicy` (the
  policies older installs attached, `kind-kro-ack` only: `IAMFullAccess` on
  `<prefix>-cluster-mgmt-iam`, `AdministratorAccess` on `<hub>-crossplane-provider`; and an
  older scoped policy after a change of the document), `iam:ListAttachedRolePolicies`,
  `iam:PutRolePolicy`;
  `eks:DescribeCapability` on the hub (read; it may not exist yet).
  `<prefix>-cluster-mgmt-iam` and, on `kind-kro-ack`, `<hub>-crossplane-provider` get a
  scoped customer-managed policy (`<role>-scoped`, or `<role>-scoped-<8 hex>` after a change
  of the document; see `cluster-providers/common/iam/managed-policy.sh`). For it the runner
  also needs, on `arn:aws:iam::<account>:policy/<prefix>-*`: `iam:GetPolicy`,
  `iam:GetPolicyVersion`, `iam:ListPolicyVersions`, `iam:CreatePolicy`,
  `iam:DeletePolicyVersion`, `iam:DeletePolicy`.
- `privileged:post`: the same, plus `iam:PutRolePolicy` on the hub's ACK capability role, and
  what `task enable-capability-logs` calls (`eks:DescribeCapability`, `eks:ListClusters`, the
  CloudWatch Logs delivery and resource-policy actions).
- `privileged:destroy`: `eks:DescribeCluster`, `eks:ListClusters`, `iam:GetRole`,
  `iam:ListAttachedRolePolicies`, `iam:DetachRolePolicy`, `iam:ListRolePolicies`,
  `iam:DeleteRolePolicy`, `iam:DeleteRole`, the scoped-policy actions above (it deletes the
  scoped policy attached to each role it deletes, or under the base name `<role>-scoped`; an
  unattached `<role>-scoped-<8 hex>` is left to a prefix-based sweep), and the CloudWatch Logs `Describe*`/`Delete*`
  delivery actions. It needs `python3` with `boto3`. Bring-your-own roles (`hub.iam.*`,
  `kind-kro-ack`) are not deleted.

A runner role scoped to `<prefix>-cluster-mgmt-*` only is not enough since the
crossplane-provider and Ray roles moved to `privileged:pre`.

## IAM the install host still needs in external mode

`external` removes the IAM role creates, policy attachments and capability-log writes listed
above from the host. The host still needs:

- Read access to those roles: `iam:GetRole`, `iam:ListAttachedRolePolicies`,
  `iam:GetRolePolicy`.
- `eks:CreatePodIdentityAssociation` and `iam:PassRole` on the roles it associates: the
  `<hub>-crossplane-provider` role, or the bring-your-own `hub.iam.crossplaneProviderRoleArn`
  role (`kind-kro-ack`, with `iam:GetRole` on it), and the two Ray roles.
- What the kind bootstrap cluster's ACK and Crossplane controllers do with the host's
  credentials: they create the hub (VPC, EKS cluster, its IAM roles, capabilities). This
  mode does not change that.
- The other AWS calls of the install that are not IAM role or capability-log writes, for
  example Secrets Manager seeding, the Ray S3 bucket, ECR repositories and the S3 CSI addon.
- Teardown, `kind-kro-ack`: under `external`, `task destroy` only tears down Kubernetes. It
  makes no AWS delete: the EKS capabilities, the hub EKS cluster, the `<hub>/config` and
  `<hub>/keycloak` secrets, the leftover sweep (ACK IAM roles and policies included) and the
  extended sweep (IAM roles and policies, VPCs, ...) are left to a stack sweep that runs
  after it with its own role (the destroy prints this list). Without one they remain:
  run `task destroy` again with `privilegedSteps: inline` and credentials allowed to make
  those deletes.
  Then `task privileged:destroy` deletes the roles above.
- Teardown, `kind-crossplane`: `task destroy` still makes its AWS deletes from the host,
  including the platform's remaining `<prefix>-*` IAM roles and policies, and ignores the
  errors of those deletes. Delete what it could not with the runner
  (`task privileged:destroy` for the roles above) or a stack-level sweep.

Not covered: `spokes:seed-provider-identity` (both providers), a manual task, still creates
its roles from wherever it runs. The Ray roles are created and verified in external mode
even when the install does not use Ray.
