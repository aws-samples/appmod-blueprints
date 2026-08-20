# Data Encryption & Secrets Management

A first-class security area in the AWS EKS Best Practices guide. Two concerns: **encryption at rest / in transit** and **secrets management**.

## Encryption at rest — what EKS does by default vs what you add

- **Default envelope encryption of ALL Kubernetes API data.** On **Kubernetes 1.28+**, every EKS cluster has **default envelope encryption enabled with no action required**, using **KMS provider v2** and an **AWS-owned KMS key**. This extends earlier Secrets-only encryption to all Kubernetes API data (Secrets, ConfigMaps, etc.) before it's persisted to etcd. It does **not** apply to data on nodes or EBS volumes. Reference: [Default envelope encryption for all Kubernetes API data](https://docs.aws.amazon.com/eks/latest/userguide/envelope-encryption.html).
- **etcd disk encryption is independent and always on.** All etcd data is encrypted at the disk level (EBS) for every EKS cluster regardless of Kubernetes version — distinct from the envelope-encryption layer above.
- **Bring your own CMK (optional, recommended for compliance).** You can supply a **customer-managed KMS key (CMK)** as the key-encryption-key (KEK) for control over rotation, audit (CloudTrail), and key policy. For existing clusters that previously enabled Secrets envelope encryption with a CMK, that same CMK becomes the KEK for all API data.
- **Storage-layer encryption (workload data).** EBS, EFS, and FSx for Lustre all support encryption at rest with a service-managed key or a CMK. Use **CMKs for EBS/EFS/FSx under compliance regimes**. EFS and FSx also support in-transit encryption (FSx for Lustre by default; EFS via the `tls` mount option). Fargate ephemeral-volume data is AES-256 encrypted by default.
- Rotate CMKs automatically (KMS annual rotation retains old key material so old data still decrypts).

> **Operational risk of a CMK (surface this — it's a real failure mode).** Once a CMK is the envelope-encryption KEK:
> - **Disabling it degrades the cluster.** The API server keeps working until it restarts (cached DEK), then fails to boot with `KMS_KEY_DISABLED`. You get a **~30-day window** to re-enable before EKS force-auto-upgrades the degraded cluster (recovery then not guaranteed).
> - **Deleting it makes the cluster unrecoverable.** `KMS_KEY_NOT_FOUND` / `KMS_GRANT_REVOKED` are terminal.
> - **Mitigation:** least-privilege IAM on KMS key operations + a CloudWatch alarm on key disable/delete; treat the CMK as a cluster-critical dependency. Same CMK can serve multiple clusters in-region — but a disable then has a wider blast radius.

## Encryption in transit
- TLS for all in-cluster API traffic (managed). For **east-west workload mTLS**, use a service mesh (Istio/Linkerd/Cilium) or VPC Lattice — see [workload-security.md](workload-security.md).
- Storage in-transit: FSx for Lustre (default), EFS (`tls` mount option).

## Secrets management — the hierarchy

Kubernetes Secrets are stored in etcd as **base64-encoded** strings (not encryption) and are readable by any pod in the namespace and by the kubelet/node authorizer on the node. Even with envelope encryption protecting etcd at rest, the **access-control risk remains** — so for production, prefer an external secret store:

| Option | What it is | When |
|---|---|---|
| **AWS Secrets Manager + Secrets Store CSI Driver + ASCP** | AWS-canonical; the AWS provider supports Secrets Manager **and** SSM Parameter Store; fine-grained IAM, encryption, automatic rotation, optional sync to K8s Secrets. Uses the pod's Pod Identity/IRSA role to fetch. | Default for AWS-native shops |
| **External Secrets Operator (ESO)** | OSS; *copies* secrets from a backend (incl. Secrets Manager) into Kubernetes Secrets, Kubernetes-native interaction | OSS-first; GitOps with K8s-Secret semantics |
| **HashiCorp Vault** | Multi-cloud; advanced engines (dynamic creds, PKI) | Existing Vault investment / multi-cloud |
| **Sealed Secrets / SOPS** | Asymmetric encryption so encrypted secrets are safe in Git | GitOps where secrets live in the repo |
| **Plain Kubernetes Secrets** | base64 in etcd (envelope-encrypted at rest on 1.28+) | **Not recommended alone for production** |

Additional AWS-recommended secret hygiene: **mount secrets as volumes, not env vars** (env values leak into logs; volume mounts are tmpfs, removed on pod deletion); **separate namespaces** to isolate secrets across apps; **rotate** (Kubernetes doesn't auto-rotate — use an external store); **audit secret access** via the EKS audit log (e.g. a CloudWatch metric filter `{($.verb="get") && ($.objectRef.resource="secrets")}` — note the resource is **`secrets`** plural, matching the API path; the singular form silently matches nothing).

## Shared responsibility (encryption & secrets)

| AWS manages | Customer manages |
|---|---|
| Default envelope encryption (KMS v2, AWS-owned key); etcd disk encryption; KMS service; Secrets Manager + ASCP provider | Choosing/guarding a CMK (and its blast radius); CMK rotation policy; external secret store choice + IAM; volume-mount vs env; namespace isolation; secret-access auditing |

## Sources
- [Default envelope encryption for all Kubernetes API data](https://docs.aws.amazon.com/eks/latest/userguide/envelope-encryption.html) · [EKS Best Practices: Data encryption & secrets management](https://docs.aws.amazon.com/eks/latest/best-practices/data-encryption-and-secrets-management.html)
- [Using EKS encryption provider support for defense in depth](https://aws.amazon.com/blogs/containers/using-eks-encryption-provider-support-for-defense-in-depth/) · [ASCP + Secrets Store CSI Driver](https://docs.aws.amazon.com/secretsmanager/latest/userguide/integrating_csi_driver.html)
- [AWS KMS](https://aws.amazon.com/kms/) · [external-secrets](https://github.com/external-secrets/external-secrets) · [Cluster health FAQs & error codes](https://docs.aws.amazon.com/eks/latest/userguide/troubleshooting.html)
