function argocd_kill_port_forward (){
	pkill -9 -f "kubectl --context $1 port-forward svc/argocd-server -n argocd $2:80"
}

function argocd_credentials (){
	argocd_kill_port_forward $1 $2
    kubectl --context $1 port-forward svc/argocd-server -n argocd $2:80 >/dev/null 2>&1 &
    # wait for port-forward to be up
    sleep 3
	export ARGOCD_PWD=$(kubectl get secrets argocd-initial-admin-secret -n argocd --template='{{index .data.password | base64decode}}' --context $1)
    argocd login "localhost:$2" --plaintext --username admin --password $ARGOCD_PWD --name $1
	echo "ArgoCD Username: admin"
	echo "ArgoCD Password: $ARGOCD_PWD"
	echo "ArgoCD URL: $IDE_URL/proxy/$2"
}

function argocd_hub_credentials (){
	argocd_credentials ${HUB_CLUSTER_NAME:-peeks-hub-cluster} 8081
}
function argocd_dev_credentials (){
	argocd_credentials ${SPOKE_CLUSTER_NAME_PREFIX:-peeks-spoke}-dev 8082
}
function argocd_prod_credentials (){
	argocd_credentials ${SPOKE_CLUSTER_NAME_PREFIX:-peeks-spoke}-prod 8083
}




