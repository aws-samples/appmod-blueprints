# EKS Supply Chain, Infrastructure & Compliance Security

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** Image security, software supply chain, infrastructure hardening, regulatory compliance, and incident response

**For core IAM, pod security, and secrets, see:** [Security](security.md)
**For runtime and network security, see:** [Runtime & Network Security](security-runtime-network.md)

---

## Table of Contents

1. [Image Security](#image-security)
2. [Infrastructure Security](#infrastructure-security)
3. [Regulatory Compliance](#regulatory-compliance)
4. [Incident Response](#incident-response)

---

## Image Security

### Build Minimal Images

Reducing the attack surface of container images is a primary security goal:

- **Remove unnecessary binaries** — shells, curl, nc, and anything not needed at runtime
- **Remove SETUID/SETGID bits** that can be used for privilege escalation:
  ```dockerfile
  RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} \; || true
  ```
- **Use multi-stage builds** — build tools stay in the build stage, only runtime artifacts reach the final image
- **Build from scratch** for statically-linked binaries (Go, Rust):
  ```dockerfile
  FROM golang:alpine AS builder
  WORKDIR /app
  COPY . .
  RUN go build -o /app/server

  FROM scratch
  COPY --from=builder /app/server /server
  ENTRYPOINT ["/server"]
  ```
- **Add the USER directive** to Dockerfiles to run as non-root by default
- **Lint Dockerfiles** with tools like [dockerfile_lint](https://github.com/projectatomic/dockerfile_lint) to enforce best practices in CI

### Software Bill of Materials (SBOMs)

SBOMs provide visibility into what components make up your images. They're essential for:
- Auditing image contents post-deployment
- Detecting zero-day vulnerabilities in deployed images
- Verifying provenance and trustworthiness of dependencies
- Detecting drift that may indicate unauthorized changes

**Generate SBOMs with:**
- **Amazon Inspector** — [create and export SBOMs](https://docs.aws.amazon.com/inspector/latest/user/sbom-export.html)
- **Syft (Anchore)** — generates SBOMs that can be attested and attached to images

### Image Scanning

**Enable enhanced scanning with Inspector:**

```bash
# Enable enhanced scanning (uses Amazon Inspector)
aws ecr put-registry-scanning-configuration \
  --scan-type ENHANCED \
  --rules '[{"repositoryFilters":[{"filter":"*","filterType":"WILDCARD"}],"scanFrequency":"CONTINUOUS_SCAN"}]'
```

| Scanning Type | Provider | Cost | Features |
|--------------|----------|------|----------|
| **Basic** | Clair (via ECR) | Free | On-push or on-demand |
| **Enhanced** | Amazon Inspector | Paid | Continuous, OS + language packages |

Additional scanning tools: Grype, Trivy, Snyk, Prisma Cloud (twistcli), Aqua.

Delete or rebuild images with HIGH or CRITICAL vulnerabilities. If a deployed image develops a vulnerability, replace it as soon as possible.

### Attestations and Image Signing

Attestations are cryptographically signed statements that verify artifact integrity — a pipeline run, SBOM, or vulnerability scan is true about a container image.

**Create attestations with:**
- **AWS Signer** — AWS-managed signing service
- **Sigstore cosign** — open-source signing and verification

**Validate at admission with:**
- **Kyverno** — [verify image signatures and attestations](https://kyverno.io/docs/writing-policies/verify-images/sigstore/)
- **OPA Gatekeeper** or **Ratify** — alternative admission controllers

### Admission Control for Images

**Kyverno policy — require images from ECR only:**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-image-registries
spec:
  validationFailureAction: Enforce
  rules:
  - name: validate-registries
    match:
      any:
      - resources:
          kinds: ["Pod"]
    validate:
      message: "Images must come from the approved ECR registry"
      pattern:
        spec:
          containers:
          - image: "123456789012.dkr.ecr.*.amazonaws.com/*"
```

### ECR Hardening

**Repository access control:**
- Use ECR namespaces (`team-a/`, `team-b/`) with IAM policies restricting access per team:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowPushPull",
    "Effect": "Allow",
    "Action": [
      "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability", "ecr:PutImage",
      "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload"
    ],
    "Resource": ["arn:aws:ecr:us-east-1:123456789012:repository/team-a/*"]
  }]
}
```

**VPC endpoint policies for ECR** — prevent data exfiltration by restricting which repositories can be accessed:

```json
{
  "Statement": [{
    "Sid": "LimitECRAccess",
    "Principal": "*",
    "Action": "*",
    "Effect": "Allow",
    "Resource": "arn:aws:ecr:<region>:<account_id>:repository/*"
  }]
}
```

Apply to both `com.amazonaws.<region>.ecr.dkr` and `com.amazonaws.<region>.ecr.api` endpoints. Add the EKS image registry account (e.g., `602401143452` for most commercial regions) to allow pulling kube-proxy, coredns, and aws-node images.

**Additional ECR best practices:**
- Enable **immutable tags** to prevent image overwrites
- Configure **lifecycle policies** to remove stale/untagged images (but ensure CI/CD keeps deployments current)
- Use **VPC endpoints** for ECR to avoid internet routing
- Use immutable image tags or digests (`@sha256:...`) — don't use `latest` in production
- Scan images in CI pipeline before pushing to ECR
- Use minimal base images and curate a set of vetted base images for your organization

---

## Infrastructure Security

### Use Container-Optimized OS

| OS | Key Feature | Use When |
|----|------------|----------|
| **Bottlerocket** | Reduced attack surface, verified boot, SELinux enforced | Default for security-conscious workloads |
| **EKS Optimized AMI (AL2023)** | Minimal packages, regular security patches | Standard workloads |
| **Custom RHEL/CentOS** | STIG compliance, custom hardening | Regulated environments |

Keep host OS images up to date with the latest security patches. Check the [EKS AMI CHANGELOG](https://github.com/awslabs/amazon-eks-ami/blob/master/CHANGELOG.md) regularly.

### Treat Infrastructure as Immutable

Replace worker nodes rather than performing in-place upgrades:
- **MNG:** EKS console shows a message when a new AMI is available — upgrade via API/CLI/Console
- **Karpenter:** Drift detection automatically replaces nodes after control plane upgrade
- **Fargate:** AWS automatically updates underlying infrastructure

Automate node replacement to minimize human oversight — you'll need to replace workers regularly as patches are released.

### CIS Benchmarks with kube-bench

Run [kube-bench](https://github.com/aquasecurity/kube-bench) to evaluate your cluster against the CIS Amazon EKS Benchmark:

```bash
# Run kube-bench against EKS cluster
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-eks.yaml
kubectl logs job/kube-bench
```

The CIS Amazon EKS Benchmark inherits from the CIS Kubernetes Benchmark with EKS-specific considerations. Since EKS manages the control plane, not all CIS Kubernetes recommendations apply.

### Minimize Worker Node Access

**Use SSM Session Manager instead of SSH:**

```bash
aws ssm start-session --target <INSTANCE_ID_OF_EKS_NODE>
```

SSM advantages over SSH:
- Access controlled by IAM (no SSH keys to manage, lose, or share)
- Full audit trail and command logging
- No inbound ports needed on security groups

**Minimal IAM policy for SSM access** (avoid `AmazonSSMManagedInstanceCore` which grants broad `ssm:GetParameter(s)` access):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnableAccessViaSSMSessionManager",
      "Effect": "Allow",
      "Action": [
        "ssmmessages:OpenDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:CreateControlChannel",
        "ssm:UpdateInstanceInformation"
      ],
      "Resource": "*"
    }
  ]
}
```

### Deploy Workers onto Private Subnets

Minimize exposure to the internet by deploying nodes onto private subnets. Restrict AWS security group rules for any nodes on public subnets. Beginning April 2020, MNG nodes inherit public IP assignment from the subnet configuration.

### Run Amazon Inspector for Host Scanning

Amazon Inspector scans EC2 instances for network reachability issues and vulnerabilities. The SSM agent (preinstalled on EKS optimized AMIs) enables CVE scanning. Inspector cannot run on Fargate infrastructure.

---

## Regulatory Compliance

### EKS Compliance Programs

| Program | Amazon EKS | ECS Fargate | Amazon ECR |
|---------|-----------|-------------|------------|
| **PCI DSS Level 1** | Yes | Yes | Yes |
| **HIPAA Eligible** | Yes | Yes | Yes |
| **SOC I, II, III** | Yes | Yes | Yes |
| **ISO 27001/9001/27017/27018** | Yes | Yes | Yes |
| **FedRAMP Moderate** | Yes | No | Yes |
| **FedRAMP High (GovCloud)** | Yes | No | Yes |
| **HITRUST CSF** | Yes | Yes | Yes |

Status changes over time. Always check [AWS Services in Scope](https://aws.amazon.com/compliance/services-in-scope/) for the latest.

### Shift Left — Catch Violations Early

Use policy-as-code tools in CI/CD pipelines to detect violations before deployment:

| Tool | Language | Key Feature |
|------|----------|-------------|
| **OPA/Conftest** | Rego | Test K8s manifests against policies in CI |
| **Kyverno CLI** | YAML (K8s-native) | Validate resources and test policies in pipelines |
| **Gatekeeper** | Rego | Admission control + constraint templates |

**Example: Run Kyverno CLI in CI to validate manifests:**
```bash
kyverno apply /path/to/policies --resource /path/to/manifests
```

**Example: Run Conftest in CI:**
```bash
conftest test deployment.yaml --policy /path/to/opa/policies
```

The benefit of shift-left is that developers get feedback before their application hits the cluster, catching issues like missing security contexts, privileged containers, or non-compliant images during code review rather than at deployment time.

---

## Incident Response

### EKS-Specific Forensics Steps

1. **Isolate the pod** — apply deny-all network policy to the namespace
2. **Capture pod state** — `kubectl get pod -o yaml`, `kubectl logs`, `kubectl exec -- ps aux`
3. **Snapshot the node** — create EBS snapshot of the node's root volume
4. **Cordon the node** — `kubectl cordon node-name` to prevent new scheduling
5. **Preserve logs** — export CloudWatch Logs, audit logs, VPC Flow Logs
6. **Review GuardDuty findings** — check for related security findings
7. **Analyze with EKS audit logs** — trace the attack timeline via API server logs

**Do NOT delete pods or nodes before capturing evidence.**

### Automated Response Patterns

Use GuardDuty findings with EventBridge to automate initial response:
- GuardDuty finding -> EventBridge rule -> Lambda function -> apply network policy isolation
- Alert security team via SNS/Slack while automated containment runs

### Key Investigation Tools

| Tool | Purpose |
|------|---------|
| **EKS audit logs** | Trace API calls, identify who did what |
| **GuardDuty** | Threat detection findings with context |
| **VPC Flow Logs** | Network traffic metadata |
| **CloudTrail** | AWS API calls (eks:*, ec2:*, iam:*) |
| **Velero** | Cluster state backup for comparison |

---

**Sources:**
- [AWS EKS Best Practices Guide — Image Security](https://docs.aws.amazon.com/eks/latest/best-practices/image-security.html)
- [AWS EKS Best Practices Guide — Infrastructure Security](https://docs.aws.amazon.com/eks/latest/best-practices/protecting-the-infrastructure.html)
- [AWS EKS Best Practices Guide — Compliance](https://docs.aws.amazon.com/eks/latest/best-practices/compliance.html)
- [AWS EKS Best Practices Guide — Incident Response](https://docs.aws.amazon.com/eks/latest/best-practices/incident-response.html)
