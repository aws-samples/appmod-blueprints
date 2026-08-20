# Helm Chart Dependencies

## Purpose

Ensures Helm chart dependencies are properly built when charts have dependency definitions.

## Instructions

### When to Run Helm Dependency Build

- ALWAYS run `task build-helm-dependencies` after cloning the repository for the first time (ID: HELM_DEPS_FIRST_CLONE)
- ALWAYS run `task build-helm-dependencies` when Chart.yaml dependencies are added or modified (ID: HELM_DEPS_CHART_CHANGES)
- ALWAYS run `task build-helm-dependencies` when dependency versions are updated in Chart.yaml (ID: HELM_DEPS_VERSION_UPDATES)
- ALWAYS run `task build-helm-dependencies` after pulling changes that affect charts with dependencies (ID: HELM_DEPS_AFTER_PULL)

### Charts with Dependencies

The following charts require dependency building:
- airflow (depends on airflow-1.18.0 from apache-airflow repo)
- devlake (depends on devlake from apache devlake repo)
- flux (depends on flux2 from fluxcd-community repo)
- jupyterhub (depends on jupyterhub from jupyterhub repo)
- kubevela (depends on vela-core from kubevela repo)
- mlflow (depends on mlflow from community-charts repo)
- spark-operator (depends on spark-operator from kubeflow repo)

### Task Commands

- `task build-helm-dependencies` - Build all chart dependencies
- `task check-helm-dependencies` - Check which charts have dependencies and verify Chart.lock files
- `task clean-helm-dependencies` - Clean generated Chart.lock files and charts/ directories

### Generated Files to Commit

ALWAYS commit the following generated files after running dependency build:
- Chart.lock files in each chart directory
- charts/ directories containing downloaded dependency .tgz files

## Priority

High

## Error Handling

- If dependency build fails, check that all required Helm repositories are accessible
- If Chart.lock files are missing, ArgoCD will fail to render the charts
- Never manually edit Chart.lock files - always regenerate with `helm dependency build`
