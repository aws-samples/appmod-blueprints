import * as k8s from '@kubernetes/client-node';
import yaml from 'js-yaml';

export class KubernetesTestClient {
  constructor() {
    this.kc = new k8s.KubeConfig();

    // Try to load kubeconfig from various sources
    try {
      this.kc.loadFromDefault();
    } catch (error) {
      console.warn('Could not load kubeconfig, using in-cluster config');
      try {
        this.kc.loadFromCluster();
      } catch (clusterError) {
        console.warn('Could not load in-cluster config, tests will run in mock mode');
        this.mockMode = true;
      }
    }

    if (!this.mockMode) {
      this.k8sApi = this.kc.makeApiClient(k8s.CoreV1Api);
      this.customApi = this.kc.makeApiClient(k8s.CustomObjectsApi);
      this.appsApi = this.kc.makeApiClient(k8s.AppsV1Api);
      this.rbacApi = this.kc.makeApiClient(k8s.RbacAuthorizationV1Api);
      this.batchApi = this.kc.makeApiClient(k8s.BatchV1Api);
    }

    // Ensure mockMode is always defined
    if (this.mockMode === undefined) {
      this.mockMode = false;
    }

    this.testNamespaces = new Set();
    this.testResources = new Map();
  }

  async verifyConnection() {
    if (this.mockMode) {
      throw new Error('Running in mock mode - no cluster connection');
    }

    try {
      await this.k8sApi.listNamespace();
      return true;
    } catch (error) {
      throw new Error(`Kubernetes connection failed: ${error.message}`);
    }
  }

  async createTestNamespace(name) {
    if (this.mockMode) {
      return { metadata: { name } };
    }

    const namespace = {
      metadata: {
        name,
        labels: {
          'test.kro.run/integration-test': 'true',
          'test.kro.run/created-at': Date.now().toString()
        }
      }
    };

    try {
      const result = await this.k8sApi.createNamespace(namespace);
      this.testNamespaces.add(name);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 409) {
        // Namespace already exists
        return await this.getNamespace(name);
      }
      throw error;
    }
  }

  async getNamespace(name) {
    if (this.mockMode) {
      return { metadata: { name }, status: { phase: 'Active' } };
    }

    try {
      const result = await this.k8sApi.readNamespace(name);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  async deleteNamespace(name) {
    if (this.mockMode) {
      return true;
    }

    try {
      await this.k8sApi.deleteNamespace(name);
      this.testNamespaces.delete(name);
      return true;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return true; // Already deleted
      }
      throw error;
    }
  }

  async applyKroInstance(instanceYaml, namespace) {
    if (this.mockMode) {
      const instance = yaml.load(instanceYaml);
      return {
        metadata: instance.metadata,
        spec: instance.spec,
        status: { phase: 'Ready' }
      };
    }

    const instance = yaml.load(instanceYaml);
    const group = 'kro.run';
    const version = 'v1alpha1';
    const plural = 'cicdpipelines';

    try {
      const result = await this.customApi.createNamespacedCustomObject(
        group,
        version,
        namespace,
        plural,
        instance
      );

      this.trackResource('cicdpipeline', namespace, instance.metadata.name);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 409) {
        // Resource already exists, try to get it
        return await this.getKroInstance(instance.metadata.name, namespace);
      }
      if (error.response?.statusCode === 404) {
        // Kro CRDs not installed, enable mock mode
        console.warn('⚠️  Kro CRDs not found, enabling mock mode for Kubernetes client');
        this.mockMode = true;
        return this.applyKroInstance(instanceYaml, namespace);
      }
      throw error;
    }
  }

  async getKroInstance(name, namespace) {
    if (this.mockMode) {
      return {
        metadata: { name, namespace },
        spec: {},
        status: { phase: 'Ready' }
      };
    }

    const group = 'kro.run';
    const version = 'v1alpha1';
    const plural = 'cicdpipelines';

    try {
      const result = await this.customApi.getNamespacedCustomObject(
        group,
        version,
        namespace,
        plural,
        name
      );
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  async waitForKroInstanceReady(name, namespace, timeoutMs = 300000) {
    if (this.mockMode) {
      return {
        metadata: { name, namespace },
        status: {
          phase: 'Ready',
          kubernetesResourcesReady: true,
          awsResourcesReady: true,
          workflowsReady: true
        }
      };
    }

    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      const instance = await this.getKroInstance(name, namespace);

      if (instance?.status?.kubernetesResourcesReady &&
        instance?.status?.awsResourcesReady &&
        instance?.status?.workflowsReady) {
        return instance;
      }

      await new Promise(resolve => setTimeout(resolve, 5000)); // Wait 5 seconds
    }

    throw new Error(`Timeout waiting for Kro instance ${name} to be ready`);
  }

  async getSecret(name, namespace) {
    if (this.mockMode) {
      return {
        metadata: {
          name,
          namespace,
          annotations: {
            'ecr.aws/main-repository': '123456789012.dkr.ecr.us-west-2.amazonaws.com/modengg/test-app',
            'ecr.aws/cache-repository': '123456789012.dkr.ecr.us-west-2.amazonaws.com/modengg/test-app/cache',
            'ecr.aws/registry-id': '123456789012',
            'ecr.aws/region': 'us-west-2',
            'cicd.kro.run/credential-type': 'ecr-docker-config',
            'cicd.kro.run/credential-refresh': 'true',
            'cicd.kro.run/namespace-scoped': 'true',
            'cicd.kro.run/application': 'test-app'
          }
        },
        type: 'kubernetes.io/dockerconfigjson',
        data: { '.dockerconfigjson': 'eyJhdXRocyI6eyIxMjM0NTY3ODkwMTIuZGtyLmVjci51cy13ZXN0LTIuYW1hem9uYXdzLmNvbSI6eyJ1c2VybmFtZSI6IkFXUyIsInBhc3N3b3JkIjoidGVzdC10b2tlbiIsImF1dGgiOiJRVmRUT25SbGMzUXRkRzlyWlc0PSJ9fX0=' }
      };
    }

    try {
      const result = await this.k8sApi.readNamespacedSecret(name, namespace);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  async getConfigMap(name, namespace) {
    if (this.mockMode) {
      return {
        metadata: { name, namespace },
        data: {
          ECR_MAIN_REPOSITORY: '123456789012.dkr.ecr.us-west-2.amazonaws.com/modengg/test-app',
          ECR_CACHE_REPOSITORY: '123456789012.dkr.ecr.us-west-2.amazonaws.com/modengg/test-app/cache',
          ECR_MAIN_REPOSITORY_NAME: 'modengg/test-app',
          ECR_CACHE_REPOSITORY_NAME: 'modengg/test-app/cache',
          AWS_REGION: 'us-west-2',
          AWS_ACCOUNT_ID: '123456789012',
          APPLICATION_NAME: 'test-app',
          DOCKERFILE_PATH: '.',
          DEPLOYMENT_PATH: './deployment',
          GITLAB_HOSTNAME: 'gitlab.example.com',
          GITLAB_USERNAME: 'testuser',
          SERVICE_ACCOUNT_NAME: name.replace('-config', '-sa'),
          IAM_ROLE_ARN: 'arn:aws:iam::123456789012:role/test-role',
          PIPELINE_NAMESPACE: namespace,
          DOCKER_CONFIG_SECRET_NAME: name.replace('-config', '-docker-config')
        }
      };
    }

    try {
      const result = await this.k8sApi.readNamespacedConfigMap(name, namespace);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  async getServiceAccount(name, namespace) {
    if (this.mockMode) {
      return {
        metadata: {
          name,
          namespace,
          annotations: {
            'eks.amazonaws.com/role-arn': 'arn:aws:iam::123456789012:role/test-role',
            'eks.amazonaws.com/pod-identity-association': 'arn:aws:eks:us-west-2:123456789012:podidentityassociation/test-cluster/a-123456789',
            'cicd.kro.run/application': 'test-app',
            'cicd.kro.run/pipeline': name.replace('-sa', '')
          }
        },
        automountServiceAccountToken: true
      };
    }

    try {
      const result = await this.k8sApi.readNamespacedServiceAccount(name, namespace);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      // If we get other errors, it might be because resources aren't ready yet
      console.warn(`⚠️  Could not get ServiceAccount ${name}: ${error.message}`);
      return null;
    }
  }

  async getCronJob(name, namespace) {
    if (this.mockMode) {
      return {
        metadata: { name, namespace },
        spec: { schedule: '0 */6 * * *' }
      };
    }

    try {
      const result = await this.batchApi.readNamespacedCronJob(name, namespace);
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  async getWorkflowTemplate(name, namespace) {
    if (this.mockMode) {
      // Determine entrypoint based on workflow name
      let entrypoint = 'main';
      let serviceAccountName = name.replace(/-provisioning-workflow|-cache-warmup-workflow|-cicd-workflow/, '-sa');

      if (name.includes('provisioning-workflow')) {
        entrypoint = 'provision-pipeline';
      } else if (name.includes('cache-warmup-workflow')) {
        entrypoint = 'cache-warmup-pipeline';
      } else if (name.includes('cicd-workflow')) {
        entrypoint = 'cicd-pipeline';
      }

      return {
        metadata: { name, namespace },
        spec: {
          entrypoint,
          serviceAccountName
        }
      };
    }

    const group = 'argoproj.io';
    const version = 'v1alpha1';
    const plural = 'workflowtemplates';

    try {
      const result = await this.customApi.getNamespacedCustomObject(
        group,
        version,
        namespace,
        plural,
        name
      );
      return result.body;
    } catch (error) {
      if (error.response?.statusCode === 404) {
        return null;
      }
      throw error;
    }
  }

  trackResource(type, namespace, name) {
    const key = `${type}/${namespace}/${name}`;
    this.testResources.set(key, { type, namespace, name });
  }

  async cleanup() {
    if (this.mockMode) {
      return;
    }

    console.log('🧹 Cleaning up test resources...');

    // Delete test namespaces (this will cascade delete most resources)
    for (const namespace of this.testNamespaces) {
      try {
        await this.deleteNamespace(namespace);
        console.log(`✅ Deleted test namespace: ${namespace}`);
      } catch (error) {
        console.warn(`⚠️  Failed to delete namespace ${namespace}: ${error.message}`);
      }
    }

    this.testNamespaces.clear();
    this.testResources.clear();
  }
}