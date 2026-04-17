# Values Separation: Dynamic vs Static

## Rule

Dynamic template values MUST stay in `addons.yaml` valuesObject. Static config goes in `values.yaml`.

## Dynamic Values (addons.yaml ONLY)

```yaml
# These use cluster secret annotations — MUST be in addons.yaml valuesObject
addon-name:
  valuesObject:
    global:
      resourcePrefix: '{{.metadata.annotations.resource_prefix}}'
      ingress_domain_name: '{{.metadata.annotations.ingress_domain_name}}'
      aws_region: '{{.metadata.annotations.aws_region}}'
      aws_cluster_name: '{{.metadata.annotations.aws_cluster_name}}'
      aws_account_id: '{{.metadata.annotations.aws_account_id}}'
```

## Static Values (values.yaml)

```yaml
# NO global section with dynamic values here
nodeSelector:
  karpenter.sh/nodepool: system-peeks
tolerations:
  - key: CriticalAddonsOnly
    operator: Exists
replicas: 2
resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    memory: 512Mi
```

## Common Mistake

```yaml
# ❌ WRONG — values.yaml overriding dynamic values with empty strings
global:
  resourcePrefix: ""           # Overrides the template!
  ingress_domain_name: ""      # Overrides the template!
```

Empty strings in values.yaml take precedence over template expressions in addons.yaml, silently breaking dynamic resolution.
