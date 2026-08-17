# Container Registry Best Practices

> **Part of:** [eks-best-practices](../SKILL.md)
> **Purpose:** ECR architecture, operating models, image promotion, vulnerability scanning, base image curation, lifecycle policies, pull-through cache, managed signing, archival storage, and registry configuration for Amazon EKS

---

## Table of Contents

1. [ECR Architecture](#ecr-architecture)
2. [Operating Models](#operating-models)
3. [Image Promotion Pipeline](#image-promotion-pipeline)
4. [Vulnerability Scanning](#vulnerability-scanning)
5. [Base Image Curation](#base-image-curation)
6. [ECR Lifecycle Policies](#ecr-lifecycle-policies)
7. [Pull-Through Cache](#pull-through-cache)
8. [Repository Creation Templates](#repository-creation-templates)
9. [Managed Signing](#managed-signing)
10. [Archival Storage Class](#archival-storage-class)
11. [Registry Configuration](#registry-configuration)

---

## ECR Architecture

### Private vs Public Repositories

| Type | Use Case | Access |
|---|---|---|
| **ECR Private** | Internal application images, base images | IAM-authenticated, VPC endpoint supported |
| **ECR Public** | Open-source projects, shared libraries | Public read, authenticated write |

### Repository Naming Conventions

Use a consistent naming pattern that encodes ownership and purpose:

| Pattern | Example | Use When |
|---|---|---|
| `<team>/<app>` | `platform/nginx-base`, `team-a/api-service` | Multi-team, clear ownership |
| `<env>/<app>` | `prod/api-service`, `dev/api-service` | Environment-separated registries |
| `<app>` (flat) | `api-service`, `web-frontend` | Small team, few images |

### Cross-Account Access

| Pattern | Mechanism | Use When |
|---|---|---|
| **Resource-based policy** | ECR repository policy allows cross-account pull | Centralized registry, multiple consumer accounts |
| **ECR replication** | Automatic replication to target account/region | Each account needs its own copy |
| **IAM role assumption** | Consumer assumes role in registry account | Fine-grained access control |

### VPC Endpoints for ECR

For private clusters or security-sensitive environments, configure VPC endpoints to avoid routing image pulls through the internet:

| Endpoint | Type | Required For |
|---|---|---|
| `com.amazonaws.<region>.ecr.api` | Interface | ECR API calls (auth, describe) |
| `com.amazonaws.<region>.ecr.dkr` | Interface | Docker image pull/push |
| `com.amazonaws.<region>.s3` | Gateway | Image layer storage (S3-backed) |

---

## Operating Models

| Factor | Centralized ECR | Tenant-Managed ECR | Enterprise Registry (Artifactory/Harbor) |
|---|---|---|---|
| **Registry location** | Single shared AWS account | Each team's own account | Self-hosted or SaaS |
| **Who manages** | Platform team | Individual teams | Platform/security team |
| **Access control** | Repository policies + IAM | Per-account IAM | Registry-native RBAC |
| **Image promotion** | Cross-account replication or re-tag | Push to own registry | Promotion rules in registry |
| **Scanning** | Centralized Inspector config | Per-account Inspector | Registry-native scanning |
| **Best for** | Small-medium orgs, single account | Large orgs, strict isolation | Existing enterprise investment, multi-cloud |

### When to Use Each

| Scenario | Recommendation |
|---|---|
| Single AWS account, <10 teams | Centralized ECR |
| Multi-account with Control Tower | Centralized ECR in shared services account + cross-account pull |
| Regulatory requirement for team isolation | Tenant-managed ECR |
| Multi-cloud or hybrid | Enterprise registry (Artifactory/Harbor) |
| Air-gapped environment | ECR with pull-through cache or Harbor |

---

## Image Promotion Pipeline

### Promotion Flow

| Stage | Registry/Tag | Gate | Who Promotes |
|---|---|---|---|
| **Build** | `dev/<app>:git-sha` | CI passes (unit tests, lint, scan) | CI pipeline (automatic) |
| **Staging** | `staging/<app>:git-sha` | Integration tests pass, scan clean | CI pipeline (automatic) |
| **Production** | `prod/<app>:git-sha` | Approval gate, load test pass | Release pipeline (manual approval) |

### Tag Strategy

| Strategy | Example | Pros | Cons |
|---|---|---|---|
| **Git SHA** | `api:a1b2c3d` | Immutable, traceable to commit | Not human-readable |
| **Semantic version** | `api:1.2.3` | Human-readable, follows convention | Must enforce immutability |
| **Git SHA + semver** | `api:1.2.3-a1b2c3d` | Best of both | Longer tag |
| **`latest`** | `api:latest` | Convenient | Mutable -- never use in production |

### Promotion Methods

| Method | How It Works | Best For |
|---|---|---|
| **Re-tag** | Add production tag to existing image digest | Same account, fastest |
| **Cross-account replication** | ECR replicates image to target account | Multi-account, automatic |
| **CI pipeline copy** | Pipeline pushes image to production registry | Full control, audit trail |

DO:
- Use immutable tags (Git SHA or semver) -- never `latest` in production
- Enable immutable tag setting on ECR repositories to prevent overwrites
- Include image digest (`@sha256:...`) in production deployments for guaranteed immutability

DON'T:
- Use `latest` tag in production -- it's mutable and non-deterministic
- Rebuild images for promotion -- re-tag or replicate the exact same digest
- Skip scanning between promotion stages

---

## Vulnerability Scanning

### ECR Scanning Options

| Feature | Basic Scanning | Enhanced Scanning (Inspector) |
|---|---|---|
| **Engine** | Clair (open-source) | Amazon Inspector |
| **Coverage** | OS packages only | OS + programming language libraries |
| **Trigger** | On-push only | Continuous (re-scans on new CVE disclosure) |
| **Findings** | ECR console only | Security Hub + EventBridge |
| **Cost** | Free | Per-image pricing |
| **Limitation** | -- | Cannot scan archived images (must restore first) |
| **Recommendation** | Development only | Production |

### Severity Gating

| Severity | CI Pipeline Action | Production Deploy |
|---|---|---|
| **Critical** | Block build | Block deploy |
| **High** | Block build (configurable) | Block deploy |
| **Medium** | Warn | Allow with exception |
| **Low** | Log only | Allow |

### Integration with Security Hub

Enhanced scanning findings are automatically sent to Security Hub, providing centralized visibility across all accounts. Configure Security Hub automations to:
- Notify teams of critical findings via SNS
- Create Jira/ServiceNow tickets for high findings
- Track remediation SLAs

DO:
- Enable enhanced scanning (Inspector) for production repositories
- Set up continuous scanning -- new CVEs are disclosed daily
- Gate CI/CD pipelines on scan results -- block critical/high before push
- Integrate with Security Hub for centralized finding management

DON'T:
- Rely on basic scanning for production -- it misses language-level vulnerabilities
- Scan only at push time -- images become vulnerable as new CVEs are disclosed
- Ignore medium-severity findings indefinitely -- track and remediate on a schedule

---

## Base Image Curation

### Why Curate Base Images

Using uncurated public images introduces risk: unknown vulnerabilities, unnecessary packages (shells, curl, build tools), and inconsistent patching. A curated base image pipeline provides a controlled, scanned, and patched foundation for all application images.

### Minimal Base Image Options

| Image | Size | Shell | Package Manager | Best For |
|---|---|---|---|---|
| **Distroless (Google)** | ~2-20 MB | No | No | Production -- minimal attack surface |
| **Alpine** | ~5 MB | Yes (ash) | apk | Small images, need shell for debugging |
| **AL2023-minimal** | ~30 MB | Yes (bash) | dnf | AWS-native, Graviton-optimized |
| **Ubuntu minimal** | ~30 MB | Yes (bash) | apt | Broad compatibility |
| **Scratch** | 0 MB | No | No | Static binaries (Go, Rust) |

### Base Image Pipeline

| Step | Action | Tool |
|---|---|---|
| 1 | Pull upstream base image | CI pipeline |
| 2 | Scan for vulnerabilities | Amazon Inspector / Trivy |
| 3 | Apply security patches | Dockerfile `RUN dnf update` |
| 4 | Re-scan patched image | Amazon Inspector / Trivy |
| 5 | Push to internal ECR | CI pipeline |
| 6 | Tag as approved base | Semantic version + `approved` tag |
| 7 | Notify teams of new base | EventBridge + SNS |

### Multi-Architecture Images

For Graviton (arm64) support, build multi-arch images using Docker buildx or CI pipeline matrix builds:

| Architecture | Instance Types | Notes |
|---|---|---|
| **amd64** | m6i, c6i, r6i | Default, broadest compatibility |
| **arm64** | m7g, c7g, r7g (Graviton) | 20-40% cost savings |
| **Multi-arch manifest** | Both | Single tag works on both architectures |

DO:
- Maintain a curated set of approved base images in a dedicated ECR repository
- Rebuild base images weekly to pick up security patches
- Use multi-stage builds to exclude build tools from final images
- Build multi-arch images if using Graviton

DON'T:
- Pull base images directly from Docker Hub in production -- use pull-through cache or internal copies
- Include shells, curl, or package managers in production images unless required
- Skip scanning base images -- they're the foundation of your security posture

---

## ECR Lifecycle Policies

Lifecycle policies automatically clean up old or untagged images, reducing storage costs and keeping repositories manageable.

### Recommended Rules

| Rule | Scope | Action | Purpose |
|---|---|---|---|
| Remove untagged images | Untagged | Expire after 1 day | Clean up failed builds |
| Retain N recent tagged | Tagged | Keep last 30 images | Rollback capability |
| Expire old images | Tagged | Expire images older than 90 days | Cost optimization |
| Archive stale images | Tagged | Archive after 180 days | Long-term retention at lower cost |

### Count Types

Lifecycle rules support different ways to measure image age:

| Count Type | Counts From | Use When |
|---|---|---|
| **sinceImagePushed** | Image push date | Default -- expire images that haven't been updated |
| **sinceImagePulled** | Last pull date | Keep frequently-used images regardless of age |
| **sinceImageTransitioned** | When image was archived | Manage archived image retention |

### Tag Filtering

Use `tagPatternList` with wildcards to target specific images:

```json
{
  "tagStatus": "tagged",
  "tagPatternList": ["release-*", "v*"],
  "countType": "sinceImagePushed",
  "countNumber": 90,
  "action": { "type": "expire" }
}
```

This is more flexible than `tagPrefixList` -- patterns like `*-rc` or `dev-*` let you target release candidates, dev builds, or any naming convention.

DO:
- Apply lifecycle policies to every repository -- don't let images accumulate indefinitely
- Keep at least 30 recent tagged images for rollback capability
- Remove untagged images aggressively (1 day retention)
- Use `sinceImagePulled` for shared base images to preserve actively-used versions

DON'T:
- Delete all old images without considering rollback needs
- Apply lifecycle policies that conflict with compliance retention requirements
- Forget to set lifecycle policies on pull-through cache repositories -- they accumulate images quickly

---

## Pull-Through Cache

ECR pull-through cache rules automatically cache images from upstream public registries in your private ECR. When a pod pulls an image through the cache, ECR fetches it from the upstream registry, stores it locally, and serves subsequent pulls from the cache.

### Supported Upstream Registries

| Registry | Prefix | Auth Required |
|---|---|---|
| **Docker Hub** | `docker.io` | Yes (Secrets Manager) |
| **ECR Public** | `public.ecr.aws` | No |
| **GitHub Container Registry** | `ghcr.io` | Yes (Secrets Manager) |
| **Quay.io** | `quay.io` | Yes (Secrets Manager) |
| **Kubernetes Registry** | `registry.k8s.io` | No |
| **GitLab Container Registry** | `registry.gitlab.com` | Yes (Secrets Manager) |
| **Chainguard** | `cgr.dev` | Yes (Secrets Manager) |
| **Azure Container Registry** | `<name>.azurecr.io` | Yes (Secrets Manager) |

### How It Works

1. Pod requests image via ECR pull-through cache URI (e.g., `<acct>.dkr.ecr.<region>.amazonaws.com/docker-hub/library/nginx:1.25`)
2. ECR checks if image exists in cache
3. If missing or stale (>24 hours since last check), ECR pulls from upstream -- this requires internet access via NAT gateway or VPC endpoint
4. ECR stores the image (including multi-arch manifests) and serves it locally
5. Subsequent pulls come from cache with no upstream dependency

### When to Use

| Scenario | Benefit |
|---|---|
| **Docker Hub rate limiting** | Avoid 100 pull/6hr anonymous limit |
| **Air-gapped environments** | Cache images locally, no internet needed after first pull |
| **Compliance** | All images flow through your ECR with scanning enabled |
| **Performance** | Faster pulls from regional ECR vs cross-internet |
| **Cost** | Reduce NAT gateway data transfer costs |

DO:
- Enable pull-through cache for Docker Hub at minimum -- rate limiting is the most common issue
- Store upstream credentials in Secrets Manager for registries that require authentication
- Apply vulnerability scanning and lifecycle policies to cache repositories
- Use repository creation templates to auto-configure cache repositories

DON'T:
- Assume cached images are scanned automatically -- configure scanning rules for cache repositories
- Use pull-through cache as a substitute for curated base images -- it caches everything, including vulnerable images
- Forget that the first pull requires internet access -- air-gapped clusters need initial seeding

---

## Repository Creation Templates

Repository creation templates automatically configure new repositories as they're created -- whether through pull-through cache, create-on-push, or replication. Without templates, new repositories get default settings and miss critical configurations like scanning, encryption, and lifecycle policies.

### How Templates Work

Templates match repository names by prefix. When a new repository is created (by any mechanism), ECR checks for a matching template and applies its configuration:

| Setting | What It Configures |
|---|---|
| **Encryption** | KMS key or AES-256 for image layer encryption |
| **Image scanning** | Basic or enhanced scanning on push |
| **Lifecycle policy** | Automatic cleanup rules applied at creation |
| **Immutability** | Tag immutability setting |
| **Resource tags** | Cost allocation and ownership tags |
| **Repository permissions** | Cross-account access policies |

### Template Matching

Templates use prefix matching with a priority order:
1. Longest matching prefix wins
2. If no prefix matches, the `ROOT` template applies (if configured)

Example: For repository `docker-hub/library/nginx`, a template with prefix `docker-hub/library/` takes priority over one with prefix `docker-hub/`.

### Create-on-Push

Create-on-push allows repositories to be created automatically when an image is pushed to a repository name that doesn't exist yet. Combined with templates, this means new services can push images without any pre-provisioning -- the repository is created with the correct configuration automatically.

Enable create-on-push either as a registry default or per-template.

DO:
- Create a `ROOT` template as a catch-all to ensure every repository gets baseline configuration
- Use specific prefix templates for pull-through cache registries (e.g., `docker-hub/`, `ghcr/`)
- Include lifecycle policies in templates so cache repositories don't accumulate images endlessly
- Enable create-on-push for development environments to reduce friction

DON'T:
- Skip templates for pull-through cache -- without them, cached repos have no scanning or lifecycle policies
- Enable create-on-push in production without templates -- you'll get misconfigured repositories

---

## Managed Signing

ECR managed signing automatically signs container images on push using AWS Signer, providing cryptographic proof that an image was built and pushed through your pipeline. This supports verification at deploy time via admission controllers like Kyverno or OPA Gatekeeper.

### How It Works

1. Configure signing rules at the registry level (up to 10 rules per registry)
2. Each rule specifies a repository filter (prefix match) and an AWS Signer signing profile
3. When an image is pushed to a matching repository, ECR automatically creates a Notation-format signature
4. The signature is stored alongside the image in the same repository
5. Admission controllers verify the signature before allowing the image to run

### Configuration

| Setting | Purpose |
|---|---|
| **Signing profile** | AWS Signer profile that holds the signing key |
| **Repository filter** | Prefix-based filter (e.g., `prod/` signs only production images) |
| **Cross-account** | Signing profile can be in a different account from the registry |

### Integration with Admission Control

Managed signing pairs with Kubernetes admission controllers for deploy-time verification:

| Tool | How It Verifies |
|---|---|
| **Kyverno** | `verifyImages` policy checks Notation signatures against trusted signing profiles |
| **OPA Gatekeeper** | Custom constraint template validates signature presence and signer identity |
| **Ratify** | External data provider for Gatekeeper, native Notation support |

DO:
- Enable managed signing for production repositories to establish image provenance
- Use repository prefix filters to sign only images that need verification (avoids signing dev/test images)
- Combine with admission controllers to enforce signature verification at deploy time

DON'T:
- Treat signing as a substitute for vulnerability scanning -- signing proves provenance, not safety
- Use the same signing profile for all environments -- separate dev and prod signing identities

**See also:** [Security -- Supply Chain](security-supply-chain.md) for admission control patterns and image verification policies

---

## Archival Storage Class

ECR archival storage provides a low-cost tier for images you need to retain but rarely access -- compliance snapshots, audit artifacts, or old release images. Archival images cost significantly less than standard storage but must be restored before they can be pulled.

### How It Works

| Aspect | Detail |
|---|---|
| **Transition** | Via lifecycle policy `archive` action, or manual API call |
| **Storage cost** | Lower than standard ECR storage |
| **Restore time** | Up to 20 minutes |
| **Restore duration** | Restored copy available for a configurable number of days |
| **Scanning** | Archived images cannot be scanned -- restore first |

### Lifecycle Policy Integration

Use lifecycle policies to automatically archive images after a retention period:

```json
{
  "rules": [
    {
      "rulePriority": 1,
      "selection": {
        "tagStatus": "tagged",
        "tagPatternList": ["release-*"],
        "countType": "sinceImagePushed",
        "countNumber": 180
      },
      "action": { "type": "archive" }
    },
    {
      "rulePriority": 2,
      "selection": {
        "tagStatus": "tagged",
        "tagPatternList": ["release-*"],
        "countType": "sinceImageTransitioned",
        "countNumber": 730
      },
      "action": { "type": "expire" }
    }
  ]
}
```

This archives release images after 180 days and permanently deletes them 2 years after archival -- a typical compliance lifecycle.

DO:
- Use archival storage for images required by compliance but rarely pulled
- Chain lifecycle rules: archive after N days, expire after M days from archival
- Test restore times before relying on archived images for disaster recovery

DON'T:
- Archive images you may need for rapid rollback -- 20-minute restore is too slow for incidents
- Forget that archived images can't be scanned -- restore and scan if you need to assess vulnerabilities

---

## Registry Configuration

ECR has registry-level settings that affect all repositories in the account/region. Two settings are particularly useful for large registries.

### Blob Mounting

Blob mounting allows image layers that already exist in one repository to be referenced (mounted) when pushing to another repository in the same registry, instead of re-uploading them. This is significant when many images share common base layers.

| Setting | Effect |
|---|---|
| **Enabled (default)** | Push operations mount existing layers from other repos, saving bandwidth and time |
| **Disabled** | Every push uploads all layers, even if identical copies exist in the registry |

Keep blob mounting enabled unless you have a specific security requirement to isolate layer access between repositories.

### Pull-Time Update Exclusions

When pull-through cache is enabled, ECR checks the upstream registry for updates every 24 hours. Pull-time update exclusions let you pin specific repositories so ECR never re-checks upstream -- the cached version is treated as authoritative.

Use this for:
- **Known-good images** you've validated and don't want upstream changes to override
- **Air-gapped environments** where you've seeded images and upstream is unreachable
- **Compliance scenarios** where you need a frozen, auditable copy

---

## Helm Chart Management

### ECR OCI Support vs S3 Helm Repository

| Factor | ECR OCI Helm Charts | S3-Based Helm Repo (ChartMuseum) |
|--------|--------------------|---------------------------------|
| **Protocol** | OCI registry (standard) | HTTP(S) Helm repo |
| **Authentication** | ECR IAM (same as images) | S3 IAM + Helm repo plugin |
| **Versioning** | OCI tags + digests | Chart index.yaml |
| **Replication** | ECR cross-account/region replication | S3 replication |
| **Scanning** | Not applicable (charts are templates) | Not applicable |
| **Recommendation** | Preferred — native, no extra infra | Legacy or non-AWS Helm consumers |

### Pushing and Consuming Helm Charts via ECR

The workflow for Helm charts stored in ECR OCI follows three steps:

1. **Authenticate:** Obtain an ECR authorization token and pass it to `helm registry login`. The same ECR IAM credentials used for container images work for Helm charts.
2. **Package and push:** Package the chart directory into a `.tgz` archive, then push it to an OCI URI in ECR (e.g., `oci://<account-id>.dkr.ecr.<region>.amazonaws.com/charts/`).
3. **Install from ECR:** Reference the OCI URI directly in `helm install` or in ArgoCD Application source configuration with a specific version tag.

**Design considerations:**
- Use a dedicated `charts/` prefix in ECR to separate Helm charts from container images
- Apply the same ECR lifecycle policies to chart repositories to clean up old versions
- ECR cross-account replication works for Helm charts — spoke accounts get chart replicas automatically
- ArgoCD natively supports OCI Helm sources — no extra configuration needed beyond ECR auth

---

**Sources:**
- [Amazon ECR Documentation](https://docs.aws.amazon.com/AmazonECR/latest/userguide/)
- [Designing a secure container image registry](https://aws.amazon.com/blogs/containers/designing-a-secure-container-image-registry/)
- [Amazon Inspector container scanning](https://docs.aws.amazon.com/inspector/latest/user/scanning-ecr.html)
- [ECR Pull-Through Cache](https://docs.aws.amazon.com/AmazonECR/latest/userguide/pull-through-cache.html)
- [ECR Managed Signing](https://docs.aws.amazon.com/AmazonECR/latest/userguide/managed-signing.html)
- [ECR Archival Storage](https://docs.aws.amazon.com/AmazonECR/latest/userguide/archive_restore_image.html)
- [ECR Repository Creation Templates](https://docs.aws.amazon.com/AmazonECR/latest/userguide/repository-creation-templates.html)
