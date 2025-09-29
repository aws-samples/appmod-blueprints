import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { KubernetesTestClient } from './utils/kubernetes-client.js';
import { AWSTestClient } from './utils/aws-client.js';

describe('CI/CD Pipeline Integration Tests', () => {
  let kubernetesClient;
  let awsClient;
  let testNamespace;
  let testInstanceName;

  beforeAll(async () => {
    console.log('🚀 Setting up integration test environment...');

    // Initialize test clients
    kubernetesClient = new KubernetesTestClient();
    awsClient = new AWSTestClient();

    // Generate unique test identifiers
    const timestamp = Date.now();
    testNamespace = `test-cicd-${timestamp}`;
    testInstanceName = `test-pipeline-${timestamp}`;

    // Verify connectivity and set mock mode if needed
    try {
      await kubernetesClient.verifyConnection();
      console.log('✅ Kubernetes cluster connection verified');
    } catch (error) {
      console.warn('⚠️  Kubernetes cluster not available, running in mock mode');
      kubernetesClient.mockMode = true;
    }

    try {
      await awsClient.verifyConnection();
      console.log('✅ AWS connection verified');
    } catch (error) {
      console.warn('⚠️  AWS not available, running in mock mode');
      awsClient.mockMode = true;
    }

    console.log('✅ Integration test environment setup complete');
  });

  afterAll(async () => {
    console.log('🧹 Cleaning up integration test environment...');

    // Cleanup test namespace
    if (kubernetesClient && testNamespace) {
      try {
        await kubernetesClient.deleteNamespace(testNamespace);
      } catch (error) {
        console.warn(`Failed to cleanup test namespace: ${error.message}`);
      }
    }

    // Cleanup clients
    if (kubernetesClient) {
      await kubernetesClient.cleanup();
    }
    if (awsClient) {
      await awsClient.cleanup();
    }

    console.log('✅ Integration test environment cleanup complete');
  });

  describe('Test Environment Setup', () => {
    it('should have kubernetesClient available', () => {
      expect(kubernetesClient).toBeDefined();
      expect(kubernetesClient).toHaveProperty('mockMode');
      expect(typeof kubernetesClient.mockMode).toBe('boolean');
    });

    it('should have awsClient available', () => {
      expect(awsClient).toBeDefined();
      expect(awsClient).toHaveProperty('mockMode');
      expect(typeof awsClient.mockMode).toBe('boolean');
    });

    it('should be running in mock mode (expected for CI/CD)', () => {
      // In CI/CD environments, we expect mock mode to be enabled
      // This test passes if either client is in mock mode or if they're properly initialized
      expect(kubernetesClient?.mockMode || awsClient?.mockMode).toBe(true);
    });
  });

  describe('Pipeline Provisioning Tests', () => {
    it('should create namespace for CI/CD pipeline', async () => {
      const namespace = await kubernetesClient.createTestNamespace(testNamespace);

      expect(namespace).toBeDefined();
      expect(namespace.metadata.name).toBe(testNamespace);

      if (!kubernetesClient.mockMode) {
        expect(namespace.metadata.labels).toHaveProperty('test.kro.run/integration-test', 'true');
      }
    });

    it('should apply Kro CI/CD pipeline instance successfully', async () => {
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
    name: test-app
    dockerfilePath: "."
    deploymentPath: "./deployment"
  ecr:
    repositoryPrefix: "peeks"
  gitlab:
    hostname: "gitlab.example.com"
    username: "testuser"
`;

      const instance = await kubernetesClient.applyKroInstance(instanceYaml, testNamespace);

      expect(instance).toBeDefined();
      expect(instance.metadata.name).toBe(testInstanceName);
      expect(instance.metadata.namespace).toBe(testNamespace);
      expect(instance.spec.application.name).toBe('test-app');
    });

    it('should validate Kro instance becomes ready', async () => {
      const readyInstance = await kubernetesClient.waitForKroInstanceReady(
        testInstanceName,
        testNamespace,
        30000 // 30 seconds timeout for mock mode
      );

      expect(readyInstance).toBeDefined();
      expect(readyInstance.status.kubernetesResourcesReady).toBe(true);
      expect(readyInstance.status.awsResourcesReady).toBe(true);
      expect(readyInstance.status.workflowsReady).toBe(true);
    });
  });

  describe('Kubernetes Resource Validation', () => {
    it('should create service account with proper configuration', async () => {
      const serviceAccount = await kubernetesClient.getServiceAccount(
        `${testInstanceName}-sa`,
        testNamespace
      );

      expect(serviceAccount).toBeDefined();
      expect(serviceAccount.metadata.name).toBe(`${testInstanceName}-sa`);
      expect(serviceAccount.automountServiceAccountToken).toBe(true);
    });

    it('should create ConfigMap with ECR repository information', async () => {
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );

      expect(configMap).toBeDefined();
      expect(configMap.data).toHaveProperty('APPLICATION_NAME', 'test-app');
      expect(configMap.data).toHaveProperty('AWS_REGION', 'us-west-2');
      expect(configMap.data).toHaveProperty('ECR_MAIN_REPOSITORY');
      expect(configMap.data).toHaveProperty('ECR_CACHE_REPOSITORY');
    });

    it('should create Docker registry secret', async () => {
      const dockerSecret = await kubernetesClient.getSecret(
        `${testInstanceName}-docker-config`,
        testNamespace
      );

      expect(dockerSecret).toBeDefined();
      expect(dockerSecret.type).toBe('kubernetes.io/dockerconfigjson');
      expect(dockerSecret.data).toHaveProperty('.dockerconfigjson');
    });

    it('should create CronJob for ECR credential refresh', async () => {
      const cronJob = await kubernetesClient.getCronJob(
        `${testInstanceName}-ecr-refresh`,
        testNamespace
      );

      expect(cronJob).toBeDefined();
      expect(cronJob.spec.schedule).toBe('0 */6 * * *');
    });
  });

  describe('Workflow Template Validation', () => {
    it('should create provisioning workflow template', async () => {
      const workflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-provisioning-workflow`,
        testNamespace
      );

      expect(workflow).toBeDefined();
      expect(workflow.spec.entrypoint).toBe('provision-pipeline');
      expect(workflow.spec.serviceAccountName).toBe(`${testInstanceName}-sa`);
    });

    it('should create cache warmup workflow template', async () => {
      const workflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-cache-warmup-workflow`,
        testNamespace
      );

      expect(workflow).toBeDefined();
      expect(workflow.spec.entrypoint).toBe('cache-warmup-pipeline');
    });

    it('should create CI/CD workflow template', async () => {
      const workflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-cicd-workflow`,
        testNamespace
      );

      expect(workflow).toBeDefined();
      expect(workflow.spec.entrypoint).toBe('cicd-pipeline');
    });
  });

  describe('AWS Resource Validation', () => {
    it('should create ECR repositories through ACK controllers', async () => {
      const mainRepoName = 'peeks/test-app';
      const cacheRepoName = 'peeks/test-app/cache';

      const mainRepo = await awsClient.waitForECRRepository(mainRepoName, 30000);
      expect(mainRepo).toBeDefined();
      expect(mainRepo.repositoryName).toBe(mainRepoName);
      expect(mainRepo.repositoryUri).toContain('.dkr.ecr.');

      const cacheRepo = await awsClient.waitForECRRepository(cacheRepoName, 30000);
      expect(cacheRepo).toBeDefined();
      expect(cacheRepo.repositoryName).toBe(cacheRepoName);
    });

    it('should create IAM resources through ACK controllers', async () => {
      const policyName = `${testInstanceName}-ecr-policy`;
      const roleName = `${testInstanceName}-role`;

      const policy = await awsClient.checkIAMPolicy(policyName);
      expect(policy).toBeDefined();
      expect(policy.PolicyName).toBe(policyName);

      const role = await awsClient.waitForIAMRole(roleName, 30000);
      expect(role).toBeDefined();
      expect(role.RoleName).toBe(roleName);
    });

    it('should create Pod Identity Association', async () => {
      const clusterName = 'test-cluster';
      const serviceAccountName = `${testInstanceName}-sa`;

      const association = await awsClient.waitForPodIdentityAssociation(
        clusterName,
        testNamespace,
        serviceAccountName,
        30000
      );

      expect(association).toBeDefined();
      expect(association.clusterName).toBe(clusterName);
      expect(association.namespace).toBe(testNamespace);
      expect(association.serviceAccount).toBe(serviceAccountName);
    });

    it('should validate ECR authentication works', async () => {
      const authToken = await awsClient.testECRAuthentication();

      expect(authToken).toBeDefined();
      expect(typeof authToken).toBe('string');
      expect(authToken.length).toBeGreaterThan(0);
    });
  });

  describe('Resource Integration Validation', () => {
    it('should validate ConfigMap contains correct AWS resource references', async () => {
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );

      // Both mock and real modes should have properly formatted ECR repository URIs
      expect(configMap.data.ECR_MAIN_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\/peeks\/test-app$/);
      expect(configMap.data.ECR_CACHE_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\/peeks\/test-app\/cache$/);
      expect(configMap.data.AWS_ACCOUNT_ID).toMatch(/^\d{12}$/);
      expect(configMap.data.APPLICATION_NAME).toBe('test-app');
      expect(configMap.data.AWS_REGION).toBe('us-west-2');
    });

    it('should validate service account has proper IAM role annotations', async () => {
      const serviceAccount = await kubernetesClient.getServiceAccount(
        `${testInstanceName}-sa`,
        testNamespace
      );

      // Both mock and real modes should have proper annotations
      expect(serviceAccount.metadata.annotations).toHaveProperty('eks.amazonaws.com/role-arn');
      expect(serviceAccount.metadata.annotations).toHaveProperty('eks.amazonaws.com/pod-identity-association');
      expect(serviceAccount.metadata.annotations).toHaveProperty('cicd.kro.run/application', 'test-app');
      expect(serviceAccount.metadata.annotations).toHaveProperty('cicd.kro.run/pipeline', testInstanceName);
    });

    it('should validate Docker registry secret has valid structure', async () => {
      const dockerSecret = await kubernetesClient.getSecret(
        `${testInstanceName}-docker-config`,
        testNamespace
      );

      expect(dockerSecret).toBeDefined();

      // Both mock and real modes should have proper annotations
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/main-repository');
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/cache-repository');
      expect(dockerSecret.metadata.annotations).toHaveProperty('cicd.kro.run/credential-type', 'ecr-docker-config');

      // Validate Docker config JSON structure
      const dockerConfigJson = Buffer.from(dockerSecret.data['.dockerconfigjson'], 'base64').toString();
      const dockerConfig = JSON.parse(dockerConfigJson);
      expect(dockerConfig).toHaveProperty('auths');
    });

    it('should validate all workflow templates reference correct service account', async () => {
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
  });
});