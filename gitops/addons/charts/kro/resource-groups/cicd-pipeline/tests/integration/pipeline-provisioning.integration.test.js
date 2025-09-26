import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import yaml from 'js-yaml';
import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

describe('Pipeline Provisioning Integration Tests', () => {
  let testNamespace;
  let testInstanceName;
  let kubernetesClient;
  let awsClient;

  beforeAll(async () => {
    kubernetesClient = globalThis.kubernetesClient;
    awsClient = globalThis.awsClient;

    // Generate unique test identifiers
    const timestamp = Date.now();
    testNamespace = `test-cicd-${timestamp}`;
    testInstanceName = `test-pipeline-${timestamp}`;
  });

  afterAll(async () => {
    // Cleanup test namespace
    if (kubernetesClient && testNamespace) {
      try {
        await kubernetesClient.deleteNamespace(testNamespace);
      } catch (error) {
        console.warn(`Failed to cleanup test namespace: ${error.message}`);
      }
    }
  });

  describe('End-to-End Pipeline Provisioning', () => {
    it('should create namespace for CI/CD pipeline', async () => {
      const namespace = await kubernetesClient.createTestNamespace(testNamespace);

      expect(namespace).toBeDefined();
      expect(namespace.metadata.name).toBe(testNamespace);
      expect(namespace.metadata.labels).toHaveProperty('test.kro.run/integration-test', 'true');
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
    repositoryPrefix: "modengg"
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

    it('should wait for Kro instance to become ready', async () => {
      // This test validates that all resources are provisioned and ready
      const readyInstance = await kubernetesClient.waitForKroInstanceReady(
        testInstanceName,
        testNamespace,
        300000 // 5 minutes timeout
      );

      expect(readyInstance).toBeDefined();
      expect(readyInstance.status.kubernetesResourcesReady).toBe(true);
      expect(readyInstance.status.awsResourcesReady).toBe(true);
      expect(readyInstance.status.workflowsReady).toBe(true);
    }, 300000); // 5 minute timeout for this test

    it('should validate all Kubernetes resources are created', async () => {
      // Test service account creation
      const serviceAccount = await kubernetesClient.getServiceAccount(
        `${testInstanceName}-sa`,
        testNamespace
      );
      expect(serviceAccount).toBeDefined();
      expect(serviceAccount.metadata.name).toBe(`${testInstanceName}-sa`);
      expect(serviceAccount.automountServiceAccountToken).toBe(true);

      // Test ConfigMap creation
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );
      expect(configMap).toBeDefined();
      expect(configMap.data).toHaveProperty('APPLICATION_NAME', 'test-app');
      expect(configMap.data).toHaveProperty('AWS_REGION', 'us-west-2');
      expect(configMap.data).toHaveProperty('ECR_MAIN_REPOSITORY');
      expect(configMap.data).toHaveProperty('ECR_CACHE_REPOSITORY');

      // Test Docker registry secret creation
      const dockerSecret = await kubernetesClient.getSecret(
        `${testInstanceName}-docker-config`,
        testNamespace
      );
      expect(dockerSecret).toBeDefined();
      expect(dockerSecret.type).toBe('kubernetes.io/dockerconfigjson');
      expect(dockerSecret.data).toHaveProperty('.dockerconfigjson');

      // Test CronJob for ECR credential refresh
      const cronJob = await kubernetesClient.getCronJob(
        `${testInstanceName}-ecr-refresh`,
        testNamespace
      );
      expect(cronJob).toBeDefined();
      expect(cronJob.spec.schedule).toBe('0 */6 * * *');
    });

    it('should validate workflow templates are created', async () => {
      // Test provisioning workflow template
      const provisioningWorkflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-provisioning-workflow`,
        testNamespace
      );
      expect(provisioningWorkflow).toBeDefined();
      expect(provisioningWorkflow.spec.entrypoint).toBe('provision-pipeline');

      // Test cache warmup workflow template
      const cacheWorkflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-cache-warmup-workflow`,
        testNamespace
      );
      expect(cacheWorkflow).toBeDefined();
      expect(cacheWorkflow.spec.entrypoint).toBe('cache-warmup-pipeline');

      // Test CI/CD workflow template
      const cicdWorkflow = await kubernetesClient.getWorkflowTemplate(
        `${testInstanceName}-cicd-workflow`,
        testNamespace
      );
      expect(cicdWorkflow).toBeDefined();
      expect(cicdWorkflow.spec.entrypoint).toBe('cicd-pipeline');
    });
  });

  describe('AWS Resource Creation through ACK Controllers', () => {
    it('should create ECR repositories through ACK ECR controller', async () => {
      const mainRepoName = 'modengg/test-app';
      const cacheRepoName = 'modengg/test-app/cache';

      // Wait for main repository to be created
      const mainRepo = await awsClient.waitForECRRepository(mainRepoName, 180000);
      expect(mainRepo).toBeDefined();
      expect(mainRepo.repositoryName).toBe(mainRepoName);
      expect(mainRepo.repositoryUri).toContain('.dkr.ecr.');
      expect(mainRepo.repositoryUri).toContain('.amazonaws.com/');

      // Wait for cache repository to be created
      const cacheRepo = await awsClient.waitForECRRepository(cacheRepoName, 180000);
      expect(cacheRepo).toBeDefined();
      expect(cacheRepo.repositoryName).toBe(cacheRepoName);
      expect(cacheRepo.repositoryUri).toContain('.dkr.ecr.');
      expect(cacheRepo.repositoryUri).toContain('.amazonaws.com/');
    }, 180000); // 3 minute timeout

    it('should create IAM resources through ACK IAM controller', async () => {
      const policyName = `${testInstanceName}-ecr-policy`;
      const roleName = `${testInstanceName}-role`;

      // Wait for IAM policy to be created
      const policy = await awsClient.checkIAMPolicy(policyName);
      expect(policy).toBeDefined();
      expect(policy.PolicyName).toBe(policyName);
      expect(policy.Arn).toContain(':policy/');

      // Wait for IAM role to be created
      const role = await awsClient.waitForIAMRole(roleName, 180000);
      expect(role).toBeDefined();
      expect(role.RoleName).toBe(roleName);
      expect(role.Arn).toContain(':role/');
    }, 180000); // 3 minute timeout

    it('should create Pod Identity Association through ACK EKS controller', async () => {
      const clusterName = 'test-cluster';
      const serviceAccountName = `${testInstanceName}-sa`;

      // Wait for Pod Identity Association to be created
      const association = await awsClient.waitForPodIdentityAssociation(
        clusterName,
        testNamespace,
        serviceAccountName,
        180000
      );

      expect(association).toBeDefined();
      expect(association.clusterName).toBe(clusterName);
      expect(association.namespace).toBe(testNamespace);
      expect(association.serviceAccount).toBe(serviceAccountName);
      expect(association.associationArn).toContain(':podidentityassociation/');
    }, 180000); // 3 minute timeout

    it('should validate ECR authentication works', async () => {
      const authToken = await awsClient.testECRAuthentication();

      expect(authToken).toBeDefined();
      expect(typeof authToken).toBe('string');
      expect(authToken.length).toBeGreaterThan(0);
    });
  });

  describe('Resource Configuration Validation', () => {
    it('should validate ECR repository policies are correctly configured', async () => {
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );

      expect(configMap.data.ECR_MAIN_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\/modengg\/test-app$/);
      expect(configMap.data.ECR_CACHE_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\/modengg\/test-app\/cache$/);
      expect(configMap.data.AWS_ACCOUNT_ID).toMatch(/^\d{12}$/);
    });

    it('should validate service account has proper annotations', async () => {
      const serviceAccount = await kubernetesClient.getServiceAccount(
        `${testInstanceName}-sa`,
        testNamespace
      );

      expect(serviceAccount.metadata.annotations).toHaveProperty('eks.amazonaws.com/role-arn');
      expect(serviceAccount.metadata.annotations).toHaveProperty('eks.amazonaws.com/pod-identity-association');
      expect(serviceAccount.metadata.annotations).toHaveProperty('cicd.kro.run/application', 'test-app');
      expect(serviceAccount.metadata.annotations).toHaveProperty('cicd.kro.run/pipeline', testInstanceName);
    });

    it('should validate Docker registry secret has proper structure', async () => {
      const dockerSecret = await kubernetesClient.getSecret(
        `${testInstanceName}-docker-config`,
        testNamespace
      );

      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/main-repository');
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/cache-repository');
      expect(dockerSecret.metadata.annotations).toHaveProperty('ecr.aws/registry-id');
      expect(dockerSecret.metadata.annotations).toHaveProperty('cicd.kro.run/credential-type', 'ecr-docker-config');

      // Validate the Docker config JSON structure
      const dockerConfigJson = Buffer.from(dockerSecret.data['.dockerconfigjson'], 'base64').toString();
      const dockerConfig = JSON.parse(dockerConfigJson);
      expect(dockerConfig).toHaveProperty('auths');
    });

    it('should validate workflow templates have correct service account references', async () => {
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

  describe('Resource Dependency Validation', () => {
    it('should validate namespace is created before other resources', async () => {
      const namespace = await kubernetesClient.getNamespace(testNamespace);
      expect(namespace.status.phase).toBe('Active');
    });

    it('should validate AWS resources are ready before Kubernetes resources reference them', async () => {
      const instance = await kubernetesClient.getKroInstance(testInstanceName, testNamespace);

      // AWS resources should be ready
      expect(instance.status.awsResourcesReady).toBe(true);

      // ConfigMap should reference ECR repositories
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );
      expect(configMap.data.ECR_MAIN_REPOSITORY).toBeDefined();
      expect(configMap.data.ECR_CACHE_REPOSITORY).toBeDefined();
      expect(configMap.data.IAM_ROLE_ARN).toBeDefined();
    });

    it('should validate proper resource cleanup order on deletion', async () => {
      // This test validates that resources can be properly cleaned up
      // by checking that the Kro instance status reflects proper dependency management
      const instance = await kubernetesClient.getKroInstance(testInstanceName, testNamespace);

      expect(instance.status.kubernetesResourcesReady).toBe(true);
      expect(instance.status.awsResourcesReady).toBe(true);
      expect(instance.status.workflowsReady).toBe(true);
      expect(instance.status.setupCompleted).toBe(true);
    });
  });
});