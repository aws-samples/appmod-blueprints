# KubeVela CUE Commands

## Apply CUE Definition

### Basic apply
```bash
# Apply CUE definition directly (creates ComponentDefinition in cluster)
vela def apply appmod-service.cue

# Apply to specific namespace
vela def apply appmod-service.cue --namespace default

# Dry-run (convert to CRD without applying)
vela def apply appmod-service.cue --dry-run

# Apply from URL
vela def apply https://my-host/my-component.cue

# Apply from stdin
cat appmod-service.cue | vela def apply -

# Apply entire directory
vela def apply ./defs/
```

## Working with Existing Definitions

### Get definition from cluster
```bash
# Get ComponentDefinition as YAML
vela def get appmod-service

# Get as CUE
vela def get appmod-service --format cue

# Get from file
vela def get -f appmod-service-component.yaml
```

### List definitions
```bash
# List all definitions
vela def list

# List in specific namespace
vela def list --namespace default
```

### Edit definition
```bash
# Edit definition in cluster
vela def edit appmod-service
```

### Delete definition
```bash
# Delete definition from cluster
vela def del appmod-service
```

## Common Workflows

### 1. Create ComponentDefinition from CUE file
```bash
# Preview what will be created
vela def apply appmod-service.cue --dry-run

# Apply to cluster
vela def apply appmod-service.cue --namespace vela-system

# Verify it was created
vela def get appmod-service
```

### 2. Extract CUE from existing ComponentDefinition
```bash
# Get from cluster as CUE
vela def get appmod-service --format cue > appmod-service.cue

# Or from YAML file
vela def get -f appmod-service-component.yaml --format cue > appmod-service.cue
```

### 3. Update existing definition
```bash
# Edit CUE file, then reapply
vela def apply appmod-service.cue

# Or edit directly in cluster
vela def edit appmod-service
```

### 4. Test definition with dry-run
```bash
# Preview the CRD that will be created
vela def apply appmod-service.cue --dry-run > preview.yaml

# Review the preview
cat preview.yaml
```

## Examples

### Apply appmod-service.cue
```bash
cd platform/oam

# Preview first
vela def apply appmod-service.cue --dry-run

# Apply to vela-system namespace
vela def apply appmod-service.cue --namespace vela-system

# Verify
vela def get appmod-service
```

### Export to YAML
```bash
# Convert CUE to ComponentDefinition YAML
vela def apply appmod-service.cue --dry-run > appmod-service-component.yaml

# Apply the YAML with kubectl
kubectl apply -f appmod-service-component.yaml
```

### Apply from URL
```bash
vela def apply https://raw.githubusercontent.com/org/repo/main/defs/my-component.cue
```

## Useful Flags

### vela def apply
- `--dry-run` - Convert to CRD without applying to cluster
- `--namespace` / `-n` - Target namespace (default: vela-system)
- `-y` / `--yes` - Assume yes for all prompts
- `-V` / `--verbosity` - Log level verbosity

### vela def get
- `--format` - Output format (yaml, cue)
- `-f` - Get from file instead of cluster

### vela def list
- `--namespace` / `-n` - List from specific namespace

## CUE File Structure

A valid KubeVela CUE definition must have:

```cue
// Required: output defines the main resource
output: {
  apiVersion: "..."
  kind: "..."
  // ...
}

// Optional: outputs defines additional resources
outputs: {
  "resource-name": {
    apiVersion: "..."
    kind: "..."
    // ...
  }
}

// Required: parameter defines the input schema
parameter: {
  field1: string
  field2: *"default" | string
  // ...
}
```

## References

- [VelaD CLI Reference](https://kubevela.io/docs/cli/vela_def)
- [CUE Basic](https://kubevela.io/docs/platform-engineers/cue/basic)
- [Component Definition](https://kubevela.io/docs/platform-engineers/components/custom-component)
