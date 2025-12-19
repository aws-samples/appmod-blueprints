# Technical Details of the CUE Parameter Configuration

### Parameter Setup

The parameter `metrics` of type `#MetricGate` are added for metric configuration.

```cue
parameter:
  metrics?: #MetricGate
#MetricGate: {
    evaluationCriteria:
    [...{
            interval: *"1s" | string
            count: *1 | int
            function?: "sum" | "avg" | "max" | "min" | "count"
            successOrFailCondition: *"success" | "fail" # Two options of pass or fail.
            metric: string
            comparisonType: *">" | ">=" | "<" | "<=" | "==" | "!="
            threshold: *0 | number # Can be a whole number or decimal.
        }]
}
```

### Creates Analysis Template
```cue
if parameter.metrics !=  _|_ {
{
    analysis: {
        templates: [
            {
                templateName: "functional-metric-\(context.name)"
            }
        ],
        args: [
            {
                name: "service-name"
                value: previewService
            }
        ]
    }
}
}
```

## Creating Secrets from SSM Parameters in CUE
```cue
spec: {
    secretStoreRef: {
        name: "cluster-secretstore-sm"
        kind: "ClusterSecretStore"
    }
    target: {
        name: "amp-workspace"
        template: type: "Opaque"
    }
    data: [
        {
            secretKey: "amp-workspace-url"
            remoteRef: {
                key: "/platform/amp-workspace"
            }
        },
        {
            secretKey: "amp-workspace-region"
            remoteRef: {
                key: "/platform/amp-region"
            }
        }
    ]
}

...

args: [{
    name: "amp-workspace-url"
    valueFrom: secretKeyRef: {
        name: "amp-workspace"
        key: "amp-workspace-url"
    }
}, {
    name: "amp-workspace-region"
    valueFrom: secretKeyRef: {
        name: "amp-workspace"
        key: "amp-workspace-region"
    }
}]
```
These two sections are responsible for grabbing the needed values from the SSM parameters `/platform/amp-workspace` and `/platform/amp-region`, and then creates the secret `amp-workspace` with them defined as variables to be called.

# Sample Application Configuration for Rust App with Argo Rollouts and DynamoDB

The following configuration defines a Rust-based application that requires a DynamoDB table, a service account, and a backend service component configured with Argo Rollouts. 

- This application needs to be load tested for metrics to start generating. So calling the load test image in either performanceGate or functionalGate will trigger before metrics is called.
## Application Overview

```YAML
apiVersion: core.oam.dev/v1beta1
kind: Application
metadata:
  name: rust-app
spec:
  components:
    - name: dynamodb-table
      type: dynamodb-table
      properties:
        tableName: rust-service-table
        partitionKeyName: partition_key
        sortKeyName: sort_key 
        region: us-west-2
      traits:
        - type: component-iam-policy
          properties:
            service: dynamodb
    - name: rust-service-account
      type: dp-service-account
      properties:
        componentNamesForAccess:
          - dynamodb-table
        clusterName: peeks-spoke-dev
        clusterRegion: us-west-2
        dependsOn:
          - dynamodb-table
    - name: rust-backend
      type: appmod-service
      properties:
        image:  <image> # Target image for workload
        image_name: rust-microservice
        port: 80
        targetPort: 8080
        replicas: 5
        serviceAccount: "rust-service-account"
        functionalGate:
          pause: "10s" 
          image: "<image>"
        performanceGate:
          pause: "5s"
          image: "<image>"
        metrics:
          evaluationCriteria: [
            {
              interval: "1s", # user needs to add s, m, or h next to the number (second, minute, hour).
              count: 1,
              function: "sum", # Optional from list of "sum" | "avg" | "max" | "min" | "count"
              successOrFailCondition: "success", # "success" or "fail" as options.
              metric: "rocket_http_requests_total", # Required and is case and format sensitive.
              comparisonType: ">", # Options ">" | ">=" | "<" | "<=" | "==" | "!="
              threshold: 0
            },
            {
              interval: "1s", 
              successOrFailCondition: "success",
              function: "avg",
              metric: "rocket_http_requests_duration_seconds_sum",
              comparisonType: ">",
              threshold: 0
            },
            {
              interval: "1s", 
              count: 1,
              successOrFailCondition: "success",
              function: "max",
              metric: "rocket_http_requests_duration_seconds_count",
              comparisonType: ">",
              threshold: 0
            },
            {
              interval: "1s", 
              count: 1,
              function: "count",
              successOrFailCondition: "success",
              metric: "rocket_http_requests_duration_seconds_bucket",
              comparisonType: ">",
              threshold: 0
            },
            {
              interval: "1s", 
              count: 1,
              successOrFailCondition: "fail",
              metric: "rocket_http_requests_total",
              comparisonType: "<",
              threshold: 0
            }

          ]
      dependsOn:
        - rust-service-account
      traits: 
        - type: path-based-ingress
          properties:
            domain: "*.elb.us-west-2.amazonaws.com"
            rewritePath: true 
            http:
              /rust-app: 80
```
## Sample Application Breakdown
The following configuration specifies an application that includes a Rust-based backend. It requires a DynamoDB table and a service account, with `ComponentDefinitions` provided separately.

The main focus here is on configuring the `appmod-service` component, which leverages the solution setup when the application is ready. Below are the necessary fields to complete for a successful setup:

- **name**: `rust-backend` - Assign a name to your application.
- **type**: `appmod-service` - Designate this as the appmod solution.
- **properties**: Contains values required to set up Argo Rollouts properly.
  - `image`: `<image>` - Path to the container image running the application.
  - `image_name`: `rust-microservice` - Names the container it runs on.
  - `port`: `80` - The port for the application.
  - `targetPort`: `8080` - The application's target port.
  - `replicas`: `5` - The number of replicas for the rollout.
  - `serviceAccount`: `"rust-service-account"` - Service account name for the specified workload.
  - **metrics** (Optional): 
    - **evaluationCriteria**: Define an array of metrics to be tested. Each metric in the array specify the following values:
      - `interval`: `"1s"` - Specify interval with suffix `s`, `m`, or `h`.
      - `count`: `1`
      - `function`: `"sum"` - Optional. Choose a metric tracking augmentation function from `"sum"`, `"avg"`, `"max"`, `"min"`, `"count"`.
      - `successOrFailCondition`: `"success"` - Determines if the metric should pass or fail. Options are `"success"` or `"fail"`.
      - `metric`: `"rocket_http_requests_total"` - The case-sensitive name of the metric to track.
      - `comparisonType`: `">"` - Choose a comparison operator from `">"`, `">="`, `"<"`, `"<="`, `"=="`, `"!="`.
      - `threshold`: `0` - Specify a numeric threshold.

## Load testing rust-app to trigger inital metrics for the application
- See attached `applications/rust/integration/demo-build` folder for load testing which builds the image needed that is called by the `rust-application.yaml`

---
# Troubleshooting User Scenarios

If the given metric does not exist or returns nothing, you should expect an error in the **Rollout**:

- **Strategy:** Canary  
- **Name:** rust-backend  
- **Namespace:** test-123  
- **Status:** ✖ Degraded  
- **Message:** `RolloutAborted: Rollout aborted update to revision 16: Metric "metric[0]-rust-backend: rocket_http_reqsdfadfuests_total" assessed Error due to consecutiveErrors (5) > consecutiveErrorLimit (4): "Error Message: reflect: slice index out of range"`

---

If a metric fails the test/condition the user sets up, the first failure hit returns this in **Rollouts**:

- **Strategy:** Canary  
- **Name:** rust-backend  
- **Namespace:** test-123  
- **Status:** ✖ Degraded  
- **Message:** `RolloutAborted: Rollout aborted update to revision 13: Metric "metric[2]-rust-backend: rocket_http_requests_total" assessed Failed due to failed (1) > failureLimit (0)`

---

If `evaluationCriteria[]` values are of the wrong type specified that the CUE Manifest requires when they deploy their application, they get this as an **Application Message**:

- **Message:** `run step(provider=oam,do=component-apply): GenerateComponentManifest: evaluate base template app=rust-app in namespace=test-123: invalid cue template of workload rust-backend after merge parameter and context: parameter.metrics.evaluationCriteria.0.count: 2 errors in empty disjunction: (and 5 more errors)`

---

While default values work fine if they don't put a value in for one that has a default set up, if a user did not enter a required variable that lacks a default (like `metrics` inside of `evaluationCriteria`, for example), expect the following as an **Application Message**:

- **Message:** `run step(provider=oam,do=component-apply): GenerateComponentManifest: evaluate template trait=path-based-ingress app=rust-backend: cue: marshal error: outputs."success-rate-analysis-template".spec.metrics.1.name: invalid interpolation: non-concrete value string (type string)`