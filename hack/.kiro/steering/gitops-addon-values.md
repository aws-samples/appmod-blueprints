# GitOps Addon Values Configuration

## Purpose

Ensures proper separation between dynamic template values and static configuration values in GitOps addon management to prevent value override issues.

## Instructions

### Dynamic vs Static Values Separation

- NEVER define dynamic template values in addon values.yaml files (ID: GITOPS_NO_DYNAMIC_IN_VALUES)
- ALWAYS keep dynamic template values ONLY in addons.yaml valuesObject (ID: GITOPS_DYNAMIC_IN_ADDONS_YAML)
- NEVER use empty strings ("") for dynamic values in values.yaml as they will override templates (ID: GITOPS_NO_EMPTY_DYNAMIC)
- ALWAYS put static configuration values in addon-specific values.yaml files (ID: GITOPS_STATIC_IN_VALUES)

### Dynamic Template Values

Dynamic values that MUST stay in `gitops/addons/bootstrap/default/addons.yaml`:
- `{{.metadata.annotations.resource_prefix}}`
- `{{.metadata.annotations.ingress_domain_name}}`
- `{{.metadata.annotations.aws_region}}`
- `{{.metadata.annotations.aws_cluster_name}}`
- `{{.metadata.annotations.aws_account_id}}`
- Any other `{{.metadata.*}}` template expressions

### Static Configuration Values

Static values that go in `gitops/addons/default/addons/*/values.yaml`:
- Nodepool names (e.g., `karpenter.sh/nodepool: system-peeks`)
- Tolerations
- Resource limits/requests
- Replica counts
- Image lists
- Feature flags
- Any non-templated configuration

### Correct Pattern

**addons.yaml (dynamic values only):**
```yaml
addon-name:
  valuesObject:
    global:
      resourcePrefix: '{{.metadata.annotations.resource_prefix}}'
      ingress_domain_name: '{{.metadata.annotations.ingress_domain_name}}'
```

**values.yaml (static values only):**
```yaml
# NO global section with dynamic values
nodeSelector:
  karpenter.sh/nodepool: system-peeks
tolerations:
  - key: CriticalAddonsOnly
    operator: Exists
```

### Incorrect Pattern

**❌ WRONG - values.yaml overriding dynamic values:**
```yaml
global:
  resourcePrefix: ""  # ❌ Will override dynamic template
  ingress_domain_name: ""  # ❌ Will override dynamic template

nodeSelector:
  karpenter.sh/nodepool: system-peeks
```

### Validation

When adding or modifying addon configurations:
1. Check that values.yaml does NOT contain `global.resourcePrefix` or `global.ingress_domain_name`
2. Verify dynamic templates are only in addons.yaml valuesObject
3. Confirm no empty string ("") placeholders for dynamic values

## Priority

High

## Error Handling

- If dynamic values appear in values.yaml, remove them and keep only in addons.yaml
- If empty strings are used for dynamic values, remove the entire global section from values.yaml
- If addon configuration is not working, check for value override conflicts
