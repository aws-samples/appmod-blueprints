---
name: rgd-authoring
description: Write ResourceGraphDefinitions for kro. Use when creating RGDs, defining schemas, writing CEL expressions, configuring resources, external references, collections, or cluster-scoped CRDs.
allowed-tools: Read, Grep, Glob
---

# Workflow

When this skill is invoked:

1. **Determine what the user needs**:

   - RGD only → output the ResourceGraphDefinition
   - Instance only → find the existing RGD, then output a matching instance
   - Both → output both the RGD and an example instance
   - Unclear → ask the user which they need

2. **Gather requirements**:

   - For RGDs: the user must specify what resources to orchestrate. If not provided, ask.
   - For instances: search for the target RGD in the codebase to understand its schema.

3. **Output**: Present YAML in code blocks. Keep explanations brief and focused on non-obvious choices.

# RGD Authoring Reference

One annotated example covering all features.

```yaml
apiVersion: kro.run/v1alpha1
kind: ResourceGraphDefinition
metadata:
  name: web-platform
spec:
  schema:
    # API IDENTIFICATION
    # These define the GVK for the generated CRD. All three are immutable.
    apiVersion: v1alpha1                    # Required. Pattern: v[0-9]+(alpha|beta)?[0-9]*
    kind: WebPlatform                       # Required. PascalCase, max 63 chars
    group: mycompany.io                     # Optional. Defaults to "kro.run"

    # SCOPE
    # Controls whether the generated CRD is namespaced or cluster-scoped.
    # Default: Namespaced. Immutable after creation.
    # When Cluster: all namespaced child resources MUST set metadata.namespace explicitly.
    scope: Namespaced                       # "Namespaced" (default) or "Cluster"

    # CUSTOM TYPES
    # Reusable type definitions. Reference in spec using the type name.
    types:
      DatabaseSpec:
        name: string | required=true
        storage: string | default="10Gi"
        backupEnabled: boolean | default=true

    # SPEC - User inputs
    # SimpleSchema syntax: type | marker=value marker2=value2
    spec:
      # Basic types with validation markers
      name: string | required=true immutable=true description="Application name"
      image: string | required=true
      replicas: integer | default=3 minimum=1 maximum=100

      # String validation
      email: string | pattern="^[\\w.-]+@[\\w.-]+\\.\\w+$"
      username: string | minLength=3 maxLength=20

      # Enum - allowed values
      environment: string | enum="dev,staging,prod" default="dev"

      # Nested object - defaults to {} if not provided by user
      ingress:
        enabled: boolean | default=false
        host: string
        path: string | default="/"
        tls: boolean | default=false

      # Array types - quote complex types
      ports: "[]integer | default=[80]"
      tags: "[]string | uniqueItems=true minItems=1 maxItems=10"

      # Map types
      labels: "map[string]string"
      env: "map[string]string"

      # Custom type reference (defined above in types)
      databases: "[]DatabaseSpec"

      # Unstructured object - use sparingly, disables validation
      extraConfig: object

    # STATUS - Computed from resources via CEL expressions
    # Types are inferred from the expression return type.
    status:
      # Single expression - can be any type
      availableReplicas: ${deployment.status.availableReplicas}
      ready: ${deployment.status.availableReplicas >= schema.spec.replicas}

      # String template - multiple expressions, all must return strings
      endpoint: "https://${service.metadata.name}.${service.metadata.namespace}.svc"

      # Use string() to convert non-strings in templates
      summary: "Replicas: ${string(deployment.status.replicas)}"

      # Aggregating from collections
      databaseCount: ${size(databases)}
      allDatabasesReady: ${databases.all(db, db.status.?phase == "Ready")}

      # Structured status object
      connection:
        host: ${service.spec.clusterIP}
        port: ${service.spec.ports[0].port}

      # Status array with individual elements
      endpoints:
        - ${service.status.loadBalancer.ingress[0].hostname}
        - ${service.status.loadBalancer.ingress[1].hostname}

      # Status array from multiple resources
      databaseEndpoints:
        - ${database1.status.endpoint}
        - ${database2.status.endpoint}

    # PRINTER COLUMNS - Custom kubectl get output
    additionalPrinterColumns:
      - name: Replicas
        type: integer
        jsonPath: .spec.replicas
      - name: Available
        type: integer
        jsonPath: .status.availableReplicas
      - name: Age
        type: date
        jsonPath: .metadata.creationTimestamp

  # RESOURCES
  # Each resource needs: id (lowerCamelCase) + template OR externalRef
  # Recommended field order: id, forEach, readyWhen, includeWhen, template/externalRef
  resources:

    # EXTERNAL REFERENCE (SCALAR)
    # Reads a single existing resource by name, never creates/updates/deletes it.
    # kro watches the resource and re-reconciles when it changes.
    # readyWhen and includeWhen CAN be used with externalRef.
    - id: platformConfig
      readyWhen:
        - ${platformConfig.data.?ready == "true"}
      includeWhen:
        - ${schema.spec.usePlatformConfig}
      externalRef:
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: platform-config
          namespace: platform-system       # Optional, defaults to instance namespace

    # EXTERNAL REFERENCE (COLLECTION)
    # Uses label selectors to match multiple existing resources.
    # Supports matchLabels and matchExpressions with CEL in selector values.
    # Exposed as an array to other resources (like forEach collections).
    # forEach CANNOT be used with externalRef.
    # An empty selector matches ALL resources of the given kind across all namespaces.
    - id: teamConfigs
      externalRef:
        apiVersion: v1
        kind: ConfigMap
        metadata:
          selector:
            matchLabels:
              team: ${schema.spec.teamName}
            matchExpressions:
              - key: environment
                operator: In
                values:
                  - ${schema.spec.environment}

    # BASIC RESOURCE WITH CEL EXPRESSIONS
    # ${...} wraps CEL. References create implicit dependencies.
    - id: deployment
      readyWhen:
        - ${deployment.status.availableReplicas > 0}
        - ${deployment.status.conditions.exists(c, c.type == "Available" && c.status == "True")}
      template:
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: ${schema.spec.name}
          namespace: ${schema.metadata.namespace}
          labels: ${schema.spec.labels}
        spec:
          replicas: ${schema.spec.replicas}
          selector:
            matchLabels:
              app: ${schema.spec.name}
          template:
            metadata:
              labels:
                app: ${schema.spec.name}
            spec:
              containers:
                - name: app
                  image: ${schema.spec.image}
                  ports:
                    - containerPort: ${schema.spec.ports[0]}
                  env:
                    # Reference external resource with ? for untyped fields
                    - name: PLATFORM_URL
                      value: ${platformConfig.data.?platformUrl.orValue("http://default")}
                    # Ternary conditional
                    - name: LOG_LEVEL
                      value: ${schema.spec.environment == "prod" ? "warn" : "debug"}
                    # omit() - conditionally remove field entirely (feature-gated: CELOmitFunction)
                    # Drops the field from SSA payload instead of writing empty/null.
                    # CANNOT be used on required metadata fields (name, namespace, apiVersion, kind).
                    - name: KMS_KEY
                      value: ${schema.spec.kmsKeyID != "" ? schema.spec.kmsKeyID : omit()}

    # RESOURCE WITH REFERENCE TO OTHER RESOURCE
    # Creates dependency: service waits for deployment
    - id: service
      template:
        apiVersion: v1
        kind: Service
        metadata:
          name: ${schema.spec.name}
        spec:
          selector:
            app: ${deployment.spec.template.metadata.labels.app}
          ports:
            - port: 80
              targetPort: ${schema.spec.ports[0]}

    # CONDITIONAL RESOURCE
    # includeWhen: all conditions must be true (AND logic).
    # Can reference schema.spec AND upstream resources.
    # Resource references in includeWhen create real DAG dependencies.
    # If false, resource AND all its dependents are skipped.
    - id: ingress
      includeWhen:
        - ${schema.spec.ingress.enabled}
      template:
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        metadata:
          name: ${schema.spec.name}
        spec:
          rules:
            - host: ${schema.spec.ingress.host}
              http:
                paths:
                  - path: ${schema.spec.ingress.path}
                    pathType: Prefix
                    backend:
                      service:
                        name: ${service.metadata.name}
                        port:
                          number: 80

    # CONDITIONAL REFERENCING AN UPSTREAM RESOURCE
    # includeWhen can depend on other resources, not just schema.spec.
    - id: certificate
      includeWhen:
        - ${schema.spec.ingress.enabled}
        - ${schema.spec.ingress.tls}
        - ${ingress.status.?conditions.exists(c, c.type == "Ready" && c.status == "True")}
      template:
        apiVersion: cert-manager.io/v1
        kind: Certificate
        metadata:
          name: ${schema.spec.name}-tls
        spec:
          secretName: ${schema.spec.name}-tls
          dnsNames:
            - ${schema.spec.ingress.host}

    # COLLECTION (forEach)
    # Creates multiple resources from single definition.
    # forEach CANNOT be used with externalRef.
    # Iterator variable available in template.
    # Max collection size: 1000 items. Max forEach dimensions: 5.
    - id: databases
      forEach:
        - dbSpec: ${schema.spec.databases}
      # readyWhen in collections uses `each` keyword (not the resource id)
      readyWhen:
        - ${each.status.?phase == "Ready"}
      template:
        apiVersion: database.example.com/v1
        kind: PostgreSQL
        metadata:
          # MUST include iterator variable for unique names
          name: ${schema.metadata.name}-${dbSpec.name}
        spec:
          storage: ${dbSpec.storage}

    # COLLECTION WITH FILTER
    # Use filter() to exclude items (includeWhen is all-or-nothing for collections)
    - id: backupJobs
      forEach:
        - dbSpec: ${schema.spec.databases.filter(d, d.backupEnabled)}
      template:
        apiVersion: batch/v1
        kind: CronJob
        metadata:
          name: ${schema.metadata.name}-backup-${dbSpec.name}
        spec:
          schedule: "0 2 * * *"
          jobTemplate:
            spec:
              template:
                spec:
                  containers:
                    - name: backup
                      image: backup-tool:latest

    # CARTESIAN PRODUCT (multiple iterators)
    # regions × tiers = creates resource for each combination
    - id: regionalConfigs
      forEach:
        - region: ${["us-east", "us-west", "eu-west"]}
        - tier: ${["web", "api"]}
      template:
        apiVersion: v1
        kind: ConfigMap
        metadata:
          # Creates: myapp-us-east-web, myapp-us-east-api, myapp-us-west-web, ...
          name: ${schema.metadata.name}-${region}-${tier}
        data:
          region: ${region}
          tier: ${tier}

    # REFERENCING A COLLECTION (including external collections)
    # Collection exposed as array. Use CEL functions to aggregate.
    - id: summary
      template:
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: ${schema.metadata.name}-summary
        data:
          databaseNames: ${databases.map(db, db.metadata.name).join(",")}
          totalDatabases: ${string(size(databases))}
          allReady: ${string(databases.all(db, db.status.?phase == "Ready"))}
          # Reference external collection
          teamConfigCount: ${string(size(teamConfigs))}

    # ITERATE USING INDEX
    # Use lists.range() to get indices
    - id: indexedPods
      forEach:
        - idx: ${lists.range(schema.spec.replicas)}
      template:
        apiVersion: v1
        kind: Pod
        metadata:
          name: ${schema.metadata.name}-worker-${string(idx)}
        spec:
          containers:
            - name: worker
              image: ${schema.spec.image}
              env:
                - name: WORKER_INDEX
                  value: ${string(idx)}
```

## Instance Example

Once the RGD above is applied, kro generates a CRD. Users then create instances:

```yaml
apiVersion: mycompany.io/v1alpha1
kind: WebPlatform
metadata:
  name: my-app
  namespace: production
  annotations:
    # Uncomment to pause reconciliation (kro will stop managing this instance)
    # kro.run/reconcile: suspended
spec:
  # Required fields
  name: my-app
  image: nginx:1.25

  # Optional with defaults (can omit)
  replicas: 5 # default: 3
  environment: prod # default: dev

  # String validation
  email: admin@mycompany.io
  username: appuser

  # Nested object
  ingress:
    enabled: true
    host: my-app.mycompany.io
    tls: true
    # path defaults to "/"

  # Arrays
  ports:
    - 80
    - 443
  tags:
    - production
    - critical

  # Maps
  labels:
    team: platform
    cost-center: engineering
  env:
    LOG_FORMAT: json
    METRICS_PORT: "9090"

  # Custom type array
  databases:
    - name: primary
      storage: 50Gi
      backupEnabled: true
    - name: analytics
      storage: 100Gi
      backupEnabled: false

  # Unstructured (any valid YAML)
  extraConfig:
    customSetting: value
    nested:
      anything: goes
```

The resulting status (populated by kro from resource states):

```yaml
status:
  availableReplicas: 5
  ready: true
  endpoint: https://my-app.production.svc
  summary: "Replicas: 5"
  databaseCount: 2
  allDatabasesReady: true
  connection:
    host: 10.96.45.123
    port: 80
  databaseEndpoints:
    - primary.mycompany.io:5432
    - analytics.mycompany.io:5432
```

## Quick Reference

| Feature                | Syntax                                      | Scope                                            |
| ---------------------- | ------------------------------------------- | ------------------------------------------------ |
| CEL expression         | `${expression}`                             | Any field value                                  |
| String template        | `"prefix-${expr}-suffix"`                   | String fields only, all exprs must return string |
| Escape shell `${VAR}`  | `${"${VAR}"}`                               | Produces literal `${VAR}` in output              |
| Reference schema       | `${schema.spec.fieldName}`                  | Instance spec values                             |
| Reference metadata     | `${schema.metadata.name}`                   | Instance name/namespace/labels/annotations       |
| Reference resource     | `${resourceId.spec.field}`                  | Creates dependency                               |
| Optional field         | `${resource.field.?maybeField}`             | Returns null if missing                          |
| Default value          | `${resource.data.?key.orValue("default")}`  | Fallback for optional                            |
| Conditional            | `${condition ? valueIfTrue : valueIfFalse}` | Ternary                                          |
| omit()                 | `${cond ? value : omit()}`                  | Drop field from SSA payload (feature-gated)      |
| includeWhen            | References `schema.spec` or resources       | All conditions AND, creates DAG deps             |
| readyWhen (resource)   | Can only reference self by id               | All conditions AND                               |
| readyWhen (collection) | Uses `each` keyword                         | Per-item check                                   |
| forEach                | `- varName: ${arrayExpression}`             | Variable available in template                   |
| scope                  | `scope: Cluster` or `scope: Namespaced`     | Controls CRD scope (default: Namespaced)         |
| externalRef scalar     | `metadata.name` + optional `namespace`      | Single resource lookup, watched                  |
| externalRef collection | `metadata.selector.matchLabels`             | Multi-resource lookup via selectors, watched     |
| Suspend reconciliation | annotation `kro.run/reconcile: suspended`   | Pauses instance reconciliation                   |

## CEL Libraries Reference

| Library    | Functions / Features                                                     |
| ---------- | ------------------------------------------------------------------------ |
| Lists      | `filter()`, `map()`, `all()`, `exists()`, `size()`, `sortBy()`, `lists.range()`, `lists.concat()`, `lists.setAtIndex()`, `lists.insertAtIndex()`, `lists.removeAtIndex()` |
| Strings    | `contains()`, `startsWith()`, `endsWith()`, `matches()`, `replace()`, `split()`, `join()`, `trim()`, `lowerAscii()`, `upperAscii()` |
| JSON       | `json.marshal(value) → string`, `json.unmarshal(string) → dyn`          |
| Maps       | `map.merge(other) → map` (second-map-wins)                              |
| Quantity   | Parse/manipulate k8s quantities (`"500m"`, `"2Gi"`) natively            |
| Hash       | `hash.fnv64a(string)`, `hash.sha256(string)`, `hash.md5(string)` → bytes |
| Random     | `random.seededInt(min, max, seed)` → deterministic int from seed        |
| Bind       | `cel.bind(varName, init, body)` - name intermediate values              |
| Encoders   | Base64/URL encoding                                                      |
| URLs       | URL parsing/formatting                                                   |
| Regex      | Pattern matching                                                         |
| Comprehensions | `transformMap(k, v, expr)`, `transformList(k, v, expr)`, `sortBy(x, expr)` |

## Key Rules

### Naming Constraints

- Resource `id` must be lowerCamelCase (e.g., `deployment`, `webServer`, `postgresDb`)
- Resource `id` cannot contain hyphens (interpreted as subtraction in CEL) or underscores
- `kind` must be UpperCamelCase/PascalCase (e.g., `WebPlatform`, `MyApp`)
- `apiVersion` must match pattern `v[0-9]+(alpha|beta)?[0-9]*` (e.g., `v1`, `v1alpha1`, `v1beta2`)
- Resource IDs must be unique within an RGD (no duplicates)
- Iterator names in `forEach` must also be lowerCamelCase and unique within that resource
- Iterator names cannot conflict with resource IDs

### Reserved Keywords (Cannot Use as Resource IDs)

CEL reserved: `true`, `false`, `null`, `in`, `as`, `break`, `const`, `continue`, `else`, `for`, `function`, `if`, `import`, `let`, `loop`, `package`, `namespace`, `return`, `var`, `void`, `while`

kro reserved: `schema`, `instance`, `each`, `item`, `items`, `spec`, `status`, `metadata`, `kind`, `apiVersion`, `resources`, `kro`, `self`, `this`, `root`, `context`, `graph`, `runtime`, `version`, `object`, `resource`, `namespace`, `dependency`, `dependencies`, `variables`, `vars`, `externalRef`, `externalReference`, `externalRefs`, `externalReferences`, `resourcegraphdefinition`, `resourceGraphDefinition`, `serviceAccountName`

### Schema Rules

- Nested objects in `spec.schema` default to `{}` if not provided by user
- Status fields MUST reference at least one resource (cannot be pure `schema.spec` expressions)
- Status types are inferred from CEL expression return types
- String templates (multiple `${...}` in one value) require ALL expressions to return strings
- `scope: Cluster` makes the generated CRD cluster-scoped; namespaced child resources must explicitly set `metadata.namespace`
- `scope` is immutable after RGD creation

### Resource Rules

- Each resource requires `id` + either `template` OR `externalRef` (exactly one)
- Templates must have `apiVersion`, `kind`, and `metadata` fields
- Scalar `externalRef.metadata` can only have `name` and `namespace`
- Collection `externalRef.metadata` uses `selector` with `matchLabels` and/or `matchExpressions`
- Selector values accept CEL expressions (`${schema.spec.teamName}`)
- An empty selector matches ALL resources of that kind across all namespaces
- `externalRef` namespace defaults to instance namespace if omitted
- `forEach` cannot be used with `externalRef`
- `readyWhen` and `includeWhen` can be used with `externalRef`
- kro watches external references and re-reconciles on changes automatically
- Resource field order: `id`, `forEach`, `readyWhen`, `includeWhen`, `template`/`externalRef`
- Collection size limit: 1000 items. forEach dimension limit: 5.

### Expression Constraints

- `includeWhen` can reference `schema.spec` AND other resources; resource references create real DAG dependencies and participate in cycle detection
- `readyWhen` can only reference the resource itself by `id` (or `each` for collections)
- `readyWhen` and `includeWhen` must return `bool` or `optional_type(bool)`
- Collections use `each` in `readyWhen`, not the resource id
- forEach iterators cannot reference other iterators (they're independent for cartesian product)
- Circular dependencies between resources are detected and rejected at RGD creation
- `omit()` is rejected on required metadata fields (`name`, `namespace`, `apiVersion`, `kind`)
- `omit()` requires the `CELOmitFunction` feature gate to be enabled

### Dependency Behavior

- CEL references to other resources create implicit dependencies
- When `includeWhen` is false, all dependent resources (those referencing it via CEL) are also skipped
- Collections (both forEach and external) are exposed as arrays to other resources (use `map()`, `filter()`, `all()`, `sortBy()`, etc.)
- kro waits for referenced resources to exist before creating dependent resources

### Type Checking

- All CEL expressions are type-checked at RGD creation time (not runtime)
- Expression output types must match target field types
- Structural compatibility: output struct can have fewer fields than expected, but NOT extra fields
- Use `?` operator for fields with unknown structure (ConfigMap data, etc.) - returns null if missing
- Use `.orValue("default")` to provide fallbacks for optional fields

### Graph Revisions

- Each RGD spec change creates an immutable `GraphRevision` (short name: `gr`)
- Revisions are compiled and validated independently before instances use them
- If the latest revision fails compilation, instances block (no silent fallback)
- Inspect: `kubectl get gr`, `kubectl get gr -l internal.kro.run/resource-graph-definition-name=my-rgd`
- Retention: last 5 revisions per RGD (configurable via `config.rgd.maxGraphRevisions`)
- Revision numbers are monotonic, never reused

### Feature Gates

| Gate                      | Default | Stage | Purpose                                        |
| ------------------------- | ------- | ----- | ---------------------------------------------- |
| `CELOmitFunction`         | `false` | Alpha | Enables `omit()` for conditional field removal |
| `InstanceConditionEvents` | `false` | Alpha | Emits k8s Events on status condition changes   |

Configure via Helm (`config.featureGates.CELOmitFunction: true`) or `--feature-gates CELOmitFunction=true`.

### Operational

- Pause reconciliation: annotate instance with `kro.run/reconcile: suspended`
- kro-owned labels cannot be set in resource templates (rejected at build time)
