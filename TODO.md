# TODO — Platform on EKS Workshop

## EKS Cluster RGD — ingress_domain_name for spoke clusters

**Issue**: `ingress_domain_name` on the fleet secret is set to the hub CloudFront domain for all clusters (hub + spokes). For spoke clusters, it should be the spoke's own ingress-nginx NLB hostname (e.g., `DNS_DEV`, `DNS_PROD`).

**Current impact**: Low — no spoke addon template currently consumes `ingress_domain_name` for routing. Only `platform-manifests-bootstrap` ApplicationSet requires the annotation key to exist (but doesn't use the value in its chart templates).

**Why it's hard to fix**: Chicken-and-egg problem. The fleet secret is created by the EksCluster RGD before addons deploy. The spoke ingress NLB hostname only exists after the ingress-nginx addon creates the LoadBalancer Service. The fleet secret would need a two-phase update:
1. Phase 1: Create fleet secret with empty/placeholder `ingress_domain_name`
2. Phase 2: After ingress-nginx deploys, update the fleet secret with the actual NLB hostname

**Possible solutions**:
- Use a Kubernetes controller/job that watches for the ingress-nginx Service and patches the fleet secret
- Use an ExternalSecret or ConfigMap that dynamically resolves the NLB hostname
- Accept the hub CloudFront as a shared domain and route spoke traffic through it (current behavior)
- Use a predictable DNS name (e.g., Route53 alias) that can be set before the NLB exists

**Note**: The same issue exists in Terraform — it also sets the hub CloudFront domain for all spoke fleet secrets.

## Terraform — ingress_domain_name per spoke

**File**: `platform/infra/terraform/common/locals.tf`
**Line**: `ingress_domain_name = aws_cloudfront_distribution.ingress.domain_name`

This sets the same hub CloudFront domain for all clusters. Consider making it per-cluster using the spoke ingress NLB hostname once available.
