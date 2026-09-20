# Module: Security

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect security posture - IAM model, Pod Security, policy engines, secrets management

## Table of Contents

- [Prerequisites](#prerequisites)
- [Detection Strategy](#detection-strategy)
- [Detection Commands](#detection-commands)
  - [1. IAM Model Detection](#1-iam-model-detection)
  - [2. Pod Security Standards (PSS)](#2-pod-security-standards-pss)
  - [3. Policy Engine Detection](#3-policy-engine-detection)
  - [4. Secrets Management](#4-secrets-management)
  - [5. Image Security](#5-image-security)
  - [6. RBAC Summary](#6-rbac-summary)
- [Output Schema](#output-schema)
- [Edge Cases](#edge-cases)
- [Recommendations Based on Findings](#recommendations-based-on-findings)

---

## Prerequisites

- **Cluster name required:** Yes
- **MCP tools used:** `describe_eks_resource`, `list_k8s_resources`, `list_eks_resources`
- **CLI fallback:** `aws eks`, `kubectl`

---

## Detection Strategy

Security posture covers multiple dimensions:

```
1. IAM Model         -> Pod Identity vs IRSA vs node role
2. Pod Security      -> PSA labels, PSS enforcement
3. Policy Engine     -> Kyverno, OPA Gatekeeper, or none
4. Secrets           -> ESO, Secrets Store CSI, native secrets
5. Image Security    -> ECR scanning, admission control
6. RBAC              -> Role/ClusterRole analysis
```

---

## Detection Commands

### 1. IAM Model Detection

Detect which IAM model the cluster uses for workload authentication. This determines how pods access AWS services:
- **Pod Identity** (recommended): AWS-native, simplest to manage, supports cross-account without OIDC providers
- **IRSA**: Established pattern using OIDC, widely adopted but more complex setup
- **Node role**: Legacy approach where all pods share the node's IAM role - security risk

**Pod Identity:**

**MCP:**
```
describe_eks_resource(
  resource_type="addon",
  cluster_name="<cluster-name>",
  resource_name="eks-pod-identity-agent"
)
```

**CLI:**
```bash
# Check if Pod Identity agent is installed
aws eks describe-addon --cluster-name <cluster-name> --addon-name eks-pod-identity-agent 2>/dev/null

# List Pod Identity associations
aws eks list-pod-identity-associations --cluster-name <cluster-name> \
  --query 'associations[*].{namespace:namespace,serviceAccount:serviceAccount,roleArn:roleArn}'
```

**Example output (Pod Identity enabled):**
```json
{
  "addon": {
    "addonName": "eks-pod-identity-agent",
    "status": "ACTIVE",
    "addonVersion": "v1.3.4-eksbuild.1"
  }
}
```

**IRSA (IAM Roles for Service Accounts):**

**MCP:**
```
list_k8s_resources(
  cluster_name="<cluster-name>",
  kind="ServiceAccount",
  api_version="v1"
)
```

**CLI:**
```bash
# Find service accounts with IRSA annotation
kubectl get sa -A -o json | jq -r '
  .items[] | 
  select(.metadata.annotations["eks.amazonaws.com/role-arn"] != null) |
  {
    namespace: .metadata.namespace,
    name: .metadata.name,
    role: .metadata.annotations["eks.amazonaws.com/role-arn"]
  }'
```

**Example output (IRSA configured):**
```json
{
  "namespace": "kube-system",
  "name": "aws-load-balancer-controller",
  "role": "arn:aws:iam::123456789012:role/AWSLoadBalancerControllerRole"
}
{
  "namespace": "external-secrets",
  "name": "external-secrets",
  "role": "arn:aws:iam::123456789012:role/ExternalSecretsRole"
}
```

**Determine IAM Model:**
```
if pod_identity_associations > 0:
    if irsa_service_accounts > 0:
        model = "mixed"
    else:
        model = "Pod Identity"
elif irsa_service_accounts > 0:
    model = "IRSA"
else:
    model = "node-role"  # Using node IAM role (not recommended)
```

### 2. Pod Security Standards (PSS)

Check Pod Security Admission (PSA) enforcement. PSA replaced PodSecurityPolicy in Kubernetes 1.25+. Use this detection to understand which namespaces enforce security constraints on pods:
- **restricted**: Heavily restricted, follows hardening best practices
- **baseline**: Minimally restrictive, prevents known privilege escalations
- **privileged**: Unrestricted (default if no label set)

**CLI:**
```bash
# Check PSA labels on namespaces
kubectl get ns -o json | jq -r '
  .items[] |
  {
    namespace: .metadata.name,
    enforce: .metadata.labels["pod-security.kubernetes.io/enforce"],
    warn: .metadata.labels["pod-security.kubernetes.io/warn"],
    audit: .metadata.labels["pod-security.kubernetes.io/audit"]
  } |
  select(.enforce != null or .warn != null or .audit != null)'
```

**Example output (PSA configured):**
```json
{
  "namespace": "production",
  "enforce": "restricted",
  "warn": "restricted",
  "audit": "restricted"
}
{
  "namespace": "monitoring",
  "enforce": "baseline",
  "warn": "restricted",
  "audit": null
}
```

**Summary:**
```bash
# Count namespaces by enforcement level
kubectl get ns -o json | jq -r '
  .items | 
  group_by(.metadata.labels["pod-security.kubernetes.io/enforce"]) |
  map({level: .[0].metadata.labels["pod-security.kubernetes.io/enforce"] // "none", count: length})'
```

### 3. Policy Engine Detection

Identify if a policy engine enforces admission control beyond PSA. Policy engines provide fine-grained control over what resources can be created:
- **Kyverno**: Kubernetes-native, policies written in YAML, easier learning curve
- **OPA Gatekeeper**: Uses Rego language, more powerful but steeper learning curve
- Running both adds complexity - recommend consolidating to one

**Kyverno:**
```bash
# Check for Kyverno deployment
kubectl get deploy -n kyverno kyverno-admission-controller 2>/dev/null

# Get Kyverno version
kubectl get deploy -n kyverno -o json 2>/dev/null | \
  jq -r '.items[0].spec.template.spec.containers[0].image'

# Count policies
kubectl get clusterpolicies.kyverno.io 2>/dev/null | wc -l
kubectl get policies.kyverno.io -A 2>/dev/null | wc -l
```

**Example output (Kyverno detected):**
```
NAME                            READY   AGE
kyverno-admission-controller    1/1     45d

# Version: ghcr.io/kyverno/kyverno:v1.11.4
# ClusterPolicies: 12
# Policies: 3
```

**OPA Gatekeeper:**
```bash
# Check for Gatekeeper deployment
kubectl get deploy -n gatekeeper-system gatekeeper-controller-manager 2>/dev/null

# Get Gatekeeper version
kubectl get deploy -n gatekeeper-system -o json 2>/dev/null | \
  jq -r '.items[0].spec.template.spec.containers[0].image'

# Count constraints
kubectl get constraints 2>/dev/null | wc -l
kubectl get constrainttemplates 2>/dev/null | wc -l
```

**Example output (Gatekeeper detected):**
```
NAME                                READY   AGE
gatekeeper-controller-manager       1/1     90d

# Version: openpolicyagent/gatekeeper:v3.15.0
# ConstraintTemplates: 8
# Constraints: 15
```

### 4. Secrets Management

Determine how the cluster manages sensitive data. Native Kubernetes secrets are base64-encoded (not encrypted at rest by default), so most production clusters use external solutions:
- **External Secrets Operator (ESO)**: Syncs secrets from AWS Secrets Manager/Parameter Store to K8s secrets
- **Secrets Store CSI Driver**: Mounts secrets directly as volumes, avoids creating K8s Secret objects
- **KMS encryption**: Encrypts etcd secrets at rest (cluster-level, not a secrets solution itself)

**External Secrets Operator (ESO):**
```bash
# Check for ESO deployment
kubectl get deploy -n external-secrets external-secrets 2>/dev/null

# Count ExternalSecrets
kubectl get externalsecrets.external-secrets.io -A 2>/dev/null | wc -l

# Check SecretStores
kubectl get secretstores.external-secrets.io -A 2>/dev/null | head -5
kubectl get clustersecretstores.external-secrets.io 2>/dev/null | head -5
```

**Example output (ESO detected):**
```
NAME               READY   AGE
external-secrets   1/1     60d

# ExternalSecrets: 24
# SecretStores (namespaced): 4
# ClusterSecretStores: 1
```

**Secrets Store CSI Driver:**
```bash
# Check for Secrets Store CSI
kubectl get daemonset -n kube-system secrets-store-csi-driver 2>/dev/null

# Check for AWS provider
kubectl get daemonset -n kube-system secrets-store-csi-driver-provider-aws 2>/dev/null

# Count SecretProviderClasses
kubectl get secretproviderclasses -A 2>/dev/null | wc -l
```

**Example output (Secrets Store CSI detected):**
```
NAME                                      DESIRED   CURRENT   READY   AGE
secrets-store-csi-driver                  3         3         3       45d
secrets-store-csi-driver-provider-aws     3         3         3       45d

# SecretProviderClasses: 8
```

**KMS Encryption:**
```bash
# Check if secrets encryption is enabled
aws eks describe-cluster --name <cluster-name> \
  --query 'cluster.encryptionConfig[*].{resources:resources,keyArn:provider.keyArn}'
```

**Example output (KMS encryption enabled):**
```json
[
  {
    "resources": ["secrets"],
    "keyArn": "arn:aws:kms:us-west-2:123456789012:key/a1b2c3d4-5678-90ab-cdef-EXAMPLE11111"
  }
]
```

### 5. Image Security

Assess container image security posture. Check whether images come from trusted registries and if admission policies enforce image requirements:
- **ECR usage**: Private registry with built-in vulnerability scanning
- **Admission policies**: Kyverno/Gatekeeper rules that enforce image signing, registries, or tags

**ECR Scanning:**
```bash
# Check if ECR is used (look for ECR URLs in pods)
kubectl get pods -A -o json | jq -r '
  .items[].spec.containers[].image | 
  select(contains(".ecr.") or contains("ecr.aws"))' | sort -u | head -10
```

**Example output (ECR images found):**
```
123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:v1.2.3
123456789012.dkr.ecr.us-west-2.amazonaws.com/api-service:latest
public.ecr.aws/aws-observability/aws-otel-collector:v0.35.0
```

**Image Policy Enforcement:**
```bash
# Check for image policies in Kyverno
kubectl get clusterpolicies.kyverno.io -o json 2>/dev/null | \
  jq -r '.items[] | select(.spec.rules[].match.resources.kinds[] == "Pod") | .metadata.name'

# Check for Gatekeeper image constraints
kubectl get constraints -o json 2>/dev/null | \
  jq -r '.items[] | select(.spec.match.kinds[].kinds[] == "Pod") | .metadata.name'
```

### 6. RBAC Summary

Analyze RBAC configuration to identify overly permissive roles. Focus on:
- **Wildcard permissions**: Roles with `*` on resources and verbs grant unlimited access
- **cluster-admin bindings**: Should be minimal and well-documented
- High role/binding counts may indicate RBAC sprawl needing cleanup

```bash
# Count ClusterRoles and ClusterRoleBindings
kubectl get clusterroles | wc -l
kubectl get clusterrolebindings | wc -l

# Find overly permissive ClusterRoles
kubectl get clusterroles -o json | jq -r '
  .items[] |
  select(.rules[]?.resources[]? == "*" and .rules[]?.verbs[]? == "*") |
  .metadata.name'

# Check for cluster-admin bindings
kubectl get clusterrolebindings -o json | jq -r '
  .items[] |
  select(.roleRef.name == "cluster-admin") |
  {name: .metadata.name, subjects: .subjects}'
```

**Example output (RBAC findings):**
```
# ClusterRoles: 87
# ClusterRoleBindings: 52

# Overly permissive roles:
super-admin-role
legacy-operator-role

# cluster-admin bindings:
{
  "name": "cluster-admin-binding",
  "subjects": [
    {"kind": "User", "name": "admin@example.com"}
  ]
}
{
  "name": "eks-console-dashboard-full-access-binding",
  "subjects": [
    {"kind": "Group", "name": "eks-console-dashboard-full-access-group"}
  ]
}
```

---

## Output Schema

```yaml
security:
  iam:
    model: string           # Pod Identity | IRSA | mixed | node-role
    pod_identity:
      enabled: bool
      associations: int     # Count of Pod Identity associations
    irsa:
      enabled: bool
      service_accounts: int # Count of SAs with IRSA annotation
      
  pod_security:
    psa_enabled: bool
    enforcement:
      restricted: int       # Namespaces enforcing restricted
      baseline: int         # Namespaces enforcing baseline
      privileged: int       # Namespaces enforcing privileged
      none: int            # Namespaces with no PSA labels
      
  policy_engine:
    tool: string           # kyverno | gatekeeper | both | none
    kyverno:
      detected: bool
      version: string
      cluster_policies: int
      policies: int
    gatekeeper:
      detected: bool
      version: string
      constraint_templates: int
      constraints: int
      
  secrets:
    approach: string       # eso | secrets-store-csi | native | mixed
    kms_encryption: bool
    kms_key_arn: string
    external_secrets:
      detected: bool
      external_secrets: int
      secret_stores: int
    secrets_store_csi:
      detected: bool
      aws_provider: bool
      secret_provider_classes: int
      
  image_security:
    ecr_used: bool
    private_registries: list
    admission_policies: bool  # Image policies exist
    
  rbac:
    cluster_roles: int
    cluster_role_bindings: int
    overly_permissive_roles: list
    cluster_admin_bindings: list
```

---

## Edge Cases

### Mixed IAM Model

Many clusters transition from IRSA to Pod Identity gradually:
- Note both are in use
- List which service accounts use which method
- Recommend completing migration

### No PSA Labels

Namespaces without PSA labels run in unrestricted mode:
- Flag security risk
- Recommend at minimum `baseline` enforcement

### Multiple Policy Engines

Some clusters run both Kyverno and Gatekeeper:
- Note complexity risk
- Check for conflicting policies

### GuardDuty Integration

```bash
# Check if GuardDuty EKS Runtime Monitoring is enabled
aws guardduty list-detectors --query 'DetectorIds'
# Then check features for each detector
aws guardduty get-detector --detector-id <id> \
  --query 'Features[?Name==`EKS_RUNTIME_MONITORING`]'
```

### Admission Webhooks

Identify validating and mutating admission webhooks to understand what policies are enforced at admission time. Webhooks can block or modify resources before they're persisted.

**CLI:**
```bash
# List validating webhooks (exclude system webhooks)
kubectl get validatingwebhookconfigurations -o json | jq '[
  .items[] | 
  select(.metadata.name | test("^(eks|vpc-resource|aws-)") | not) |
  {name: .metadata.name, webhooks: [.webhooks[].name], failurePolicy: .webhooks[0].failurePolicy}
]'

# List mutating webhooks (exclude system webhooks)
kubectl get mutatingwebhookconfigurations -o json | jq '[
  .items[] | 
  select(.metadata.name | test("^(eks|vpc-resource|aws-)") | not) |
  {name: .metadata.name, webhooks: [.webhooks[].name], failurePolicy: .webhooks[0].failurePolicy}
]'

# Count all webhooks
kubectl get validatingwebhookconfigurations --no-headers | wc -l
kubectl get mutatingwebhookconfigurations --no-headers | wc -l
```

**Example output (validating webhooks):**
```json
[
  {
    "name": "kyverno-resource-validating-webhook-cfg",
    "webhooks": ["validate.kyverno.svc"],
    "failurePolicy": "Fail"
  },
  {
    "name": "cert-manager-webhook",
    "webhooks": ["webhook.cert-manager.io"],
    "failurePolicy": "Fail"
  }
]
```

**Notable webhooks to look for:**
- `kyverno-*` - Kyverno policy enforcement
- `gatekeeper-*` - OPA Gatekeeper constraints
- `cert-manager-webhook` - Certificate management
- `aws-load-balancer-webhook` - ALB controller validation

---

## Recommendations Based on Findings

| Finding | Recommendation |
|---------|---------------|
| node-role IAM model | Migrate to Pod Identity for least-privilege |
| IRSA only | Consider Pod Identity for simpler management |
| No PSA labels | Apply at least `baseline` enforcement |
| No policy engine | Consider Kyverno for policy-as-code |
| KMS encryption not enabled | Enable for compliance requirements |
| No secrets solution | Implement ESO or Secrets Store CSI |
| Overly permissive RBAC | Review and tighten role permissions |
| Many mutating webhooks | Review for performance impact on API server |
