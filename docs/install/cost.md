# Solution cost — what you pay for, how to estimate it, how to stop it

**Objective:** list the AWS resources this solution actually creates, so you can estimate their
cost in the AWS Pricing Calculator, track it in Cost Explorer, and reduce or stop it. This page
gives **no price figures** on purpose: prices are regional and change over time.

> Applies to **every mode** (workshop in your own account, quick and custom direct installs).
> At an AWS‑led event the account is provided and you pay nothing.

---

## 1. Cost items (what the solution deploys)

A deployment is **one hub plus N spokes**. Every item below is created by the solution's own code
(source in brackets); nothing else is assumed.

| Item | Scope | Created by |
|---|---|---|
| EKS cluster (control plane) | hub + **each** spoke | KRO `EksCluster` (`rg-eks.yaml`) / `EksclusterWithVpc` (`rg-eks-vpc.yaml`); the hub's is applied from the local `kind` cluster (`hub:claim`) |
| EKS managed Capabilities (Argo CD, ACK, kro) | hub (Argo CD + ACK + kro); spokes: ACK + kro, Argo CD only when enabled | `Capability` resources in `rg-eks.yaml` |
| Worker nodes (EKS Auto Mode) | hub + each spoke | Auto Mode node pools; scales with the workloads you run |
| VPC with **1 NAT gateway + 1 Elastic IP** | each spoke; the hub too, unless `hub.network.vpcId` reuses an existing VPC | `rg-vpc.yaml` (`natGateways` is currently always 1) |
| Application Load Balancer | hub (`platform` IngressGroup); a spoke only when one of its workloads exposes an Ingress | `ingress-class-alb` + AWS Load Balancer Controller |
| CloudFront distribution | only in CloudFront mode (`insecure: true`) | `scripts/cloudfront-*.sh` ([quick-cloudfront.md](quick-cloudfront.md)) |
| Amazon Managed Service for Prometheus workspace + managed scrapers | hub (scrapers for hub and spokes) | `observability-aws` addon (`amp-workspace.yaml`, `prometheus-scraper.yaml`, `spoke-scrapers.yaml`) |
| Amazon Managed Grafana workspace | hub | `observability-aws` addon (`amg-workspace.yaml`) — billed per active user |
| AWS Secrets Manager secrets | hub (`<hub>/secrets`, observability credentials, …) | provider + External Secrets |
| Route53 hosted zone + queries | only in own‑domain mode (`insecure: false`) | your zone; the platform writes records via external‑dns |
| ECR repositories, S3 buckets | per `resourcePrefix`, as workloads create them | KRO resource groups (CI/CD pipeline, S3, Ray/model cache, …) |
| CloudWatch Logs | per cluster | EKS control‑plane logs (api, audit, authenticator, controllerManager, scheduler) are enabled in `rg-eks.yaml`; Capability controller logs only after `task enable-capability-logs` |
| Data transfer (internet egress, cross‑AZ, NAT processing) | all | usage‑driven |

The `kind` bootstrap cluster runs locally in Docker: it costs nothing on AWS.

Each additional spoke adds roughly one EKS cluster + its Capabilities + its nodes + one VPC with
NAT gateway and Elastic IP.

---

## 2. Estimate before deploying — AWS Pricing Calculator

Build an estimate in the [AWS Pricing Calculator](https://calculator.aws/) from the table above, in
the region you deploy to:

- EKS: `1 + N` clusters, plus the EKS Capabilities per cluster;
- EC2 / Auto Mode: the node footprint you expect on the hub and on each spoke;
- VPC: up to `1 + N` NAT gateways and Elastic IPs (one per VPC the solution creates), plus NAT data processing;
- 1 ALB; CloudFront if used; Route53 if you use your own domain;
- AMP ingestion/storage/query + managed scraper; AMG active users; Secrets Manager secret count.

The nodes are usually the largest and most variable line; the per‑cluster fixed items (control
plane, Capabilities, NAT) grow linearly with the number of spokes.

---

## 3. Track the real cost — tags + Cost Explorer

### Step 1 — set cost‑allocation tags at install time

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

### Step 2 — activate the tags as cost‑allocation tags

In the **payer** account, Billing → **Cost allocation tags**, activate each `platformTags` key.
Activation is not retroactive, so do it as early as possible (newly tagged resources show up in Cost
Explorer within ~24 h).

### Step 3 — read the cost in Cost Explorer

- **By tag:** group/filter by your `platformTags` key (e.g. `project`) to isolate the whole
  platform's spend across services.
- **By resource name prefix:** everything the platform names carries your `resourcePrefix`
  (ECR repos, S3 buckets, IAM roles), useful as a secondary cross‑check.
- **By linked account:** for **cross‑account spokes**, filter by the spoke's linked account (the
  cleanest per‑spoke breakdown).
- **By service:** group by AWS service to see the split between EKS, EC2, VPC/NAT, ELB, CloudFront,
  AMP/AMG — the table in section 1, with real numbers.

### Optional — in‑cluster visibility

- The `peeks` agent shipped in the workshop IDE bundles the **`eks-cost-intelligence`** APEX skill;
  you can ask it for a cost analysis of the live cluster (convenience only — Cost Explorer stays
  authoritative).
- For Kubernetes‑native attribution by namespace/workload, add **OpenCost** (or a commercial
  equivalent). It is **not** part of the platform.

---

## 4. Reduce or stop the cost

| Goal | Action |
|---|---|
| Remove an unused spoke | [Delete a spoke](delete-spoke.md) — removes its EKS cluster, VPC, NAT gateway and Elastic IP |
| Shrink the hub | In your **writable** fleet repo, set unused addons to `false` under `enabledAddons:` in `<fleetRepo.basepath>overlays/environments/control-plane/enabled-addons.yaml` (create it if absent — missing value files are ignored), e.g. `jupyterhub`, `ray_operator`, `spark_operator`, `devlake`; fewer workloads → fewer Auto Mode nodes |
| Drop managed observability | Set `enabledAddons.observability_aws: false` in the same file (removes the AMP/AMG workspaces and scrapers; you lose the managed dashboards/alerts) |
| Remove all addons, keep the hub cluster | `task hub-destroy-addons` — the on‑hub controllers also delete the AWS resources they manage, **including the spoke clusters** |
| **Stop everything** (direct install) | `task destroy` — deletes the KRO instances, waits for ACK to delete their AWS resources, then sweeps the remaining resources (CloudFront, IAM, Secrets, AMP, OIDC, VPC). Requires `boto3` in `python3` |
| **Stop everything** (workshop in your own account) | Follow the workshop [Cleanup](https://catalog.workshops.aws/platform-engineering-on-eks/en-US/90_cleanup) section, then delete the CloudFormation stack |

`task destroy-kind` only deletes the local `kind` cluster; it does **not** stop AWS costs.

After a teardown, check Cost Explorer (by tag and by service) for a few days, and look for
leftovers by `resourcePrefix` (ECR repositories, S3 buckets, log groups, VPCs).
