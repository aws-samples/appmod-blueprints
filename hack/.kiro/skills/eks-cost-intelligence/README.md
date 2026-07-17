# eks-cost-intelligence

A Kiro agent skill that connects to a live EKS cluster, analyzes cost signals across 6 dimensions, and produces a scored cost intelligence report with dollar-quantified findings and prioritized remediation.

## What it does

Unlike static cost best-practices guidance (`eks-best-practices`), this skill performs **live assessment** against a specific cluster. It pulls data from three sources and correlates them to produce dollar-denominated waste findings:

- **AWS Cost Explorer** — actual spend by cluster, namespace, and workload
- **CloudWatch Container Insights** — real CPU/memory utilization (P50/P95)
- **Kubernetes API** — resource requests, limits, replica counts, PVCs, Services

The output is a **Cost Score (0–100)** with classification (OPTIMIZED/GOOD/FAIR/NEEDS_WORK/CRITICAL) and a prioritized findings table with dollar impact and ready-to-apply remediation snippets.

## Assessment Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Compute Efficiency | 25 pts | CPU/memory waste, over-provisioning, missing requests |
| Spot/Graviton Adoption | 20 pts | Spot %, Graviton eligibility, instance diversity |
| Networking Costs | 15 pts | Cross-AZ traffic, VPC endpoints, topology routing |
| Storage Costs | 15 pts | gp2→gp3, unused PVCs, oversized volumes |
| Observability Costs | 10 pts | Control plane logging, metric cardinality |
| Idle Resources | 15 pts | Zero-scale deploys, orphaned LBs, empty namespaces |

## Structure

```
skills/eks-cost-intelligence/
├── SKILL.md                              # Skill entry point (frontmatter + workflow)
├── README.md                             # This file (contributor documentation)
├── references/
│   ├── compute-efficiency.md             # Dimension 1 checks
│   ├── spot-graviton-adoption.md         # Dimension 2 checks
│   ├── networking-costs.md               # Dimension 3 checks
│   ├── storage-costs.md                  # Dimension 4 checks
│   ├── observability-costs.md            # Dimension 5 checks
│   ├── idle-resources.md                 # Dimension 6 checks
│   ├── report-generation.md              # Scoring algorithm + report template
│   ├── cost-data-collection.md           # API calls for data sources
│   ├── waste-calculation.md              # Dollar waste formulas
│   ├── cost-estimation-fallback.md       # Node-based estimation fallback
│   └── findings-format.md               # Output schema + remediation templates
└── tools/
    └── report_to_html.py                 # Markdown → HTML converter (stdlib only)
```

## Prerequisites

- AWS credentials with EKS read access
- `kubectl` configured for the target cluster
- **Required permissions:** `eks:DescribeCluster`, `eks:ListClusters`, `eks:ListNodegroups`, `ec2:DescribeInstances`, `ec2:DescribeVolumes`, `elasticloadbalancing:DescribeLoadBalancers`
- **Optional (for richer analysis):** `ce:GetCostAndUsage`, `cloudwatch:GetMetricData`, `pricing:GetProducts`

## Relationship to other skills

| Skill | Relationship |
|-------|-------------|
| `eks-best-practices` | Provides advisory guidance; this skill adds the live dollar layer |
| `eks-operation-review` | Assesses operational health; this skill focuses on cost |
| `eks-recon` | Discovers cluster state; useful to run before cost analysis |
| `eks-upgrade-check` | Assesses upgrade readiness; complementary but different concern |

## Pricing Data

This skill uses **dynamic pricing lookups** (AWS Price List API) as the primary method for dollar estimates. A static reference pricing table is included as a fallback for environments where the Price List API is unavailable. The static table was last verified in June 2026 and covers us-east-1 On-Demand rates.

For production assessments, ensure `pricing:GetProducts` permission is available for the most accurate results.

## Multi-Cluster Support

Multi-cluster fleet-wide assessment is **out of scope** for the initial release. The skill assesses one cluster at a time. For fleet-wide cost analysis, run the assessment against each cluster individually and aggregate the reports externally.

Future enhancement: a `multi-cluster.md` reference may be added to support fleet-level aggregation and cross-cluster comparison.

## Contributing

This skill is developed in-repo (not vendored from an upstream source). To contribute:

1. Follow the patterns established by sibling skills (`eks-operation-review`, `eks-upgrade-check`)
2. Reference files use progressive disclosure — loaded on-demand per dimension
3. All pricing data should prefer dynamic API lookups over static tables
4. Remediation snippets should be ready-to-apply (kubectl, YAML, Terraform)
5. Run the eval scaffold (`misc/evals/eks-cost-intelligence/`) to validate changes

See the repository's [CONTRIBUTING.md](../../CONTRIBUTING.md) for general guidelines.

---

*This skill is provided as sample code for educational and demonstration purposes only.*
