# Backstage Template Integrations

This repo has following backstage templates which can be plugged in to your Internal Developer Portal via backstage readily:

- `create-dev-and-prod-env` backstage template enables you to deploy 2 EKS clusters for Dev and Prod application environments
- `eks-cost-monitoring` backstage template enables you to deploy an EKS cluster with cost monitoring tools on your cluster to enable your Kubernetes cluster with cost monitoring out of the box.
- `eks-istio` backstage template enables you to deploy an EKS cluster with istio as service mesh for managing networking and telemetry for your micro services.
- `eks-nvdia-gpu-efa` backstage template enables you to deploy an EKS cluster with GPU infrastructure to run ML and LLM based workloads.
- `eks-observability-accelerator` backstage template enables you to deploy an EKS cluster with complete suite of open source observability tooling out of the box.
- `eks-stateful-workload` backstage template enables you to deploy an EKS cluster with all necessary day 2 ops tooling to run stateful workloads on your kubernetes cluster.
- `jupyerhub-on-eks` backstage template enables you to deploy an EKS cluster with a setup to run JupyterHub notebook.
- `microservices` backstage template provides you with an ArgoCD app setup for your Git repo for GitOps based deployment on your EKS cluster.
- `microservices-with-repo` backstage template provides you with a Git repo and ArgoCD app setup for GitOps based deployment on your EKS cluster.
- `ray-serve` backstage template provides enables to you serve your ML models on your Kubernetes cluster via Ray Serve.
- `rds-cluster` backstage template provides you a mechanism to create an Amazon RDS cluster via CrossPlane from your Kubernetes cluster.
- `s3-bucket` backstage template provides you a mechanism to create an Amazon S3 bucket via CrossPlane from your Kubernetes cluster.
- `serverless-microservice` backstage template provides you a setup to deploy microservice on AWS environment via terraform backstage integrations.
- `spark-job` backstage template enables you to run a Spark Job for Data or ML engineering on your Kubernetes cluster.
- `spark-on-eks` backstage template enables you to deploy an EKS cluster with Spark operator to run Spark jobs.

Some of above patterns require you to install `crossplane`, `flux`, `tofu-controller`, `ray`, `spark` operators. If you have setup your backstage environment using our [AppMod Blueprints reference implementation on EKS](https://github.com/aws-samples/appmod-blueprints/tree/feature/modern-engg-integratedflow), you should be all set.
You can import these backstage templates manually via backstage console or you also use below config in `backstage-config` configmap.

```yaml
        - type: url
          target: https://github.com/aws-samples/appmod-blueprints/blob/main/platform/backstage/templates/catalog-info.yaml
          rules:
            - allow: [User, Group]
```

Alternative you can also use the below setup if you are using `idpbuilder`.

## 🏃‍♀️ Prerequisites

1. We might need a container engines such as `Docker Desktop`, `Podman` to run backstage crossplane integrations locally. Please check [this](https://github.com/cnoe-io/idpbuilder?tab=readme-ov-file#prerequisites) documentation to setup your container engine.

2. Download and install [idpbuilder](https://github.com/cnoe-io/idpbuilder?tab=readme-ov-file#download-and-install-the-idpbuilder) for running backstage crossplane integrations.

## 🌟 Implementation walkthrough

1. `idpBuilder` is extensible to launch custom Crossplane patterns using package extensions.

Please use the below command to deploy an IDP reference implementation with an Argo application for preparing up the setup for terraform integrations:

```bash
idpbuilder create \
  --use-path-routing \
  --package-dir https://github.com/cnoe-io/stacks//ref-implementation \
  --package-dir https://github.com/cnoe-io/stacks//crossplane-integrations \
  --package-dir https://github.com/cnoe-io/stacks//terraform-integrations
```

## What is installed?

- Crossplane Runtime
- Flux and Terraform controllers
- AWS providers
- Basic Compositions

2. Clone the [cnoe-io/stacks](https://github.com/cnoe-io/stacks) repository
3. Update [the credentials secret file](crossplane-providers/provider-secret.yaml)
4. Run the below command to create the crossplane provider secrets:

```bash
idpbuilder create \
  --use-path-routing \
  --package-dir https://github.com/cnoe-io/stacks//ref-implementation \
  --package-dir [path-to-stacks-repo]/crossplane-integrations \
  --package-dir [path-to-stacks-repo]//terraform-integrations
```

<details>
<summary> <b>Optional:</b> Add AWS Credentials</summary>

In case of deploying backstage templates which deploys terraform integrations, you will need access to your AWS account. You can follow the instructions below, to setup your AWS account with terraform integrations:

```bash
export AWS_ACCESS_KEY_ID=<FILL THIS>
export AWS_SECRET_ACCESS_KEY=<FILL THIS>
# Optional for IAM roles
export AWS_SESSION_TOKEN=<FILL THIS> 

# AWS Credentials for flux-system Namespace for TOFU Controller
cat << EOF > ./aws-secrets-tofu.yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials
  namespace: flux-system
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
  AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
  # Add this only if it's required. Optional for IAM roles
  AWS_SESSION_TOKEN: ${AWS_SESSION_TOKEN}
EOF

kubectl apply -f ./aws-secrets-tofu.yaml

```

</details>

5. Postgres credentials for RDS Database

```bash
cat << EOF > ./postgres-secret.yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: postgres-root-user-password
  namespace: crossplane-system
data:
  password: bXlzZWNyZXRQYXNzd29yZDEh # mysecretPassword1!
EOF
kubectl apply -f ./postgres-secret.yaml
```

6. Next, in the `idpbuilder` folder, navigate to `./ref-implementation/backstage/manifests/install.yaml` and add the following lines for catalog location at line 171 in backstage config to deploy crossplane backstage templates to backstage:

```yaml
        - type: url
          target: https://github.com/aws-samples/appmod-blueprints/blob/main/platform/backstage/templates/catalog-info.yaml
          rules:
            - allow: [User, Group]
```

7. Finally, run the following `idpbuilder` command to build and run the crossplane backstage integrations:

```bash
idpbuilder create \
  --use-path-routing \
  --package-dir https://github.com/cnoe-io/stacks//ref-implementation \
  --package-dir [path-to-stacks-repo]/crossplane-integrations \
  --package-dir [path-to-stacks-repo]//terraform-integration
```

