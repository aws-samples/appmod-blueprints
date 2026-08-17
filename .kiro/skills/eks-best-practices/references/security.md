# EKS Security Best Practices

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Core security guidance for Amazon EKS clusters — IAM, cluster access, pod identity, pod security, multi-tenancy, secrets management, and data encryption

**For runtime/network security, see:** [Runtime & Network Security](security-runtime-network.md)
**For supply chain, infrastructure, and compliance, see:** [Supply Chain & Compliance](security-supply-chain.md)

---

## Table of Contents

1. [IAM Best Practices](#iam-best-practices)
2. [Cluster Access Management](#cluster-access-management)
3. [Pod Identity and IRSA](#pod-identity-and-irsa)
4. [Pod Security Standards](#pod-security-standards)
5. [Multi-Tenancy Isolation](#multi-tenancy-isolation)
6. [Secrets Management](#secrets-management)
7. [Data Encryption](#data-encryption)

---

## IAM Best Practices

### Cluster IAM Configuration

**Use dedicated IAM roles per cluster:**

- Create a dedicated cluster IAM role with only `eks:*` permissions needed
- Use separate node group IAM roles per workload class
- Enable audit logging for all IAM actions

**Minimum node IAM policies:**
- `AmazonEKSWorkerNodePolicy`
- `AmazonEKS_CNI_Policy` (or use IRSA/Pod Identity for VPC CNI)
- `AmazonEC2ContainerRegistryReadOnly`

Move VPC CNI permissions to IRSA/Pod Identity to reduce node role scope. Never add application-level permissions (S3, DynamoDB) to node roles — use Pod Identity or IRSA instead.

### Instance Metadata Lockdown

**Require IMDSv2 with hop limit 1 to block pods from accessing node credentials:**

```bash
# In launch template user data or EC2NodeClass
aws ec2 modify-instance-metadata-options --instance-id <id> \
  --http-tokens required --http-put-response-hop-limit 1
```

| Hop Limit | Who Can Reach IMDS | Use When |
|-----------|-------------------|----------|
| **1** | Only the node itself | Default — pods blocked from IMDS |
| **2** | Node + pods on the node | Only if apps need instance metadata |

---

## Cluster Access Management

### Cluster Access Manager (Recommended)

Cluster Access Manager is the preferred way to manage access. It eliminates the fragile `aws-auth` ConfigMap in favor of the EKS API, providing full audit trail and IAM integration.

**Two key concepts:**
- **Access Entries** — cluster identity linked to an AWS IAM principal (user or role)
- **Access Policies** — EKS-specific policies providing K8s authorization

```bash
# Create cluster with API authentication (recommended for new clusters)
aws eks create-cluster \
  --name my-cluster \
  --role-arn <CLUSTER_ROLE_ARN> \
  --resources-vpc-config subnetIds=<value> \
  --access-config authenticationMode=API,bootstrapClusterCreatorAdminPermissions=false
```

**Create access entries:**

```bash
# Grant namespace-scoped access
aws eks create-access-entry \
  --cluster-name my-cluster \
  --principal-arn arn:aws:iam::123456789012:role/DevTeam \
  --type STANDARD

aws eks associate-access-policy \
  --cluster-name my-cluster \
  --principal-arn arn:aws:iam::123456789012:role/DevTeam \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy \
  --access-scope type=namespace,namespaces=dev
```

### Authentication Mode Decision

| Mode | Pros | Cons | Use When |
|------|------|------|----------|
| **API** | Single source of truth, auditable, recommended | No aws-auth fallback | New clusters, greenfield |
| **API_AND_CONFIG_MAP** | Backward compatible | Two systems to manage | Migrating from aws-auth |
| **CONFIG_MAP** (legacy) | Familiar | No API audit trail, fragile | Legacy only — migrate away |

**Migration path:** `CONFIG_MAP` -> `API_AND_CONFIG_MAP` -> `API`. These transitions are **irreversible** — you cannot switch from `API` back to `CONFIG_MAP`.

**Available access policies:**
- `AmazonEKSClusterAdminPolicy` -> cluster-admin
- `AmazonEKSAdminPolicy` -> admin (namespace-scopable)
- `AmazonEKSEditPolicy` -> edit (namespace-scopable)
- `AmazonEKSViewPolicy` -> view (namespace-scopable)

### Identify Global STS Endpoint Usage

Use this CloudWatch query to check if clients are using the global STS endpoint (which should be migrated to regional):

```
fields @timestamp, @message, @logStream, stsendpoint
| filter @logStream like /authenticator/
| filter @message like /stsendpoint/
| sort @timestamp desc
| limit 10000
```

If `stsendpoint` equals `sts.amazonaws.com`, the client is using the global endpoint. Migrate to regional (`sts.<region>.amazonaws.com`) for lower latency and better availability.

---

## Pod Identity and IRSA

### Decision Matrix: Pod Identity vs IRSA

| Factor | EKS Pod Identity | IRSA |
|--------|------------------|------|
| **Setup complexity** | Simple — EKS add-on | Moderate — OIDC provider + role trust |
| **Cross-account** | Built-in support | Manual trust policy per account |
| **Session tags** | Automatic (cluster, namespace, SA) | Not available |
| **Role chaining** | Supported | Not supported |
| **EKS version** | 1.24+ | 1.14+ |
| **Fargate support** | Not yet | Supported |
| **Recommendation** | Preferred for new workloads | Use for older clusters or Fargate |

### Pod Identity Setup

```yaml
# 1. Install the Pod Identity Agent add-on
aws eks create-addon \
  --cluster-name my-cluster \
  --addon-name eks-pod-identity-agent

# 2. Create IAM role with Pod Identity trust
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "pods.eks.amazonaws.com" },
    "Action": ["sts:AssumeRole", "sts:TagSession"]
  }]
}

# 3. Create the association
aws eks create-pod-identity-association \
  --cluster-name my-cluster \
  --namespace app-ns \
  --service-account app-sa \
  --role-arn arn:aws:iam::123456789012:role/AppRole
```

### IRSA Setup (when Pod Identity is not available)

```yaml
# 1. Create OIDC provider (one per cluster)
eksctl utils associate-iam-oidc-provider --cluster my-cluster --approve

# 2. Trust policy for the role
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::123456789012:oidc-provider/oidc.eks.region.amazonaws.com/id/CLUSTER_ID"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.region.amazonaws.com/id/CLUSTER_ID:sub": "system:serviceaccount:namespace:sa-name",
        "oidc.eks.region.amazonaws.com/id/CLUSTER_ID:aud": "sts.amazonaws.com"
      }
    }
  }]
}

# 3. Annotate the service account
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: app-ns
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/AppRole
```

- Scope IRSA trust policies to specific namespace:service-account pairs
- Use `StringEquals` (not `StringLike`) for sub conditions
- Never use wildcard `*` in IRSA trust policy conditions
- Don't share service accounts across applications with different privilege needs

---

## Pod Security Standards

### Enforcement with Pod Security Admission (PSA)

**Pod Security Standards levels:**

| Level | Description | Use When |
|-------|-------------|----------|
| **Privileged** | Unrestricted | System namespaces (kube-system), CNI daemonsets |
| **Baseline** | Prevents known privilege escalations | Default for most workloads |
| **Restricted** | Hardened, follows best practices | Security-sensitive workloads |

**Apply via namespace labels:**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # Enforce restricted — reject non-compliant pods
    pod-security.kubernetes.io/enforce: restricted
    # Warn on restricted violations (better UX for Deployments)
    pod-security.kubernetes.io/warn: restricted
    # Audit restricted violations to audit log
    pod-security.kubernetes.io/audit: restricted
```

Using all three modes together is important — `enforce` alone blocks pods silently when applied via Deployments (the Deployment succeeds but pods fail without obvious feedback). Adding `warn` and `audit` surfaces the violations to the user and audit log.

**Recommended rollout strategy:**
1. Start with `warn` + `audit` modes on all namespaces
2. Review warnings in audit logs
3. Fix non-compliant workloads
4. Switch to `enforce` mode

### PSA Exemptions

Configure exemptions for workloads that legitimately need elevated privileges:
- **Usernames** — exempt specific authenticated users
- **RuntimeClassNames** — exempt specific runtime classes
- **Namespaces** — exempt system namespaces (e.g., `kube-system`)

### PAC vs PSA Decision

| Factor | Policy-as-Code (Kyverno, OPA) | Pod Security Admission |
|--------|------------------------------|----------------------|
| **Flexibility** | Highly granular, any resource | 3 levels, pods only |
| **Learning curve** | New policy language | Namespace labels only |
| **Mutation** | Can mutate requests | No mutation |
| **Scope** | Any K8s resource, any action | Pods only |
| **Generation** | Can auto-generate resources | No |
| **CI/CD integration** | CLI tools for pipelines | Limited |
| **Built-in** | Requires installation | Native since K8s 1.25 |

Use PSA when your security posture fits the three standard levels. Use PAC when you need finer control, mutation, non-pod policies, or CI/CD integration.

### Restricted Pod Security Context

```yaml
# Restricted-compliant pod spec
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: app:latest
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
      runAsUser: 1000
      runAsGroup: 1000
```

### Pod Security Rules

- Set `runAsNonRoot: true` on all workloads
- Drop ALL capabilities and add back only what's needed
- Use `readOnlyRootFilesystem: true` where possible
- Set `seccompProfile: RuntimeDefault`
- Never run Docker-in-Docker or mount the Docker socket — use Kaniko, buildah, or CodeBuild instead
- Restrict `hostPath` usage — if necessary, mount as `readOnly: true` and limit allowed prefixes via policy
- Don't enable `privileged: true`, `hostNetwork`, `hostPID`, or `hostIPC` for application workloads
- Set resource requests and limits on every container to prevent DoS and resource contention

### Linux Capabilities Awareness

Containers run as root by default with these capabilities:
`CAP_AUDIT_WRITE, CAP_CHOWN, CAP_DAC_OVERRIDE, CAP_FOWNER, CAP_FSETID, CAP_KILL, CAP_MKNOD, CAP_NET_BIND_SERVICE, CAP_NET_RAW, CAP_SETGID, CAP_SETUID, CAP_SETFCAP, CAP_SETPCAP, CAP_SYS_CHROOT`

Privileged containers inherit ALL host capabilities. Consider adding/dropping specific Linux capabilities before writing seccomp policies — capabilities are coarser but simpler to manage.

---

## Multi-Tenancy Isolation

### Isolation Levels

| Level | Mechanism | Isolation Strength | Overhead |
|-------|-----------|-------------------|----------|
| **Soft** | Namespaces + RBAC + Network Policies | Low | Low |
| **Medium** | + Resource Quotas + Pod Security + OPA/Kyverno | Medium | Medium |
| **Hard** | Separate node groups per tenant | High | High |
| **Full** | Separate clusters per tenant | Complete | Highest |

### Namespace-Level Isolation Checklist

For each tenant namespace, apply:
1. **RBAC** — Namespace-scoped roles, no cluster-admin
2. **Network policies** — Default deny + explicit allow rules
3. **Resource quotas** — CPU, memory, pod count limits
4. **Limit ranges** — Default/max container resource limits
5. **Pod security** — PSA labels at baseline or restricted level
6. **Service account** — Disable automount of default SA token

```yaml
# Resource quota per tenant namespace
apiVersion: v1
kind: ResourceQuota
metadata:
  name: tenant-quota
  namespace: tenant-a
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
    services: "10"
    persistentvolumeclaims: "20"
```

### ArgoCD-Managed Tenants

Tenants can be managed through ArgoCD using a directory-based ApplicationSet pattern.

**How It Works:**

1. Create a directory per tenant under a `tenants/workloads/` path:

```
tenants/workloads/
├── team-alpha/
│   ├── namespace.yaml
│   ├── resource-quota.yaml
│   └── network-policy.yaml
└── team-beta/
    ├── namespace.yaml
    ├── resource-quota.yaml
    └── network-policy.yaml
```

2. The ApplicationSet uses a Git directory generator to discover each tenant directory and create an ArgoCD Application for it.

3. ArgoCD applies the manifests with automated sync, prune, and self-heal enabled.

**Example Tenant Manifest:**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-alpha
  labels:
    pod-security.kubernetes.io/enforce: baseline
    tenant: team-alpha
```

Cross-account IAM roles for ArgoCD-managed tenants are still created by Terraform or managed externally, since ArgoCD cannot create IAM resources.

### Cross-Account IAM

When a tenant specifies an `account_id`, the tenant module creates two IAM roles:

**Admin Role:**

- **Name**: `<cluster>-<tenant>-admin`
- **Trust policy**: Allows `sts:AssumeRole` from `arn:aws:iam::<account_id>:root`
- **Condition**: Requires `sts:ExternalId` matching the tenant key (e.g., `team-beta`)
- **EKS access**: `AmazonEKSEditPolicy` scoped to the tenant's namespace

**Readonly Role:**

- **Name**: `<cluster>-<tenant>-readonly`
- **Trust policy**: Same as admin role (same account, same ExternalId)
- **EKS access**: `AmazonEKSViewPolicy` scoped to the tenant's namespace

**Usage from the Tenant Account:**

The tenant's AWS account assumes the role with the external ID:

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::<cluster-account>:role/my-eks-cluster-team-beta-admin \
  --role-session-name team-beta-session \
  --external-id team-beta
```

Then configure kubectl with the assumed credentials:

```bash
aws eks update-kubeconfig --name my-eks-cluster --region us-east-1 --role-arn arn:aws:iam::<cluster-account>:role/my-eks-cluster-team-beta-admin
```

The ExternalId requirement mitigates confused-deputy attacks by ensuring only the intended tenant account can assume the role.

---

## Secrets Management

### Decision Matrix

| Approach | Complexity | Rotation | Use When |
|----------|-----------|----------|----------|
| **K8s Secrets + envelope encryption** | Low | Manual | Simple apps, low secret count |
| **Secrets Store CSI Driver** | Medium | Auto-sync | Mount secrets as volumes |
| **External Secrets Operator (ESO)** | Medium | Configurable | Sync to K8s Secrets, GitOps-friendly |
| **Sealed Secrets (Bitnami)** | Low | Manual | Encrypt secrets for Git storage |
| **Direct SDK calls** | Low | N/A | Application handles own secret retrieval |

### Enable Envelope Encryption

```bash
# Enable KMS encryption for Kubernetes secrets
aws eks associate-encryption-config \
  --cluster-name my-cluster \
  --encryption-config '[{
    "resources": ["secrets"],
    "provider": {
      "keyArn": "arn:aws:kms:region:account:key/key-id"
    }
  }]'
```

### External Secrets Operator (Recommended for GitOps)

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: production
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: app-secrets
    creationPolicy: Owner
  data:
  - secretKey: db-password
    remoteRef:
      key: prod/app/database
      property: password
```

### Audit Kubernetes Secrets Access

Enable audit logging and use CloudWatch Logs Insights to monitor secret access:

```
# Count secret accesses by secret name
fields @timestamp, @message
| sort @timestamp desc
| limit 100
| stats count(*) by objectRef.name as secret
| filter verb="get" and objectRef.resource="secrets"

# Show who accessed which secrets
fields @timestamp, @message
| sort @timestamp desc
| limit 100
| filter verb="get" and objectRef.resource="secrets"
| display objectRef.namespace, objectRef.name, user.username, responseStatus.code
```

### Secrets Best Practices

- Enable envelope encryption with KMS for etcd secrets
- Use ESO or Secrets Store CSI for production workloads
- Set `refreshInterval` for automatic rotation pickup
- **Use volume mounts instead of environment variables** — env var values can appear in logs, `kubectl describe`, and crash dumps. Secrets mounted as volumes use tmpfs (RAM-backed) and are removed when the pod is deleted
- Use separate namespaces to isolate secrets from different applications — secrets in a namespace are accessible to all pods in that namespace
- Don't store secrets in ConfigMaps
- Don't commit secrets to Git (even base64-encoded)
- Don't rely on default Kubernetes encryption (base64 only, not encrypted at rest)

### Secrets Operating Models

Choose an operating model based on team structure, compliance requirements, and existing investment:

| Factor | Model A: Centralized External Vault | Model B: Centralized AWS Secrets Manager | Model C: Tenant-Managed Secrets Manager |
|--------|-------------------------------------|------------------------------------------|----------------------------------------|
| **Secret store** | CyberArk, HashiCorp Vault | AWS Secrets Manager (platform-managed) | AWS Secrets Manager (per-tenant account) |
| **K8s integration** | ESO with Vault provider | ESO or Secrets Store CSI with AWS provider | ESO with cross-account IAM |
| **Who creates secrets** | Security team or vault admins | Platform team | Tenant teams |
| **Who rotates secrets** | Vault auto-rotation or security team | Lambda rotation function (platform team) | Tenant teams |
| **Compliance** | Strong — centralized audit, enterprise-grade | Good — CloudTrail + Secrets Manager audit | Per-tenant — each tenant owns compliance |
| **Best for** | Enterprise with existing vault, strict compliance | AWS-native platform, centralized operations | Federated teams, regulatory tenant isolation |

**Model A: Centralized External Vault**
- Enterprise vault (CyberArk, HashiCorp Vault) is single source of truth
- ESO syncs secrets from vault to Kubernetes Secrets
- Platform team manages ESO `ClusterSecretStore` pointing to vault
- Tenant teams reference secrets via `ExternalSecret` in their namespace

**Model B: Centralized AWS Secrets Manager**
- Platform team creates and manages secrets in a central AWS account
- ESO `ClusterSecretStore` configured with cross-account IAM role
- Secrets organized by path convention: `/<environment>/<tenant>/<secret-name>`
- Lambda rotation functions managed by platform team

**Model C: Tenant-Managed Secrets Manager**
- Each tenant manages secrets in their own AWS account
- ESO `SecretStore` (namespace-scoped) per tenant with tenant's IAM role
- Platform provides ESO infrastructure; tenants own secret lifecycle
- Cross-account access via Pod Identity or IRSA

### Secret Lifecycle

**Promotion workflow:**

```
Developer creates secret in dev
     |
     v
Dev Secrets Manager: /<dev>/<tenant>/<secret>
     | (manual or automated promotion)
     v
Staging Secrets Manager: /<staging>/<tenant>/<secret>
     | (approval gate — change management)
     v
Prod Secrets Manager: /<prod>/<tenant>/<secret>
     |
     v
ESO syncs to K8s Secret in target namespace
```

**Rotation strategies by model:**

| Model | Rotation Method | Frequency | Automation |
|-------|----------------|-----------|------------|
| **A (External Vault)** | Vault dynamic secrets or scheduled rotation | Per secret policy | Vault-managed |
| **B (Centralized SM)** | Secrets Manager Lambda rotation | 30-90 days | Platform team configures |
| **C (Tenant-Managed SM)** | Tenant configures rotation | Per tenant policy | Tenant-managed |

**RACI Matrix:**

| Activity | Model A | Model B | Model C |
|----------|---------|---------|---------|
| **Create secrets** | Security team (R), Tenant (C) | Platform team (R), Tenant (C) | Tenant (R/A) |
| **Rotate secrets** | Vault / Security team (R) | Platform team (R) | Tenant (R/A) |
| **Audit access** | Security team (R/A) | Platform team (R/A) | Tenant (R), Platform (A) |
| **Delete secrets** | Security team (R), Tenant (I) | Platform team (R), Tenant (C) | Tenant (R/A) |
| **Manage ESO infra** | Platform team (R/A) | Platform team (R/A) | Platform team (R/A) |

---

## Data Encryption

### Encryption at Rest

| Component | Mechanism | Default |
|-----------|-----------|---------|
| **etcd (secrets)** | KMS envelope encryption | Off — must enable |
| **EBS volumes** | EBS encryption with KMS | Configure in StorageClass |
| **EFS** | Encryption at rest | Configure at file system creation |
| **FSx for Lustre** | Service-managed key or CMK | Service-managed by default |
| **Fargate ephemeral** | AES-256 | On by default (since May 2020) |

**EBS CSI StorageClass with encryption:**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-gp3
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  kmsKeyId: arn:aws:kms:region:account:key/key-id
volumeBindingMode: WaitForFirstConsumer
```

**EFS with encryption in transit:**

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: efs-pv
spec:
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  mountOptions:
    - tls    # Enables encryption in transit
  csi:
    driver: efs.csi.aws.com
    volumeHandle: <file_system_id>
```

**Use EFS access points** to simplify shared dataset access with different POSIX file permissions. Each EFS file system supports up to 120 access points.

### CMK Rotation

Configure KMS to automatically rotate your CMKs. This rotates keys once a year while saving old keys indefinitely so existing data can still be decrypted.

### Encryption in Transit

- EKS API server: TLS by default
- Pod-to-pod: Use service mesh (Istio mTLS) or VPC Lattice
- Application to AWS services: HTTPS endpoints, VPC endpoints for private traffic
- Nitro instances (C5n, M5n, R5n, etc.): Traffic between them is automatically encrypted

**For runtime security, network policies, and encryption in transit details, see:** [Runtime & Network Security](security-runtime-network.md)

---

**Sources:**
- [AWS EKS Best Practices Guide — Security](https://docs.aws.amazon.com/eks/latest/best-practices/security.html)
- [AWS EKS Best Practices Guide — IAM](https://docs.aws.amazon.com/eks/latest/best-practices/identity-and-access-management.html)
- [AWS EKS Best Practices Guide — Pod Security](https://docs.aws.amazon.com/eks/latest/best-practices/pod-security.html)
- [AWS EKS Best Practices Guide — Data Encryption](https://docs.aws.amazon.com/eks/latest/best-practices/data-encryption-and-secrets-management.html)
