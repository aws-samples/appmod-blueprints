# Sync Wave Map

| Wave | Addons |
|------|--------|
| -5 | multi-acct |
| -3 | kro |
| -2 | kro-manifests, kro-manifests-hub |
| -1 | ACK controllers (iam, eks, ec2, ecr, s3, dynamodb, efs), external-secrets, platform-manifests-bootstrap |
| 0 | ArgoCD, metrics-server, ingress-class-alb |
| 1 | ingress-nginx, image-prepuller |
| 2 | cert-manager, gitlab |
| 3 | keycloak, argo-events, argo-rollouts, kyverno, kube-state-metrics, prometheus-node-exporter, opentelemetry-operator, kubevela, aws-for-fluentbit, keda |
| 4 | kyverno-policies, kyverno-policy-reporter, argo-workflows, kargo, backstage, grafana, grafana-operator, flux, aws-efs-csi-driver |
| 5 | cw-prometheus, cni-metrics-helper, jupyterhub, kubeflow, mlflow, ray-operator, spark-operator, airflow, litellm, langfuse, qdrant |
| 6 | crossplane-aws, platform-manifests, vllm, tei |
| 7 | devlake, openwebui, n8n |

## Guidelines

- Infrastructure addons: waves -5 to -1
- Core platform services: waves 0-2
- Identity and monitoring: wave 3
- Applications and tools: waves 4+
- GenAI stack: waves 5-7
- Choose wave based on what the addon depends on being ready
