# Prod Cluster values stored in the AWS SSM Parameter Store

data "aws_ssm_parameter" "gitops_prod_argocd_authCA" {
  name = "/gitops/prod-argocdca"
}

data "aws_ssm_parameter" "gitops_prod_argocd_authN" {
  name = "/gitops/prod-argocd-token"
}

data "aws_ssm_parameter" "gitops_prod_argocd_serverurl" {
  name = "/gitops/prod-serverurl"
}

resource "kubectl_manifest" "argocd_prod_cluster-connect" {
  yaml_body = <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: prod-cluster-argo-secret
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  name: prod-cluster
  server: ${data.aws_ssm_parameter.gitops_prod_argocd_serverurl.value}
  config: |
    {
      "bearerToken": "${data.aws_ssm_parameter.gitops_prod_argocd_authN.value}",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "${data.aws_ssm_parameter.gitops_prod_argocd_authCA.value}"
      }
    }
YAML
}