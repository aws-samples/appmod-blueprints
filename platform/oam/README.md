# OAM definitions (CUE sources)

The KubeVela ComponentDefinitions and TraitDefinitions shipped by the `kubevela`
addon are authored here in CUE. The YAML under
`gitops/addons/charts/kubevela/templates/{components,traits}/` is generated from these
files. Do not edit the YAML; it is overwritten on the next generation.

```
platform/oam/
├── definitions/
│   ├── components/   -> gitops/addons/charts/kubevela/templates/components/
│   └── traits/       -> gitops/addons/charts/kubevela/templates/traits/
└── generate.sh
```

Each `.cue` file produces the YAML file of the same name.

## Regenerating

```bash
platform/oam/generate.sh
git diff --stat -- gitops/addons/charts/kubevela/templates
```

Requirements:

- the `vela` CLI
- a reachable KubeVela cluster in the current kube context. `vela def render`
  resolves CUE packages from the cluster and fails without one.

After regenerating, confirm that only the definitions you changed appear in the
diff. An unrelated file in the diff means its YAML had drifted from its CUE source.
Commit the `.cue` change and the regenerated YAML together.

If one `.cue` file fails to parse, `vela def render` still writes the others in that
directory and the script exits non-zero, so check `git status` before committing.

## Helm values inside CUE

The generated YAML is a Helm template, so Helm runs before KubeVela parses the CUE.
That gives two cases:

- **Ambient platform values** (region, account): write a Helm placeholder in a CUE
  default, for example `region: *"{{ .Values.global.awsRegion }}" | string`. Helm
  substitutes it at chart render time. See `traits/aws-service-identity.cue`.
- **A literal `{{ ... }}` that must survive Helm** (for example an Argo Rollouts
  analysis arg): escape it for Helm and wrap it in a CUE raw string, so the source is
  valid CUE and Helm still emits the braces:

  ```cue
  let ampWorkspaceUrl = #"{{ "{{" }}args.amp-workspace-url{{ "}}" }}"#
  ```

## Notes

- `import` statements go at file scope, not inside `template: {}`.
- `vela def render` does not emit `metadata.namespace`. Definitions are installed in
  the chart's release namespace (`vela-system`).
- `traits/aws-service-identity.cue` is the same file as it was in
  open-agentic-platform before it moved here.
