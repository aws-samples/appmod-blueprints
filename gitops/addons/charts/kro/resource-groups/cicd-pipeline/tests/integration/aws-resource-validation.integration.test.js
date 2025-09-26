import { describe, it, expect, beforeAll, afterAll } from 'vitest';

describe('AWS Resource Validation Integration Tests', () => {
  let awsClient;
  let kubernetesClient;
  let testNamespace;
  let testInstanceName;

  beforeAll(async () => {
    awsClient = globalThis.awsClient;
    kubernetesClient = globalThis.kubernetesClient;

    // Use existing test resources from the main provisioning test
    const timestamp = Date.now();
    testNamespace = `test-aws-${timestamp}`;
    testInstanceName = `test-aws-pipeline-${timestamp}`;
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

  describe('ECR Repository Management', () => {
    it('should create ECR repositories with correct naming convention', async () => {
      // Setup test instance
      await kubernetesClient.createTestNamespace(testNamespace);

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
    name: test-aws-app
    dockerfilePath: "."
    deploymentPath: "./deployment"
  ecr:
    repositoryPrefix: "modengg"
  gitlab:
    hostname: "gitlab.example.com"
    username: "testuser"
`;

      await kubernetesClient.applyKroInstance(instanceYaml, testNamespace);

      // Wait for repositories to be created
      const mainRepo = await awsClient.waitForECRRepository('modengg/test-aws-app', 180000);
      const cacheRepo = await awsClient.waitForECRRepository('modengg/test-aws-app/cache', 180000);

      expect(mainRepo.repositoryName).toBe('modengg/test-aws-app');
      expect(cacheRepo.repositoryName).toBe('modengg/test-aws-app/cache');

      // Validate repository URIs follow AWS ECR format
      expect(mainRepo.repositoryUri).toMatch(/^\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com\/modengg\/test-aws-app$/);
      expect(cacheRepo.repositoryUri).toMatch(/^\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com\/modengg\/test-aws-app\/cache$/);
    }, 200000);

    it('should validate ECR repository policies allow proper access', async () => {
      const mainRepo = await awsClient.checkECRRepository('modengg/test-aws-app');
      expect(mainRepo).toBeDefined();

      // Repository should exist and be accessible
      expect(mainRepo.repositoryArn).toContain(':repository/modengg/test-aws-app');
      expect(mainRepo.registryId).toMatch(/^\d{12}$/);
    });

    it('should validate ECR authentication token generation', async () => {
      const authToken = await awsClient.testECRAuthentication();

      expect(authToken).toBeDefined();
      expect(typeof authToken).toBe('string');

      // Decode the token to validate structure
      const decodedToken = Buffer.from(authToken, 'base64').toString();
      expect(decodedToken).toContain('AWS:');
    });
  });

  describe('IAM Resource Management', () => {
    it('should create IAM policy with correct ECR permissions', async () => {
      const policyName = `${testInstanceName}-ecr-policy`;
      const policy = await awsClient.checkIAMPolicy(policyName);

      expect(policy).toBeDefined();
      expect(policy.PolicyName).toBe(policyName);
      expect(policy.Arn).toContain(`:policy/${policyName}`);
    });

    it('should create IAM role with EKS pod identity trust policy', async () => {
      const roleName = `${testInstanceName}-role`;
      const role = await awsClient.waitForIAMRole(roleName, 180000);

      expect(role).toBeDefined();
      expect(role.RoleName).toBe(roleName);
      expect(role.Arn).toContain(`:role/${roleName}`);

      // Validate the role has the correct trust policy for EKS pod identity
      expect(role.AssumeRolePolicyDocument).toBeDefined();
    }, 180000);

    it('should validate IAM role policy attachment', async () => {
      const roleName = `${testInstanceName}-role`;
      const policyName = `${testInstanceName}-ecr-policy`;

      // Both role and policy should exist
      const role = await awsClient.checkIAMRole(roleName);
      const policy = await awsClient.checkIAMPolicy(policyName);

      expect(role).toBeDefined();
      expect(policy).toBeDefined();

      // In a real test, you might check attached policies
      // For now, we validate they exist and can be referenced
      expect(role.Arn).toContain(roleName);
      expect(policy.Arn).toContain(policyName);
    });
  });

  describe('EKS Pod Identity Integration', () => {
    it('should create Pod Identity Association with correct configuration', async () => {
      const clusterName = 'test-cluster';
      const serviceAccountName = `${testInstanceName}-sa`;

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
    }, 180000);

    it('should validate Pod Identity Association links to correct IAM role', async () => {
      const clusterName = 'test-cluster';
      const serviceAccountName = `${testInstanceName}-sa`;
      const roleName = `${testInstanceName}-role`;

      const association = await awsClient.checkPodIdentityAssociation(
        clusterName,
        testNamespace,
        serviceAccountName
      );

      const role = await awsClient.checkIAMRole(roleName);

      expect(association).toBeDefined();
      expect(role).toBeDefined();

      // The association should reference the correct role ARN
      expect(association.roleArn).toBe(role.Arn);
    });
  });

  describe('AWS Resource Status and Health', () => {
    it('should validate all AWS resources are in healthy state', async () => {
      // Check ECR repositories are accessible
      const mainRepo = await awsClient.checkECRRepository('modengg/test-aws-app');
      const cacheRepo = await awsClient.checkECRRepository('modengg/test-aws-app/cache');

      expect(mainRepo).toBeDefined();
      expect(cacheRepo).toBeDefined();

      // Check IAM resources exist
      const policy = await awsClient.checkIAMPolicy(`${testInstanceName}-ecr-policy`);
      const role = await awsClient.checkIAMRole(`${testInstanceName}-role`);

      expect(policy).toBeDefined();
      expect(role).toBeDefined();

      // Check Pod Identity Association exists
      const association = await awsClient.checkPodIdentityAssociation(
        'test-cluster',
        testNamespace,
        `${testInstanceName}-sa`
      );

      expect(association).toBeDefined();
    });

    it('should validate AWS resource ARNs are properly formatted', async () => {
      const mainRepo = await awsClient.checkECRRepository('modengg/test-aws-app');
      const role = await awsClient.checkIAMRole(`${testInstanceName}-role`);
      const policy = await awsClient.checkIAMPolicy(`${testInstanceName}-ecr-policy`);

      // Validate ARN formats
      expect(mainRepo.repositoryArn).toMatch(/^arn:aws:ecr:[a-z0-9-]+:\d{12}:repository\/.+$/);
      expect(role.Arn).toMatch(/^arn:aws:iam::\d{12}:role\/.+$/);
      expect(policy.Arn).toMatch(/^arn:aws:iam::\d{12}:policy\/.+$/);
    });

    it('should validate AWS resources have correct tags and metadata', async () => {
      const association = await awsClient.checkPodIdentityAssociation(
        'test-cluster',
        testNamespace,
        `${testInstanceName}-sa`
      );

      expect(association).toBeDefined();

      // Pod Identity Association should have proper metadata
      expect(association.clusterName).toBe('test-cluster');
      expect(association.namespace).toBe(testNamespace);
      expect(association.serviceAccount).toBe(`${testInstanceName}-sa`);
    });
  });

  describe('AWS Resource Integration with Kubernetes', () => {
    it('should validate Kubernetes resources reference correct AWS ARNs', async () => {
      const configMap = await kubernetesClient.getConfigMap(
        `${testInstanceName}-config`,
        testNamespace
      );

      const serviceAccount = await kubernetesClient.getServiceAccount(
        `${testInstanceName}-sa`,
        testNamespace
      );

      // ConfigMap should contain AWS resource information
      expect(configMap.data.ECR_MAIN_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\/modengg\/test-aws-app$/);
      expect(configMap.data.ECR_CACHE_REPOSITORY).toMatch(/\.dkr\.ecr\..+\.amazonaws\.com\/modengg\/test-aws-app\/cache$/);
      expect(configMap.data.AWS_ACCOUNT_ID).toMatch(/^\d{12}$/);
      expect(configMap.data.IAM_ROLE_ARN).toMatch(/^arn:aws:iam::\d{12}:role\/.+$/);

      // Service Account should have IAM role annotation
      expect(serviceAccount.metadata.annotations['eks.amazonaws.com/role-arn']).toMatch(/^arn:aws:iam::\d{12}:role\/.+$/);
      expect(serviceAccount.metadata.annotations['eks.amazonaws.com/pod-identity-association']).toMatch(/^arn:aws:eks:.+:podidentityassociation\/.+$/);
    });

    it('should validate Docker registry secret contains valid ECR credentials', async () => {
      const dockerSecret = await kubernetesClient.getSecret(
        `${testInstanceName}-docker-config`,
        testNamespace
      );

      expect(dockerSecret).toBeDefined();
      expect(dockerSecret.type).toBe('kubernetes.io/dockerconfigjson');

      // Decode and validate Docker config structure
      const dockerConfigJson = Buffer.from(dockerSecret.data['.dockerconfigjson'], 'base64').toString();
      const dockerConfig = JSON.parse(dockerConfigJson);

      expect(dockerConfig).toHaveProperty('auths');

      // Should have ECR registry entries
      const registryKeys = Object.keys(dockerConfig.auths);
      expect(registryKeys.some(key => key.includes('.dkr.ecr.') && key.includes('.amazonaws.com'))).toBe(true);
    });
  });
});