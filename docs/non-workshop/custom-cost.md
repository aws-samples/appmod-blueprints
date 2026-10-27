# 3.4 · Custom — show the cost of the solution

There is no dedicated cost task in the repo, but the platform already **tags every resource it
creates**, which is the foundation for both estimating the cost up front and tracking it after
deployment. This page gives a concrete, generic method (no invented figures).

---

## What makes up the cost

A deployment is a hub plus N spokes. The recurring cost components are:

| Component | Scope | Notes |
|---|---|---|
| EKS control plane | hub + **each** spoke | one flat hourly charge per cluster |
| Worker nodes (EKS Auto Mode / Karpenter) | hub + each spoke | the largest and most variable line; scales with workload |
| VPC data path — NAT gateways, data processing | hub + each spoke | each cluster gets its own VPC |
| Elastic IPs | per NAT / per env | |
| Application Load Balancer | hub (and spokes with ingress) | the platform's internet/edge entry |
| CloudFront | if you expose via CloudFront | request + data‑transfer pricing |
| Amazon Managed Prometheus + Managed Grafana (AMP/AMG) | hub observability | ingestion + query + Grafana user pricing |
| AWS Secrets Manager | hub | per‑secret monthly + API calls |
| Route53 | if you use your own domain | hosted zone + queries |
| ECR, S3 | per `resourcePrefix` | registry storage + request/data |

Each spoke roughly multiplies the control‑plane + nodes + VPC + NAT lines.

---

## Method 1 — tag the platform, then read Cost Explorer (recommended)

### Step 1 — set cost-allocation tags at install time

Set `platformTags` in `config.local.yaml`. These tags are applied to **every** AWS resource the
platform creates — hub resources via CDK `Tags.of(stack).add()`, and spoke resources via the KRO
`EksclusterWithVpc` `awsTags` field (threaded through the hub cluster‑secret `platform_tags`
annotation):

```yaml
platformTags:
  project: <your-project>
  environment: <your-env>
  owner: <your-team>
```

> If you omit `platformTags` the chart renders `awsTags: {}` (a no‑op) and resources carry no
> platform cost tag — so set it before install, or re‑tag afterward, if you want tag‑based cost
> reports.

### Step 2 — activate the tags as cost-allocation tags

In the **payer** account, Billing → **Cost allocation tags**, activate each `platformTags` key.
Activation is not retroactive, so do it as early as possible (newly tagged resources show up in Cost
Explorer within ~24 h).

### Step 3 — read the cost in Cost Explorer

- **By tag:** group/filter Cost Explorer by your `platformTags` key (e.g. `project`) to isolate the
  whole platform's spend across services.
- **By resource name prefix:** everything the platform names carries your `resourcePrefix`
  (ECR repos, S3 buckets, IAM roles), useful as a secondary cross‑check.
- **By linked account:** for **cross‑account spokes**, filter Cost Explorer by the spoke's linked
  account to get its spend in one view (this is the cleanest per‑spoke breakdown when spokes live in
  their own accounts).
- **By service:** group by AWS service to see the split between EKS, EC2 (nodes), VPC/NAT, CloudFront,
  AMP/AMG, etc. — that is your component breakdown above, with real numbers.

---

## Method 2 — estimate up front with the AWS Pricing Calculator

Before (or instead of) deploying, build an estimate in the
[AWS Pricing Calculator](https://calculator.aws/) from the component list above:

- 1 × EKS control plane for the hub + 1 × per spoke;
- EC2 for the expected node footprint (hub + each spoke) in your region and instance families;
- NAT gateway(s) per VPC + expected data processing;
- 1 × ALB (+ per spoke with ingress);
- CloudFront (if used), AMP ingestion/query, AMG users, Secrets Manager, Route53.

Multiply the per‑cluster block by `1 + N spokes`. Pricing is regional, so estimate in the region(s)
you actually deploy to.

---

## Method 3 — in-cluster cost visibility (optional)

- The `peeks` agent that ships in the workshop IDE bundles the **`eks-cost-intelligence`** APEX
  skill — if you run that agent, you can ask it for a cost analysis of the live cluster. (This is an
  agent convenience; the authoritative numbers still come from Cost Explorer.)
- For continuous, Kubernetes‑native cost attribution you can add **OpenCost** (or a commercial
  equivalent) to the hub/spokes to break spend down by namespace/workload. This is **not** part of
  the platform and is an opt‑in addon.

---

## Practical tips

- EKS Auto Mode / node cost is almost always the dominant line — size and scale‑to‑zero policy
  matter far more than the fixed control‑plane fees.
- Each spoke is a full cluster (control plane + nodes + VPC + NAT): the marginal cost of an extra
  spoke is roughly one more hub‑sized data path, so delete spokes you are not using
  ([custom-delete-spoke.md](custom-delete-spoke.md)).
- Keep `platformTags` consistent across hub and spokes so a single Cost Explorer tag filter captures
  the whole solution.
