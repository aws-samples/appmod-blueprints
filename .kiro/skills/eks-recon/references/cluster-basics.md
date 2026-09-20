# Module: Cluster Basics

> **Part of:** [eks-recon](../SKILL.md)
> **Purpose:** Detect core cluster information - name, version, region, endpoint, platform version

## Prerequisites

- **Cluster name required:** Yes (auto-discover if not provided — see SKILL.md Step 1)
- **MCP tools used:** `describe_eks_resource`
- **CLI fallback:** `aws eks describe-cluster`

---

## Detection Commands

### MCP (Preferred)

Use MCP when available because it handles authentication automatically and returns structured data that requires no parsing.

```
describe_eks_resource(
  resource_type="cluster",
  cluster_name="my-production-cluster"
)
```

**Example response:**

```json
{
  "cluster": {
    "name": "my-production-cluster",
    "version": "1.31",
    "platformVersion": "eks.5",
    "endpoint": "https://ABC123DEF456.gr7.us-west-2.eks.amazonaws.com",
    "arn": "arn:aws:eks:us-west-2:123456789012:cluster/my-production-cluster",
    "status": "ACTIVE",
    "createdAt": "2024-06-15T10:30:00Z"
  }
}
```

**Extract from response:**
- `cluster.name` -> Cluster name
- `cluster.version` -> Kubernetes version (check for upgrade eligibility)
- `cluster.platformVersion` -> EKS platform version (indicates patch level)
- `cluster.endpoint` -> API server endpoint (needed for kubectl config)
- `cluster.arn` -> Cluster ARN (extract region from this)
- `cluster.status` -> Cluster status (verify ACTIVE before proceeding)
- `cluster.createdAt` -> Creation timestamp (useful for audit reports)

### CLI Fallback

Use CLI when MCP tools are unavailable or when running from a bastion host with AWS credentials configured.

```bash
aws eks describe-cluster \
  --name my-production-cluster \
  --region us-west-2 \
  --query 'cluster.{
    name:name,
    version:version,
    platformVersion:platformVersion,
    endpoint:endpoint,
    arn:arn,
    status:status,
    createdAt:createdAt
  }'
```

**Example output:**

```json
{
    "name": "my-production-cluster",
    "version": "1.31",
    "platformVersion": "eks.5",
    "endpoint": "https://ABC123DEF456.gr7.us-west-2.eks.amazonaws.com",
    "arn": "arn:aws:eks:us-west-2:123456789012:cluster/my-production-cluster",
    "status": "ACTIVE",
    "createdAt": "2024-06-15T10:30:00.000000+00:00"
}
```

---

## Region Detection

When the user does not specify a region, detect it using these methods in order:

1. **Extract from cluster ARN** (if already known): Parse `arn:aws:eks:<region>:<account>:cluster/<name>`
2. **Check kubeconfig context**: Run `kubectl config current-context` and parse the region
3. **Query AWS config**: Run `aws configure get region`
4. **Prompt the user**: Ask explicitly as a last resort

---

## Output Schema

```yaml
cluster:
  name: string           # Cluster name - use for all subsequent API calls
  region: string         # AWS region - required for CLI commands
  version: string        # Kubernetes version (e.g., "1.31") - check EKS docs for EOL dates
  platform_version: string  # EKS platform version (e.g., "eks.5") - higher = more patches
  endpoint: string       # API server endpoint URL - needed for kubectl configuration
  arn: string           # Full cluster ARN - use for IAM policies and cross-account access
  status: string        # ACTIVE, CREATING, UPDATING, DELETING - proceed only if ACTIVE
  created_at: string    # ISO timestamp - useful for compliance and audit reports
```

---

## Edge Cases

### Handle Cluster Not Found

When `describe-cluster` returns `ResourceNotFoundException`, troubleshoot in this order:

1. Verify the cluster name spelling matches exactly (case-sensitive)
2. Confirm the region is correct by listing clusters: `aws eks list-clusters --region <region>`
3. Check IAM permissions - the caller needs `eks:DescribeCluster` permission

### Handle Transitional States

When the cluster status is not `ACTIVE`, take these actions:

| Status | Action |
|--------|--------|
| `CREATING` | Wait for creation to complete before running recon |
| `UPDATING` | Proceed with caution - some data may be incomplete during upgrades |
| `DELETING` | Abort recon immediately - cluster is being terminated |

### Handle Private Clusters

When endpoint access is private-only:

1. Verify MCP tool connectivity first - the MCP server may have VPC access
2. For CLI access, connect through a VPN or bastion host within the VPC
3. Record in the report: `endpoint_access: private` to flag this for operators
