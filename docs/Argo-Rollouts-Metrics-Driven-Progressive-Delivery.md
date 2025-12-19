# Metrics Driven Progressive Delivery for Argo Rollouts with Amazon Managed Prometheus (AMP)

## Purpose

Previously, rollouts would complete or fail without the capability to incorporate custom performance metrics, users can now integrate a load testing job during progressive delivery. Combined with existing metrics tracking, the load test results can determine the success or failure of a rollout 
based on more granular performance data.

## Summarized instruction for platform setup
1) Edit the `opentelemetrycollector` in the `adot-collector-kubeprometheus` namespace to add the following `job_name`'s to `scrape_configs`
``` YAML
receivers:
    prometheus:
      config:
        scrape_configs:
          - job_name: 'otel-collector'
            scrape_interval: 5s
            static_configs:
              - targets: ['0.0.0.0:8888']
          - job_name: k8s
            kubernetes_sd_configs:
            - role: pod
```
2) Set up the trust relationship via an IRSA relationship to the service account associated with argo rollouts to the IAM Role that will grant `arn:aws:iam::aws:policy/AmazonPrometheusQueryAccess` permissions to argo rollouts. Ensure the associated pods are refreshed with the needed permissions as well.
3) Each environment will have a different endpoint for the AMP, this will have to be specified in the rollout. Add the amp-workspace to match this formatting.
    ``` YAML
    spec:
    args:
    - name: amp-workspace
        valueFrom:
        secretKeyRef:
            name: workspace-url
            key: secretUrl
    ```
## Prerequisite additions needed
In order to scrape the needed metrics from workloads the OTEL collector needs to be modified to pull data from the pods that exponse metrics on the /metrics endpoint.

The following command lets you check for said OTEL collector.
```
k get opentelemetrycollectors.opentelemetry.io -n adot-collector-kubeprometheus
```
The following command and code allows you to edit the needed OTEL collector. Inserting and saving the code snippet below allows for metrics to be pulled from workloads as stated above.
```
k edit opentelemetrycollector adot -n adot-collector-kubeprometheus
```
``` YAML
receivers:
    prometheus:
      config:
        scrape_configs:
          - job_name: 'otel-collector'
            scrape_interval: 5s
            static_configs:
              - targets: ['0.0.0.0:8888']
          - job_name: k8s
            kubernetes_sd_configs:
            - role: pod
```

## Progressive Delivery Strategies
While Argo Rollouts allows for BlueGreen Deployment and Canary Deployment the analysis section works the same. The following doc will break down how to create a Canary Deployment with Analysis Templates to add metric driven progressive delivery.

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
                - pause: {duration: 1} # 3 minuets if you add m otherwise seconds by default.
                - analysis: # Can insert this wherever in the rollout and if it fails it will roll back.
                    templates:
                    - templateName: success-rate-with-job # This is calling the analysis-teplate that includes the load testing job called success-rate-with-job.
                    args:
                    - name: service-name # Must match the Analysis Templates spec.args.name variable.
                        value: rust-app-deployment # This calls the deployment for the target application.
                - setWeight: 40
                - pause: {duration: 1}
                - setWeight: 60
                - pause: {duration: 1}
                - setWeight: 100
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
                    image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/app/rust-microservice:latest
                    env:
                        - name: dummy-variable # (Optional) Adding this allows you to test changes by updating the below value and applying the rollout again.
                        value: "triggering-rollout-test-1"
  ```
# Metrics Driven Progressive Delivery Code Breakdown
### Rollout File
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
                - pause: {duration: 1} # 3 minuets if you add m otherwise seconds by default.
                - analysis: # Can insert this wherever in the rollout and if it fails it will roll back.
                    templates:
                    - templateName: success-rate-with-job # This is calling the analysis-teplate that includes the load testing job called success-rate-with-job.
                    args:
                    - name: service-name # Must match the Analysis Templates spec.args.name variable.
                        value: rust-app-deployment # This calls the deployment for the target application.
                - setWeight: 40
                - pause: {duration: 1}
                - setWeight: 60
                - pause: {duration: 1}
                - setWeight: 100
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
                    image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/app/rust-microservice:latest
                    env:
                        - name: dummy-variable # (Optional) Adding this allows you to test changes by updating the below value and applying the rollout again.
                        value: "triggering-rollout-test-1"
  ```
#### Rollout Template Breakdown
The key section to keep in mind is the following piece of the code:
``` YAML
- analysis: # Can insert this wherever in the rollout and if it fails it will roll back.
    templates:
    - templateName: success-rate-with-job # This is calling the analysis-teplate that includes the load testing job called success-rate-with-job.
    args:
    - name: service-name # Must match the Analysis Templates spec.args.name variable.
        value: rust-app-deployment # This calls the deployment for the target application.
```
You can do analysis for different sections of the rollout, and call a variety of Analysis Templates to test different metrics. Otherwise, the rollout is simply targeting your workload, rolling out the update as you defined it, and testing custom defined metrics along the way. If at any time the workload fails a check it will rollback to the previous stable version.
### Analysis Template
``` YAML
    apiVersion: argoproj.io/v1alpha1
    kind: AnalysisTemplate
    metadata:
        name: success-rate-with-job
        namespace: argo-rollouts
    spec:
        args:
        - name: amp-workspace # This section is important to aquire needed workspace url details for Amazon Managed Prometheus (AMP).
            valueFrom:
            secretKeyRef:
                name: workspace-url # Name of the secret you need.
                key: secretURL # Key value containing the needed query address for AMP.
        metrics:
        - name: trigger-load-test
            interval: 1s
            count: 1  # Run the Job this many times.
            successCondition: result == 0  # The Job must succeed.
            provider:
                job: # This contains the needed template details to run the load test.
                    spec:  # Define the job spec here.
                    template:
                        spec:
                        containers:
                            - name: artillery-container
                            image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/test/rust-svc:latest
                            command: ["run", "run", "-t", "http://rust-app-svc.argo-rollouts.svc.cluster.local", "/scripts/benchmark.yaml"]
                        restartPolicy: Never
        - name: success-rate
            interval: 20s # The intervals that queries are made. Starts to query at the same time as the job above.
            count: 3
            successCondition: result[0] >= 100 # Set this to a threshold you wish that matches your query.
            # failureCondition: result[#] >= # is another format that will fail if its met.
            provider:
                prometheus:
                    address: "{{args.amp-workspace}}" # Gets the needed value from the secret to query AMP.
                    query: | # This query returns something similar to: {"status":"success","data":{"resultType":"vector","result":[{"metric":{},"value":[1728922812,"11778"]}]}}
                        sum(
                            rocket_http_requests_total{
                            cluster="peeks-spoke-dev",
                            endpoint="/metrics",
                            http_scheme="http",
                            k8s_container_name="rust-app",
                            k8s_namespace_name="rust-msvc",
                            method="GET",
                            region="us-west-2",
                            status="200"
                            }
                        )
                    authentication:
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
***Inserting a Job to the Analysis Template***
``` YAML
- name: trigger-load-test
    interval: 1s
    count: 1  # Run the Job this many times.
    successCondition: result == 0  # The Job must succeed.
    provider:
        job: # This contains the needed template details to run the load test.
            spec:  # Define the job spec here.
            template:
                spec:
                containers:
                    - name: artillery-container
                    image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/test/rust-svc:latest
                    command: ["run", "run", "-t", "http://rust-app-svc.argo-rollouts.svc.cluster.local", "/scripts/benchmark.yaml"]
                restartPolicy: Never
```
The trigger-load-test section is responsible for calling the load test job that will cause metrics to change for what you want to test.

***How to query changing metrics from the job***
``` YAML
prometheus:
    address: "{{args.amp-workspace}}" # Gets the needed value from the secret to query AMP.
    query: | # This query returns something similar to: {"status":"success","data":{"resultType":"vector","result":[{"metric":{"pod":"argo-rollouts-bdbddf5fb-xbkwr"},"value":[1722963891,"0.002951664136810593"]}]}}
        sum(
            rocket_http_requests_total{
            cluster="peeks-spoke-dev",
            endpoint="/metrics",
            http_scheme="http",
            k8s_container_name="rust-app",
            k8s_namespace_name="rust-msvc",
            method="GET",
            region="us-west-2",
            status="200"
            }
        )
```
This is a flexible section to query custom metrics from AMP. Due to it being right after the load test it gives the opportunity to query 
as it runs and pass/fail depending on how the metrics change.

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
            value: rust-app-deployment 
      - setWeight: 40
      - pause: {duration: 1} 
      - setWeight: 60
      - pause: {duration: 1}
      - analysis: # This points to a second Analysis Template that can pass/fail the rollout at this later stage.
          templates:
          - templateName: test-two
          args:
          - name: service-name 
            value: rust-app-deployment
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
        image: 913524909446.dkr.ecr.us-west-2.amazonaws.com/app/rust-microservice:latest
        env:
        - name: dummy-variable
          value: "triggering-rollout-test-1"
```