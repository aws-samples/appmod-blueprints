function grafana (){
  kubectl --context ${HUB_CLUSTER_NAME:-peeks-hub-cluster} -n grafana-operator port-forward svc/grafana-service 3000:3000
}
