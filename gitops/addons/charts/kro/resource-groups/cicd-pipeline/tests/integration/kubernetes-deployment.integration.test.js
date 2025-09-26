import { describe, it, expect, beforeAll, afterAll } from 'vitest';

describe('Kubernetes Deployment Integration Tests', () => {
  let kubernetesClient;
  let awsClient;
  let testNamespace;
  let testInstanceName;

  beforeAll(async () => {
    kubernetesClient = globalThis.kubernetesClient;
    awsClient = globalThis.awsClient;

    const timestamp = Date.now();
    testNamespace = `test-k8s-${timestamp}`;
    testInstanceName = `test-k8s-pipeline-${timestamp}`;
  });

  afterAll(async () => {
    if (kubernetesClient && testNamespace) {
      try {
        await kubernetesClient.deleteNamespace(testNamespace);
      } catch (error) {
        console.warn(`Failed to cleanup test namespace: ${error.message}`);
      }
    }
  });

  describe('Kubernetes Resource Deployment', () => {
    it('should deploy complete Kubernetes resource stack', async () => {
      // Create test namespace
      await kubernetesClient.createTestNamespace(testNamespace);

      // Apply Kro instance
      const instanceYaml = `
apiVersion: kro.run/v1alpha1
kind: CICDPipeline
metadata:
  name: ${testInstanceName}
  namespace: ${testNamespace}
spec:
  name: ${testInstanceName}
  namespace: ${testNamespace}
  aws:
    region: us-west-2
    clusterName: test-cluster
  application:
    name: test-k8s-app
    dockerfilePath: "."
    deploymentPath: "./deployment"
  ecr:
    repositoryPrefix: "modengg"
  gitlab:
    hostname: "gitlab.example.com"
    username: "testuser"
`;

      const instance = await kubernetesClient.applyKroInstance(instanceYaml, testNamespace);
      expect(instance).toBeDefined();

      // Wait for all resources to be ready
      await kubernetesClient.waitForKroInstanceReady(testInstanceName, testNamespace, 300000);
    }, 300000);

    it('should validate namespace configuration and labels', async () => {
      const namespace = await kubernetesClient.getNamespace(testNamespace);

      expect(namespace).toBeDefined();
      expect(namespace.status.phase).toBe('Active');
      expect(namespace.metadata.labels).toHaveProperty('test.kro.run/integration-test', 'true');
    });

    it('should validate service account deployment and configuration', async () => {
      const serviceAccount = await kubernetesClient.getServiceAccount(
        `${testInstanceName}-sa`,
        testNamespace
      );

      expect(serviceAccount).toBeDefined();
      expect(serviceAccount.metadata.name).toBe(`${testInstanceName}-sa`);
      expect(serviceAccount.metadata.namespace).toBe(testNamespace);
      expect(serviceAccount.automountServiceAccountToken).toBe(true);

      // Validate labels
      expect(serviceAccount.metadata.labels).toHaveProperty('app.kubernetes.io/name', 'test-k8s-app');
      expect(serviceAccount.metadata.labels).toHaveProperty('app.kubernetes.io/component', 'cicd-pipeline');
      expect(serviceAccount.metadata.labels).toHaveProperty('app.kubernetes.io/managed-by', 'kro');

      // Validate annotations
      expect(serviceAccount.metadata.annotations).toHaveProperty('eks.amazonaws.com/role-arn');
      expect(serviceAccount.metadata.annotations).toHaveProperty('eks.amazonaws.com/pod-identity-association');
      expect(serviceAccount.metadata.annotations).toHaveProperty('cicd.kro.run/application', 'test-k8s-app');
      expect(serviceAccount.metadata.annotations).toHaveProperty('cicd.kro.run/pipeline', testInstanceName);
    });

    it('should validate RBAC role and role binding deployment', async () => {
      // Check Role
      const role = await kubernetesClient.k8sApi?.readNamespacedRole(`${testInstanceName}-role`, testNamespace);
      if (!kubernetesClient.mockMode) {
        expect(role.body).toBeDefined();
        expect(role.body.metadata.name).toBe(`${testInstanceName}-role`);
        expect(role.body.rules).toBeDefined();
        expect(role.body.rules.length).toBeGreaterThan(0);

        // Validate specific permissions
        const secretsRule = role.body.rules.find(rule =>
          rule.resources.includes('secrets') && rule.verbs.includes('get')
        );
        expect(secretsRule).toBeDefined();
      }

      // Check RoleBinding
      const roleBinding = await kubernetesClient.rbacApi?.readNamespacedRoleBinding(`${testInstanceName}-rolebinding`, testNamespace);
      if (!kubernetesClient.mockMode) {
        expect(roleBinding.body).toBeDefined();
        expect(roleBinding.body.metadata.name).toBe(`${testInstanceName}-rolebinding`);
        expect(roleBinding.body.subjects[0].name).toBe(`${testInstanceName}-sa`);
        expect(roleBinding.body.roleRef.name).toBe(`${testInstanceName}-role`);
      }
    });

    it('should validate ConfigMap deployment and data structure', async () => {
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );

      expect(configMap).toBeDefined();
      expect(configMap.metadata.name).toBe(`${testInstanceName}-config`);
      expect(configMap.metadata.namespace).toBe(testNamespace);

      // Validate required data fields
      const requiredFields = [
        'ECR_MAIN_REPOSITORY',
        'ECR_CACHE_REPOSITORY',
        'ECR_MAIN_REPOSITORY_NAME',
        'ECR_CACHE_REPOSITORY_NAME',
        'AWS_REGION',
        'AWS_ACCOUNT_ID',
        'APPLICATION_NAME',
        'DOCKERFILE_PATH',
        'DEPLOYMENT_PATH',
        'GITLAB_HOSTNAME',
        'GITLAB_USERNAME',
        'SERVICE_ACCOUNT_NAME',
        'IAM_ROLE_ARN',
        'PIPELINE_NAMESPACE',
        'DOCKER_CONFIG_SECRET_NAME'
      ];

      for (const field of requiredFields) {
        expect(configMap.data).toHaveProperty(field);
        expect(configMap.data[field]).toBeDefined();
        expect(configMap.data[field].length).toBeGreaterThan(0);
      }

      // Validate specific values
      expect(configMap.data.APPLICATION_NAME).toBe('test-k8s-app');
      expect(configMap.data.AWS_REGION).toBe('us-west-2');
      expect(configMap.data.DOCKERFILE_PATH).toBe('.');
      expect(configMap.data.DEPLOYMENT_PATH).toBe('./deployment');
      expect(configMap.data.GITLAB_HOSTNAME).toBe('gitlab.example.com');
      expect(configMap.data.GITLAB_USERNAME).toBe('testuser');
      expect(configMap.data.SERVICE_ACCOUNT_NAME).toBe(`${testInstanceName}-sa`);
      expect(configMap.data.PIPELINE_NAMESPACE).toBe(testNamespace);
      expect(configMap.data.DOCKER_CONFIG_SECRET_NAME).toBe(`${testInstanceName}-docker-config`);
    });

    it('should validate Docker registry secret deployment and structure', async () => {
      const dockerSecret = await kubernetesClient.getSecret(
        `${testInstanceName}-docker-config`,
        testNamespace
      );

      expect(dockerSecret).toBeDefined();
      expect(dockerSecret.metadata.name).toBe(`${testInstanceName}-docker-config`);
      expect(dockerSecret.metadata.namespace).toBe(testNamespace);
      expect(dockerSecret.type).toBe('kubernetes.io/dockerconfigjson');

      // Validate annotations
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/main-repository');
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/cache-repository');
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/registry-id');
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/region', 'us-west-2');
      expect(dockerSecret.metadata.annotations).toHaveProperty('cicd.kro.run/credential-type', 'ecr-docker-config');
      expect(dockerSecret.metadata.annotations).toHaveProperty('cicd.kro.run/credential-refresh', 'true');
      expect(dockerSecret.metadata.annotations).toHaveProperty('cicd.kro.run/namespace-scoped', 'true');
      expect(dockerSecret.metadata.annotations).toHaveProperty('cicd.kro.run/application', 'test-k8s-app');

      // Validate data structure
      expect(dockerSecret.data).toHaveProperty('.dockerconfigjson');

      // Decode and validate Docker config JSON
      const dockerConfigJson = Buffer.from(dockerSecret.data['.dockerconfigjson'], 'base64').toString();
      const dockerConfig = JSON.parse(dockerConfigJson);
      expect(dockerConfig).toHaveProperty('auths');
    });

    it('should validate CronJob deployment for ECR credential refresh', async () => {
      const cronJob = await kubernetesClient.getCronJob(
        `${testInstanceName}-ecr-refresh`,
        testNamespace
      );

      expect(cronJob).toBeDefined();
      expect(cronJob.metadata.name).toBe(`${testInstanceName}-ecr-refresh`);
      expect(cronJob.metadata.namespace).toBe(testNamespace);
      expect(cronJob.spec.schedule).toBe('0 */6 * * *');
      expect(cronJob.spec.concurrencyPolicy).toBe('Replace');
      expect(cronJob.spec.successfulJobsHistoryLimit).toBe(3);
      expect(cronJob.spec.failedJobsHistoryLimit).toBe(1);

      // Validate job template
      const jobTemplate = cronJob.spec.jobTemplate;
      expect(jobTemplate.spec.template.spec.serviceAccountName).toBe(`${testInstanceName}-sa`);
      expect(jobTemplate.spec.template.spec.restartPolicy).toBe('OnFailure');

      // Validate container configuration
      const container = jobTemplate.spec.template.spec.containers[0];
      expect(container.name).toBe('ecr-credential-refresh');
      expect(container.image).toBe('amazon/aws-cli:latest');
      expect(container.env.some(env => env.name === 'AWS_REGION' && env.value === 'us-west-2')).toBe(true);
    });
  });

  describe('Workflow Template Deployment', () => {
    it('should validate provisioning workflow template deployment', async () => {
      const workflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-provisioning-workflow`,
        testNamespace
      );

      expect(workflow).toBeDefined();
      expect(workflow.metadata.name).toBe(`${testInstanceName}-provisioning-workflow`);
      expect(workflow.metadata.namespace).toBe(testNamespace);
      expect(workflow.spec.serviceAccountName).toBe(`${testInstanceName}-sa`);
      expect(workflow.spec.entrypoint).toBe('provision-pipeline');

      // Validate labels
      expect(workflow.metadata.labels).toHaveProperty('app.kubernetes.io/name', 'test-k8s-app');
      expect(workflow.metadata.labels).toHaveProperty('app.kubernetes.io/component', 'cicd-pipeline');
      expect(workflow.metadata.labels).toHaveProperty('workflow.kro.run/type', 'provisioning');

      // Validate arguments
      expect(workflow.spec.arguments.parameters).toBeDefined();
      const appNameParam = workflow.spec.arguments.parameters.find(p => p.name === 'application-name');
      const regionParam = workflow.spec.arguments.parameters.find(p => p.name === 'aws-region');
      expect(appNameParam.value).toBe('test-k8s-app');
      expect(regionParam.value).toBe('us-west-2');
    });

    it('should validate cache warmup workflow template deployment', async () => {
      const workflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-cache-warmup-workflow`,
        testNamespace
      );

      expect(workflow).toBeDefined();
      expect(workflow.metadata.name).toBe(`${testInstanceName}-cache-warmup-workflow`);
      expect(workflow.metadata.namespace).toBe(testNamespace);
      expect(workflow.spec.serviceAccountName).toBe(`${testInstanceName}-sa`);
      expect(workflow.spec.entrypoint).toBe('cache-warmup-pipeline');

      // Validate labels
      expect(workflow.metadata.labels).toHaveProperty('workflow.kro.run/type', 'cache-warmup');

      // Validate arguments
      const baseImagesParam = workflow.spec.arguments.parameters.find(p => p.name === 'base-images');
      const cacheTtlParam = workflow.spec.arguments.parameters.find(p => p.name === 'cache-ttl');
      expect(baseImagesParam.value).toBe('node:18-alpine,python:3.11-slim,openjdk:17-jre-slim');
      expect(cacheTtlParam.value).toBe('168h');
    });

    it('should validate CI/CD workflow template deployment', async () => {
      const workflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-cicd-workflow`,
        testNamespace
      );

      expect(workflow).toBeDefined();
      expect(workflow.metadata.name).toBe(`${testInstanceName}-cicd-workflow`);
      expect(workflow.metadata.namespace).toBe(testNamespace);
      expect(workflow.spec.serviceAccountName).toBe(`${testInstanceName}-sa`);
      expect(workflow.spec.entrypoint).toBe('cicd-pipeline');

      // Validate labels
      expect(workflow.metadata.labels).toHaveProperty('workflow.kro.run/type', 'cicd');

      // Validate required parameters
      const requiredParams = ['git-url', 'git-revision', 'git-username', 'git-token', 'repo-name', 'image-tag', 'dockerfile-path', 'deployment-path'];
      for (const paramName of requiredParams) {
        const param = workflow.spec.arguments.parameters.find(p => p.name === paramName);
        expect(param).toBeDefined();
      }

      // Validate default values
      const dockerfilePathParam = workflow.spec.arguments.parameters.find(p => p.name === 'dockerfile-path');
      const deploymentPathParam = workflow.spec.arguments.parameters.find(p => p.name === 'deployment-path');
      expect(dockerfilePathParam.value).toBe('.');
      expect(deploymentPathParam.value).toBe('./deployment');
    });
  });

  describe('Resource Interdependencies', () => {
    it('should validate proper resource reference chains', async () => {
      // Get the Kro instance to check status
      const instance = await kubernetesClient.getKroInstance(testInstanceName, testNamespace);

      expect(instance.status.kubernetesResourcesReady).toBe(true);
      expect(instance.status.awsResourcesReady).toBe(true);
      expect(instance.status.workflowsReady).toBe(true);

      // Validate ConfigMap references AWS resources
      const configMap = await kubernetesClient.getConfigMap(`${testInstanceName}-config`, testNamespace);
      expect(configMap.data.ECR_MAIN_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\//);
      expect(configMap.data.IAM_ROLE_ARN).toMatch(/^arn:aws:iam::\d{12}:role\//);

      // Validate Service Account references IAM role
      const serviceAccount = await kubernetesClient.getServiceAccount(`${testInstanceName}-sa`, testNamespace);
      expect(serviceAccount.metadata.annotations['eks.amazonaws.com/role-arn']).toMatch(/^arn:aws:iam::\d{12}:role\//);

      // Validate workflows reference service account
      const workflows = [
        `${testInstanceName}-provisioning-workflow`,
        `${testInstanceName}-cache-warmup-workflow`,
        `${testInstanceName}-cicd-workflow`
      ];

      for (const workflowName of workflows) {
        const workflow = await kubernetesClient.getWorkflowTemplate(workflowName, testNamespace);
        expect(workflow.spec.serviceAccountName).toBe(`${testInstanceName}-sa`);
      }
    });

    it('should validate namespace scoping of all resources', async () => {
      const resources = [
        { type: 'serviceaccount', name: `${testInstanceName}-sa` },
        { type: 'configmap', name: `${testInstanceName}-config` },
        { type: 'secret', name: `${testInstanceName}-docker-config` },
        { type: 'cronjob', name: `${testInstanceName}-ecr-refresh` }
      ];

      for (const resource of resources) {
        let k8sResource;
        switch (resource.type) {
          case 'serviceaccount':
            k8sResource = await kubernetesClient.getServiceAccount(resource.name, testNamespace);
            break;
          case 'configmap':
            k8sResource = await kubernetesClient.getConfigMap(resource.name, testNamespace);
            break;
          case 'secret':
            k8sResource = await kubernetesClient.getSecret(resource.name, testNamespace);
            break;
          case 'cronjob':
            k8sResource = await kubernetesClient.getCronJob(resource.name, testNamespace);
            break;
        }

        expect(k8sResource).toBeDefined();
        expect(k8sResource.metadata.namespace).toBe(testNamespace);
      }
    });

    it('should validate resource cleanup readiness', async () => {
      // This test ensures that resources are properly configured for cleanup
      // by validating that they have proper labels and annotations

      const serviceAccount = await kubernetesClient.getServiceAccount(`${testInstanceName}-sa`, testNamespace);
      const configMap = await kubernetesClient.getConfigMap(`${testInstanceName}-config`, testNamespace);
      const dockerSecret = await kubernetesClient.getSecret(`${testInstanceName}-docker-config`, testNamespace);

      // All resources should have proper labels for identification
      const expectedLabels = {
        'app.kubernetes.io/name': 'test-k8s-app',
        'app.kubernetes.io/component': 'cicd-pipeline',
        'app.kubernetes.io/managed-by': 'kro'
      };

      for (const [key, value] of Object.entries(expectedLabels)) {
        expect(serviceAccount.metadata.labels).toHaveProperty(key, value);
        expect(configMap.metadata.labels).toHaveProperty(key, value);
        expect(dockerSecret.metadata.labels).toHaveProperty(key, value);
      }
    });
  });
});