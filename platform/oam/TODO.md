# OAM Platform TODOs

## ConfigTemplate for global cluster metadata

The goal is to have a cluster-level config (`platform-env`) that all components can read via `$config` in CUE templates, eliminating the need for users to pass `envName`, `clusterName`, `region` as parameters.

### What's done
- Config template CUE at `platform/oam/definitions/configs/platform-env.cue`
- Secret template in Helm chart at `gitops/addons/charts/kubevela/templates/configs/platform-env.yaml`
- Values wired in `gitops/addons/bootstrap/default/addons.yaml` under `kubevela.valuesObject.platformEnv`

### What's broken
- `$config.platform.output.envName` returns `undefined field: output` in CUE templates
- Root cause: the config template has no `template.output` block, so `vela config create` stores data as a single `input-properties` JSON key in the Secret. `$config` needs an explicit `output` Secret definition with individual keys to resolve field access.

### Fix needed
Add `template.output` to `platform-env.cue`:
```cue
template: {
    output: {
        apiVersion: "v1"
        kind:       "Secret"
        metadata: {
            name:      context.name
            namespace: context.namespace
        }
        type: "Opaque"
        stringData: {
            envName:     parameter.envName
            clusterName: parameter.clusterName
            region:      parameter.region
        }
    }
    parameter: {
        envName:     string
        clusterName: string
        region:      string
    }
}
```

Then recreate the config:
```bash
vela config delete platform-env
vela config-template apply -f platform/oam/definitions/configs/platform-env.cue
vela config create platform-env --namespace vela-system --template=platform-env \
    envName=dev clusterName=peeks-spoke-dev region=us-west-2
```

### After fix
- Update `agentcore-memory.cue` to use `$config` for auto-generating `memoryName` with env prefix
- Update `dp-service-account.cue` to read `clusterName` and `region` from `$config` instead of parameters
- Update other components (dynamodb-table, s3-bucket) similarly
- Update Helm chart Secret template to match the `template.output` structure
