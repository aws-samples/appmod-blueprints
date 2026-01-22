import AWS from 'aws-sdk';

export class AWSTestClient {
  constructor() {
    // Configure AWS SDK
    this.region = process.env.AWS_REGION || 'us-west-2';

    AWS.config.update({
      region: this.region,
      // Use environment credentials or IAM role
      accessKeyId: process.env.AWS_ACCESS_KEY_ID,
      secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
      sessionToken: process.env.AWS_SESSION_TOKEN
    });

    this.ecr = new AWS.ECR();
    this.iam = new AWS.IAM();
    this.eks = new AWS.EKS();

    this.testResources = new Map();
    this.mockMode = process.env.AWS_MOCK_MODE === 'true';
  }

  async verifyConnection() {
    if (this.mockMode) {
      throw new Error('Running in mock mode - no AWS connection');
    }

    try {
      // Simple call to verify AWS credentials and connectivity
      await this.iam.getUser().promise();
      return true;
    } catch (error) {
      if (error.code === 'AccessDenied') {
        // We have credentials but limited permissions, that's okay
        return true;
      }
      throw new Error(`AWS connection failed: ${error.message}`);
    }
  }

  async checkECRRepository(repositoryName) {
    if (this.mockMode) {
      return {
        repositoryArn: `arn:aws:ecr:${this.region}:123456789012:repository/${repositoryName}`,
        repositoryName,
        repositoryUri: `123456789012.dkr.ecr.${this.region}.amazonaws.com/${repositoryName}`,
        registryId: '123456789012'
      };
    }

    try {
      const result = await this.ecr.describeRepositories({
        repositoryNames: [repositoryName]
      }).promise();

      return result.repositories[0];
    } catch (error) {
      if (error.code === 'RepositoryNotFoundException') {
        return null;
      }
      throw error;
    }
  }

  async waitForECRRepository(repositoryName, timeoutMs = 180000) {
    if (this.mockMode) {
      return {
        repositoryArn: `arn:aws:ecr:${this.region}:123456789012:repository/${repositoryName}`,
        repositoryName,
        repositoryUri: `123456789012.dkr.ecr.${this.region}.amazonaws.com/${repositoryName}`,
        registryId: '123456789012'
      };
    }

    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      const repository = await this.checkECRRepository(repositoryName);
      if (repository) {
        return repository;
      }

      await new Promise(resolve => setTimeout(resolve, 10000)); // Wait 10 seconds
    }

    throw new Error(`Timeout waiting for ECR repository ${repositoryName} to be created`);
  }

  async checkIAMPolicy(policyName) {
    if (this.mockMode) {
      return {
        PolicyName: policyName,
        Arn: `arn:aws:iam::123456789012:policy/${policyName}`,
        PolicyId: 'ANPAI23HZ27SI6FQMGNQ2'
      };
    }

    try {
      const result = await this.iam.getPolicy({
        PolicyArn: `arn:aws:iam::${await this.getAccountId()}:policy/${policyName}`
      }).promise();

      return result.Policy;
    } catch (error) {
      if (error.code === 'NoSuchEntity') {
        return null;
      }
      throw error;
    }
  }

  async checkIAMRole(roleName) {
    if (this.mockMode) {
      return {
        RoleName: roleName,
        Arn: `arn:aws:iam::123456789012:role/${roleName}`,
        RoleId: 'AROA23HZ27SI6FQMGNQ2'
      };
    }

    try {
      const result = await this.iam.getRole({
        RoleName: roleName
      }).promise();

      return result.Role;
    } catch (error) {
      if (error.code === 'NoSuchEntity') {
        return null;
      }
      throw error;
    }
  }

  async waitForIAMRole(roleName, timeoutMs = 180000) {
    if (this.mockMode) {
      return {
        RoleName: roleName,
        Arn: `arn:aws:iam::123456789012:role/${roleName}`,
        RoleId: 'AROA23HZ27SI6FQMGNQ2'
      };
    }

    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      const role = await this.checkIAMRole(roleName);
      if (role) {
        return role;
      }

      await new Promise(resolve => setTimeout(resolve, 10000)); // Wait 10 seconds
    }

    throw new Error(`Timeout waiting for IAM role ${roleName} to be created`);
  }

  async checkPodIdentityAssociation(clusterName, namespace, serviceAccount) {
    if (this.mockMode) {
      return {
        associationArn: `arn:aws:eks:${this.region}:123456789012:podidentityassociation/test-cluster/a-123456789`,
        associationId: 'a-123456789',
        clusterName,
        namespace,
        serviceAccount
      };
    }

    try {
      const result = await this.eks.listPodIdentityAssociations({
        clusterName
      }).promise();

      // Find association matching namespace and service account
      for (const association of result.associations) {
        const details = await this.eks.describePodIdentityAssociation({
          clusterName,
          associationId: association.associationId
        }).promise();

        if (details.association.namespace === namespace &&
          details.association.serviceAccount === serviceAccount) {
          return details.association;
        }
      }

      return null;
    } catch (error) {
      if (error.code === 'ResourceNotFoundException') {
        return null;
      }
      throw error;
    }
  }

  async waitForPodIdentityAssociation(clusterName, namespace, serviceAccount, timeoutMs = 180000) {
    if (this.mockMode) {
      return {
        associationArn: `arn:aws:eks:${this.region}:123456789012:podidentityassociation/test-cluster/a-123456789`,
        associationId: 'a-123456789',
        clusterName,
        namespace,
        serviceAccount
      };
    }

    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      const association = await this.checkPodIdentityAssociation(clusterName, namespace, serviceAccount);
      if (association) {
        return association;
      }

      await new Promise(resolve => setTimeout(resolve, 15000)); // Wait 15 seconds
    }

    throw new Error(`Timeout waiting for Pod Identity Association for ${namespace}/${serviceAccount} to be created`);
  }

  async testECRAuthentication() {
    if (this.mockMode) {
      return 'mock-token-12345';
    }

    try {
      const result = await this.ecr.getAuthorizationToken().promise();
      return result.authorizationData[0].authorizationToken;
    } catch (error) {
      throw new Error(`ECR authentication failed: ${error.message}`);
    }
  }

  async getAccountId() {
    if (this.mockMode) {
      return '123456789012';
    }

    if (this.accountId) {
      return this.accountId;
    }

    try {
      const result = await this.iam.getUser().promise();
      this.accountId = result.User.Arn.split(':')[4];
      return this.accountId;
    } catch (error) {
      // Fallback: try to get account ID from STS
      const sts = new AWS.STS();
      const identity = await sts.getCallerIdentity().promise();
      this.accountId = identity.Account;
      return this.accountId;
    }
  }

  trackResource(type, identifier) {
    this.testResources.set(identifier, { type, identifier });
  }

  async cleanup() {
    if (this.mockMode) {
      return;
    }

    console.log('🧹 Cleaning up AWS test resources...');

    // Note: In a real test environment, you might want to clean up AWS resources
    // However, for integration tests, we typically rely on ACK controllers
    // to manage the lifecycle of AWS resources through Kubernetes

    this.testResources.clear();
  }
}