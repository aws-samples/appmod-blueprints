---
inclusion: fileMatch
fileMatchPattern: "**/ray/**/*,**/kubeflow/**/*,**/mlflow/**/*,**/airflow/**/*,**/jupyterhub/**/*"
---

# ML/AI Workloads Guidelines

## Platform Components

### Ray
Distributed computing framework for ML/AI workloads.

**Use Cases**:
- Distributed training
- Hyperparameter tuning
- Batch inference
- Data preprocessing

**Location**: `gitops/workloads/ray/`

**Key Features**:
- Auto-scaling clusters
- GPU support (including Trainium)
- S3 model caching
- Integration with MLflow

### Kubeflow
End-to-end ML platform on Kubernetes.

**Components**:
- Pipelines: ML workflow orchestration
- Notebooks: Interactive development
- Training Operators: Distributed training
- KServe: Model serving

**Location**: `gitops/addons/charts/kubeflow/`

### MLflow
ML experiment tracking and model registry.

**Features**:
- Experiment tracking
- Model versioning
- Model registry
- Model deployment

**Location**: `gitops/addons/charts/mlflow/`

### JupyterHub
Multi-user Jupyter notebook environment.

**Use Cases**:
- Interactive data exploration
- Model development
- Collaborative research

**Location**: `gitops/addons/charts/jupyterhub/`

### Airflow
Data pipeline orchestration.

**Use Cases**:
- ETL workflows
- Data preprocessing pipelines
- Scheduled ML training
- Model retraining automation

**Location**: `gitops/addons/charts/airflow/`

## Ray Development

### Ray Cluster Configuration
```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: ml-cluster
spec:
  rayVersion: '2.9.0'
  headGroupSpec:
    rayStartParams:
      dashboard-host: '0.0.0.0'
    template:
      spec:
        containers:
        - name: ray-head
          image: rayproject/ray:2.9.0-py310
          resources:
            limits:
              cpu: "2"
              memory: "8Gi"
  workerGroupSpecs:
  - replicas: 2
    minReplicas: 1
    maxReplicas: 10
    groupName: gpu-workers
    rayStartParams: {}
    template:
      spec:
        containers:
        - name: ray-worker
          image: rayproject/ray:2.9.0-py310-gpu
          resources:
            limits:
              nvidia.com/gpu: 1
              memory: "16Gi"
```

### GPU Inference Strategy
See: `docs/ray-gpu-inference-strategy.md`

Key considerations:
- Model loading and caching
- Batch processing
- GPU memory management
- Auto-scaling based on load

### S3 Model Caching
See: `docs/ray-s3-model-cache-implementation.md`

Benefits:
- Faster model loading
- Reduced network traffic
- Shared cache across workers
- Cost optimization

### Trainium Support
See: `docs/ray-trainium-quickstart.md`

AWS Trainium for cost-effective training:
- Custom ML accelerators
- Optimized for deep learning
- Integration with Ray
- Cost savings vs GPU

## Kubeflow Pipelines

### Pipeline Structure
```python
from kfp import dsl

@dsl.pipeline(
    name='Training Pipeline',
    description='ML model training pipeline'
)
def training_pipeline(
    data_path: str,
    model_name: str,
    epochs: int = 10
):
    # Data preprocessing
    preprocess_op = preprocess_data(data_path)
    
    # Model training
    train_op = train_model(
        preprocess_op.outputs['processed_data'],
        model_name,
        epochs
    )
    
    # Model evaluation
    eval_op = evaluate_model(
        train_op.outputs['model'],
        preprocess_op.outputs['test_data']
    )
    
    # Model registration
    register_op = register_model(
        train_op.outputs['model'],
        eval_op.outputs['metrics']
    )
```

### Best Practices
- Use pipeline parameters for flexibility
- Cache intermediate results
- Implement proper error handling
- Log metrics and artifacts
- Version pipelines

## MLflow Integration

### Experiment Tracking
```python
import mlflow

mlflow.set_tracking_uri("http://mlflow-server:5000")
mlflow.set_experiment("my-experiment")

with mlflow.start_run():
    # Log parameters
    mlflow.log_param("learning_rate", 0.01)
    mlflow.log_param("epochs", 100)
    
    # Train model
    model = train_model()
    
    # Log metrics
    mlflow.log_metric("accuracy", 0.95)
    mlflow.log_metric("loss", 0.05)
    
    # Log model
    mlflow.sklearn.log_model(model, "model")
```

### Model Registry
```python
# Register model
model_uri = f"runs:/{run_id}/model"
mlflow.register_model(model_uri, "my-model")

# Transition to production
client = mlflow.tracking.MlflowClient()
client.transition_model_version_stage(
    name="my-model",
    version=1,
    stage="Production"
)
```

## Resource Management

### GPU Allocation
- Request specific GPU types
- Use node selectors for GPU nodes
- Implement GPU sharing when appropriate
- Monitor GPU utilization

### Storage
- Use S3 for large datasets
- Mount EFS for shared storage
- Use PVCs for persistent data
- Implement data versioning

### Cost Optimization
- Use spot instances for training
- Auto-scale based on workload
- Implement resource quotas
- Monitor and optimize usage
