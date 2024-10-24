# Metrics Driven Deployment for Argo Rollouts with Amazon Managed Prometheus

## Purpose

Previously, updates would either succeed or fail without the ability to track detailed metrics. With this new feature, users can now specify the metrics they want to monitor and set acceptable thresholds. Users can also now choose between a Canary, or BlueGreen Deployment Strategies.

## Setting up Service Account Identity Access Management (IAM) to allow querying

The following command will override an existing service account and set up the trust relationship to access Amazon Managed Prometheus. If any more commands are needed edit the policy attached here.
```
eksctl create iamserviceaccount --name argo-rollouts --namespace argo-rollouts --cluster appmod-dev --role-name argo-rollouts-service-account-123\
    --attach-policy-arn arn:aws:iam::aws:policy/AmazonPrometheusQueryAccess --approve --override-existing-serviceaccounts
```

If you wish to create a new service account to attach the trust relationship it's the same command minus the override command. This will create a service account with the given name if one does not already exist of that name.
```
eksctl create iamserviceaccount --name argo-rollouts --namespace argo-rollouts --cluster appmod-dev --role-name argo-rollouts-service-account-123\
    --attach-policy-arn arn:aws:iam::aws:policy/AmazonPrometheusQueryAccess
```

For both of the above commands a new IAM Role will be made with the given name and proper trust relationship setup. The trust relationship will look similar to the following:
```YAML
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::913524909446:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/A8B66B080A0DC952E31AC4F0B8C97A22"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "oidc.eks.us-west-2.amazonaws.com/id/A8B66B080A0DC952E31AC4F0B8C97A22:sub": "system:serviceaccount:argo-rollouts:argo-rollouts",
                    "oidc.eks.us-west-2.amazonaws.com/id/A8B66B080A0DC952E31AC4F0B8C97A22:aud": "sts.amazonaws.com"
                }
            }
        }
    ]
}
```
Note that the ```"system:serviceaccount:argo-rollouts:argo-rollouts"``` is in the format of ```"system:serviceaccount:<namespaceName>:<serviceAccountName>"```.

Ensure that the target service account has the annotation to target the IAM role created by the eksctl command's ARN value.
- Should look similar to the following: ```eks.amazonaws.com/role-arn: arn:aws:iam::<Insert-Isengard-Account-ID>:role/<Insert-Target-IAM-Role>```
- Code to apply this annotation can be found below if needed:
  ```
  kubectl annotate serviceaccount <Insert-Target-Service-Account> -n <Insert-Namespace> arn:aws:iam::<Insert-Isengard-Account-ID>:role/<Insert-Target-IAM-Role> --overwrite
  ```

## Deployment Strategies
While Argo Rollouts allows for BlueGreen Deployment and Canary Deployment the analysis section works the same. The following doc will break down how to create a Canary Deployment with Analysis Templates to add metric driven deployment.

  ### Rollout Template 
  ``` YAML
    apiVersion: argoproj.io/v1alpha1
    kind: Rollout
    metadata:
      name: rollouts-demo
      namespace: argo-rollouts
    spec:
      replicas: 5
      strategy:
        canary:
          steps:
          - setWeight: 20
          - pause: {duration: 1} # Duration is minuets if you add m otherwise seconds by default.
          - analysis: # Can insert this anywhere in the rollout steps and if it fails it will roll back.
              templates:
              - templateName: success-rate # This is calling the analysis-template file success-rate.
              args:
              - name: service-name # Must match the Analysis Templates spec.args.name variable.
                value: tomcat-example # This calls the deployment for the sample Java App.
          - setWeight: 40
          - pause: {duration: 1} # Adding a second to test a change to the rollout.
          - setWeight: 60
          - pause: {duration: 1}
          - setWeight: 80
          - pause: {duration: 1}
      revisionHistoryLimit: 2
      selector:
        matchLabels:
          app: rollouts-demo
      template:
        metadata:
          labels:
            app: rollouts-demo
        spec:
          containers:
          - name: rollouts-demo
            image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/prometheus-sample-tomcat-jmx:latest
            env:
            - name: dummy-variable # (Optional) Adding this allows you to test deployments by updating the value and applying the rollout again to test changes.
              value: "triggering-rollout-test-1"
  ```
# Metrics Driven Deployment Code Breakdown
### Rollout File
```YAML
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: rollouts-demo
  namespace: argo-rollouts
spec:
  replicas: 5
  strategy:
    canary:
      steps:
      - setWeight: 20 # Initially load 20% of the workload.
      - pause: {duration: 1} # Duration is minuets if you add m otherwise seconds by default.
      - analysis: # Can insert analysis wherever in the rollout and if it fails it will roll back.
          templates:
          - templateName: success-rate # This is calling the analysis-template of name success-rate.
          args:
          - name: service-name # Must match the Analysis Templates spec.args.name variable
            value: tomcat-example # This targets the deployment with the given workload being updated.
      - setWeight: 40
      - pause: {duration: 1}
      - setWeight: 60
      - pause: {duration: 1}
      - setWeight: 80 # Once finishing testing 80% weight it deploys the remaining 20%.
      - pause: {duration: 1}
  revisionHistoryLimit: 2 # The number of old ReplicaSets to retain.
  selector:
    matchLabels:
      app: rollouts-demo
  template:
    metadata:
      labels:
        app: rollouts-demo
    spec:
      containers:
      - name: rollouts-demo
        image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/prometheus-sample-tomcat-jmx:latest # Target workload image.
        env:
        - name: testing-variable # (Optional) Adding this allows you to test deployments by updating the value and applying the rollout again to test changes.
          value: "triggering-rollout-test-1"
```
#### Rollout Template Breakdown
The key section to keep in mind is the following piece of the code:
``` YAML
- analysis: # Can insert analysis wherever in the rollout and if it fails it will roll back.
    templates:
    - templateName: success-rate # This is calling the analysis-template of name success-rate.
    args:
    - name: service-name # Must match the Analysis Templates spec.args.name variable
      value: tomcat-example # This targets the deployment with the given workload being updated.
```
You can do analysis for different sections of the rollout, and call a variety of Analysis Templates to test different metrics. Otherwise, the rollout is simply targeting your workload, rolling out the update as you defined it, and testing custom defined metrics along the way. If at any time the workload fails a check it will rollback to the previous stable version.
### Analysis Template
``` YAML
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate # Name of analysis template upon creation, and is the name used by the rollout to target the analysis template.
  namespace: argo-rollouts
spec:
  args:
  - name: amp-workspace # This section is important to aquire needed workspace url details for Amazon Managed Prometheus (AMP).
    valueFrom:
      secretKeyRef:
        name: workspace-url # Name of the secret you need.
        key: secretURL # Key value containing the needed query address for AMP.
  metrics:
  - name: success-rate
    interval: 1s # The intervals that queries are made
    count: 1
    successCondition: result[0] >= 0 # The query returns an array and result[0] grabs the first value. The successCondition means it passes if true and fails the rollout if it is not met.
    provider:
      prometheus:
        address: "{{args.amp-workspace}}" # Gets the needed value from the secret to query AMP.
        query: | # This query returns something similar to: {"status":"success","data":{"resultType":"vector","result":[{"metric":{"pod":"argo-rollouts-bdbddf5fb-xbkwr"},"value":[1722963891,"0.002951664136810593"]}]}}
          sum(
            node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate{cluster="appmod-dev", namespace="argo-rollouts"}
            * on(namespace,pod)
            group_left(workload, workload_type) namespace_workload_pod:kube_pod_owner:relabel{cluster="appmod-dev", namespace="argo-rollouts", workload="argo-rollouts", workload_type="deployment"}
          ) by (pod)
        authentication: # This section targeting the region is required for authentication to Amazon Managed Prometheus.
          sigv4:
            region: us-west-2
```
#### Analysis Template Breakdown
successCondition, and failureCondition are two important factors to keep in mind and work as the names would suggest they should:
- successCondition: will pass if met, but fail otherwise.
- failureCondition: will fail if its value is met, and pass otherwise.
- A workload can have a multitude of successConditions and failureCondition's defined.
- If they are both present the first failure status will cause a rollback.
For the query section a user can divide two query results by each other in order to get a percentage for their success and failure conditions.

***Adding a secret variable for the Amazon Managed Prometheus (AMP) Workspace URL***

This section of code allows for the workspace url to be acquired during build time. This enables granting permissions needed for querying AMP, and otherwise would require deleting a pod that would then relaunch with the needed permissions if it's done post deployment.
``` YAML
spec:
  args:
  - name: amp-workspace
    valueFrom:
      secretKeyRef:
        name: workspace-url
        key: secretUrl
```
***Example with more than one Analysis Template***
```YAML
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: rollouts-demo
  namespace: argo-rollouts
spec:
  replicas: 5
  strategy:
    canary:
      steps:
      - setWeight: 20
      - pause: {duration: 1} 
      - analysis: # Works same as the previous example.
          templates:
          - templateName: test-one 
          args:
          - name: service-name 
            value: tomcat-example 
      - setWeight: 40
      - pause: {duration: 1} 
      - setWeight: 60
      - pause: {duration: 1}
      - analysis: # This points to a second Analysis Template that can pass/fail the rollout at this later stage.
          templates:
          - templateName: test-two
          args:
          - name: service-name 
            value: tomcat-example 
      - setWeight: 80
      - pause: {duration: 1}
  revisionHistoryLimit: 2
  selector:
    matchLabels:
      app: rollouts-demo
  template:
    metadata:
      labels:
        app: rollouts-demo
    spec:
      containers:
      - name: rollouts-demo
        image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/prometheus-sample-tomcat-jmx:latest
        env:
        - name: dummy-variable
          value: "triggering-rollout-test-1"
```