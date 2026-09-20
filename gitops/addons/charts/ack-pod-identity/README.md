# ack-pod-identity

ACK-managed IAM roles, IAM policies and EKS Pod Identity Associations for platform
addons. This is the **kro-ack** counterpart of `crossplane-pod-identity`.

Design and evidence: `docs/platform/ack-pod-identity-design.md`.

## Why two charts

The repo models the crossplane / kro-ack duality as one chart per backend
(`abstractions/crossplane` vs `abstractions/kro`, `clusters-crossplane.yaml` vs
`clusters-kro.yaml`). This chart follows that convention. Only the rendered CRD kinds
differ:

| | crossplane-pod-identity | ack-pod-identity |
|--|--|--|
| Role | `iam.aws.upbound.io/Role` | `iam.services.k8s.aws/Role` |
| Policy | `iam.aws.upbound.io/Policy` | `iam.services.k8s.aws/Policy` |
| Policy attach | `RolePolicyAttachment` CR | `Role.spec.policyRefs` |
| Association | `eks.aws.upbound.io/PodIdentityAssociation` | `eks.services.k8s.aws/PodIdentityAssociation` |

Registry selection is mutually exclusive, so a cluster gets exactly one of the two:

- `pod_identities` → `provider NotIn ["kro-ack"]`
- `ack_pod_identities` → `provider In ["kro-ack"]`

## Identities

Only 4: `eso`, `lbc`, `external-dns`, `keycloak`. Deliberately absent:

- `adot-collector`, `cloudwatch-observability`, `cni-metrics-helper`,
  `kyverno-policy-reporter` — no consumer on any cluster (disabled or the namespace does
  not exist), so they are dead code rather than migration targets.
- `crossplane-iam-provider` / `crossplane-eks-provider` — genuine bootstrap
  chicken-and-egg; they stay in the `EksCluster` RGD.

`values.yaml` was **generated** from `crossplane-pod-identity/values.yaml` so the IAM
policy documents are identical by construction. Keep them that way:

```bash
task test-pod-identity-drift
```

## Adoption (this is what makes migration safe)

Every resource carries `adoption-policy: adopt-or-create` and
`deletion-policy: retain`, so the chart takes ownership of resources that already exist
(created by the RGD, Terraform, or the kind bootstrap) instead of failing on create, and
never deletes a live AWS resource on prune.

The required adoption inputs differ per resource, which is easy to get wrong:

| Resource | Keyed by | `adoption-fields` needed? |
|---|---|---|
| Policy | ARN | **Yes** — ACK cannot derive the ARN from `spec.name`; without it, create is attempted and fails 409 `EntityAlreadyExists` |
| Role | name | No — derived from `spec.name` |
| PodIdentityAssociation | clusterName + namespace + serviceAccount | No — and none is possible, `associationID` is AWS-generated |

The PodIdentityAssociation behaviour was verified empirically (adopted a pre-created
association by ns+SA, same `associationID`, no duplicate); see the design doc.

## Namespace and ACK credentials

CRs are applied to a namespace named after the **target cluster**, on the **hub** (where
the ACK capability reconciles), matching the `EksCluster` RGD convention.

ACK resolves which IAM role to assume per namespace via `IAMRoleSelector` (CARM). Without
a selector covering the namespace for both `iam.services.k8s.aws` and
`eks.services.k8s.aws`, the CRs are created but **never reconciled** — the failure mode is
silence, not an error.

**INVARIANT: every cluster running this addon must appear in `multi-acct`'s `clusters` map.**
`multi-acct` is the sole owner of `IAMRoleSelector`; this chart deliberately creates none.
It briefly shipped its own as a stopgap while the hub was missing from that map, but that
duplicated ownership: two selectors with an identical `(namespace, group)` scope put the ACK
controller in an infinite reconcile loop (empty `status{}`, zero AWS API calls, no events) —
see issue #813. Adding a cluster to `multi-acct` also gives it the `ec2` and
`secretsmanager` selectors that an on-hub `EksCluster` instance needs (issue #775).

## Sync ordering

| Wave | Resource |
|---|---|
| -20 / -19 | PreSync CRD-wait hook (ACK CRDs Established) |
| -5 | IAMRoleSelectors |
| -3 | Policy |
| -2 | Role (references Policy) |
| -1 | PodIdentityAssociation (references Role) |

The app itself is at registry wave 4, before its consumers (lbc / external-dns / keycloak
at wave 5).
