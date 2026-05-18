# app-exposure

KRO `ResourceGraphDefinition` (RGD) that exposes any Kubernetes Service
through the **shared hub ALB** in two minutes, declaratively.

A user creates a single `AppExposure` claim:

```yaml
apiVersion: peeks.io/v1alpha1
kind: AppExposure
metadata:
  name: my-app
  namespace: default
spec:
  service:
    name: my-app
    port: 80
  hostname: my-app          # final FQDN = my-app.<ingress_domain_name>
  path: /
  healthCheckPath: /healthz
  rulePriority: 100
```

KRO synthesises three AWS resources:

| # | Kind | Group | Owner |
|---|------|-------|-------|
| 1 | `TargetGroup` | `elbv2.services.k8s.aws/v1alpha1` | ACK ELBv2 controller |
| 2 | `Rule` (listener rule) | `elbv2.services.k8s.aws/v1alpha1` | ACK ELBv2 controller |
| 3 | `TargetGroupBinding` | `elbv2.k8s.aws/v1beta1` | AWS Load Balancer Controller |

Traffic flow:

```
Client ──HTTPS──► CloudFront (cloudfront-alb mode) ──HTTP──► hub ALB listener
                                                                   │
                                                                   │ host-header + path
                                                                   ▼
                                                              ACK Rule ──► ACK TargetGroup
                                                                                 │
                                                                                 │ TGB
                                                                                 ▼
                                                                          Service endpoints
```

## Modes

This chart implements the **shared-ALB** patterns described in
[`docs/exposure-architecture.md`](../../../../docs/exposure-architecture.md):

* `cloudfront-alb` — CloudFront in front of the hub ALB on HTTP:80
* `tls-alb` — direct HTTPS:443 termination on the hub ALB

Both share the same listener (different listeners per mode are selected at
seed time by `peeks-hub-bootstrap` and surfaced in the cluster secret
annotation `alb_listener_arn`). The `dedicated-alb` mode (one ALB per app)
is not yet implemented and would use a different RGD.

## Prerequisites

### Hub EKS cluster (production / Workshop Studio)

The **EKS Capability ALB** must be enabled on the cluster. It provides:

* ACK ELBv2 controller (CRDs `*.elbv2.services.k8s.aws`)
* AWS Load Balancer Controller (CRDs `*.elbv2.k8s.aws`)

Verify with:

```bash
kubectl get crd | grep -E 'elbv2|targetgroupbinding'
```

You should see at minimum:

```
listeners.elbv2.services.k8s.aws
loadbalancers.elbv2.services.k8s.aws
rules.elbv2.services.k8s.aws
targetgroups.elbv2.services.k8s.aws
targetgroupbindings.elbv2.k8s.aws
```

### kind-kro-ack (local dev)

Capabilities aren't available on Kind. The cluster bootstrap currently
installs ACK `iam`/`eks`/`ec2` only — see
`cluster-providers/kind-kro-ack/Taskfile.yaml:192-201`. To run
`app-exposure` on Kind, extend the `ack:install` task with the `elbv2`
controller and install AWS LBC manually. Tracked as a follow-up.

## How the chart is wired

The chart is meant to be deployed by ArgoCD via the addons AppSet, **not**
manually with `helm install`. The wiring lives in
`gitops/addons/registry/platform.yaml` (entry `app-exposure`):

```yaml
app-exposure:
  enabled: false                         # opt-in per cluster
  selector:
    matchExpressions:
      - key: enable_app_exposure
        operator: In
        values: ['true']
  valuesObject:
    albListenerArn:    '{{.metadata.annotations.alb_listener_arn}}'
    ingressDomainName: '{{.metadata.annotations.ingress_domain_name}}'
    vpcId:             '{{.metadata.annotations.aws_vpc_id}}'
    awsRegion:         '{{.metadata.annotations.aws_region}}'
    exposureMode:      '{{.metadata.annotations.exposure_mode}}'
```

The annotations come from the gitops-bridge cluster secret seeded by
`task hub:seed-secret` (see `cluster-providers/kind-kro-ack/Taskfile.yaml`).

A cluster opts in by carrying the label `enable_app_exposure: "true"` on
its `argocd.argoproj.io/secret-type=cluster` Secret.

## Resources rendered

| Template | Sync wave | Purpose |
|----------|-----------|---------|
| `configmap-edge-config.yaml` | 10 | Observability — exposes the values resolved from cluster annotations |
| `rgd-app-exposure.yaml` | 20 | The KRO `ResourceGraphDefinition` itself |
| `examples/instance-shared-alb.yaml` | 30 | Smoke-test `AppExposure` claim — disabled by default |

## Schema (claim CRD)

```yaml
spec:
  service:
    name: <Service in same namespace>
    port: <integer TCP port>
  hostname: <prefix>          # FQDN = <hostname>.<ingress_domain_name>
  path: /                     # path prefix the rule matches
  healthCheckPath: /          # ALB health-check path
  rulePriority: 100           # unique 50-50000 on the shared listener
  resourceSuffix: ''          # optional override (default = metadata.name)
```

`status` exposes `targetGroupARN`, `ruleARN`, `fqdn` once the resources
become Ready.

## Local rendering for dev

```bash
helm template t gitops/addons/charts/app-exposure/ \
  --set albListenerArn=arn:aws:...:listener/app/peeks-hub/abc/def \
  --set ingressDomainName=hub.example.com \
  --set vpcId=vpc-123 \
  --set awsRegion=eu-west-1 \
  --set exposureMode=cloudfront-alb \
  --set examples.enabled=true
```

## Pitfalls

* **`targetType` must be `ip`** — required for `TargetGroupBinding` with
  pod targets. AWS LBC rejects `instance` targets when bound by Service.
* **Rule priority must be unique on the shared listener.** Coordinate
  values across teams, or build an automatic allocator (future).
* **VPC ID must match the cluster's actual VPC** — the seed-secret
  annotation `aws_vpc_id` is the source of truth and is rendered into
  the RGD at chart install time, not at claim time.
* **CloudFront origin** is the ALB DNS, not the FQDN advertised here.
  The host-header match is on the user-facing FQDN; CloudFront preserves
  the Host header.
