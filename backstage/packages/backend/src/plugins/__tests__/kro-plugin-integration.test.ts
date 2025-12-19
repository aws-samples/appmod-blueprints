import { ConfigReader } from '@backstage/config';
import { KroErrorHandler } from '../kro-error-handler';
import { KroAuditLogger } from '../kro-audit';

// Mock logger
const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};

// Mock audit logger
const mockAuditLogger = {
  logAuthenticationFailure: jest.fn(),
  logAuthorizationFailure: jest.fn(),
  logResourceGroupOperation: jest.fn(),
} as jest.Mocked<KroAuditLogger>;

// Mock user
const mockUser = {
  identity: {
    userEntityRef: 'user:default/test-user',
    type: 'user',
    ownershipEntityRefs: [],
  },
  token: 'mock-token',
};

describe('Kro Plugin Integration Tests', () => {
  let config: ConfigReader;
  let errorHandler: KroErrorHandler;

  beforeEach(() => {
    jest.clearAllMocks();

    config = new ConfigReader({
      kro: {
        enablePermissions: true,
        enableAuditLogging: true,
        clusters: [
          {
            name: 'test-cluster',
            url: 'https://test-cluster.example.com',
            authProvider: 'serviceAccount',
            serviceAccountToken: 'test-token',
          },
        ],
      },
      kubernetesIngestor: {
        refreshInterval: 300,
        resources: [
          {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'ResourceGraphDefinition',
          },
          {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'CICDPipeline',
          },
        ],
        clusters: [
          {
            name: 'test-cluster',
            url: 'https://test-cluster.example.com',
            authProvider: 'serviceAccount',
            serviceAccountToken: 'test-token',
          },
        ],
      },
    });

    errorHandler = new KroErrorHandler(mockLogger, mockAuditLogger);
  });

  describe('Configuration Validation', () => {
    it('should validate complete Kro configuration', () => {
      const kroConfig = config.getOptionalConfig('kro');
      expect(kroConfig).toBeDefined();

      const clusters = kroConfig!.getOptionalConfigArray('clusters') || [];
      expect(clusters).toHaveLength(1);

      const cluster = clusters[0];
      expect(cluster.getString('name')).toBe('test-cluster');
      expect(cluster.getString('url')).toBe('https://test-cluster.example.com');
      expect(cluster.getString('authProvider')).toBe('serviceAccount');
      expect(cluster.getString('serviceAccountToken')).toBe('test-token');
    });

    it('should validate Kubernetes Ingestor configuration', () => {
      const ingestorConfig = config.getOptionalConfig('kubernetesIngestor');
      expect(ingestorConfig).toBeDefined();

      const resources = ingestorConfig!.getOptionalConfigArray('resources') || [];
      expect(resources).toHaveLength(2);

      const kroResources = resources.filter(resource => {
        const apiVersion = resource.getOptionalString('apiVersion');
        return apiVersion?.startsWith('kro.run/');
      });
      expect(kroResources).toHaveLength(2);
    });

    it('should handle missing configuration gracefully', () => {
      const emptyConfig = new ConfigReader({});

      const kroConfig = emptyConfig.getOptionalConfig('kro');
      const ingestorConfig = emptyConfig.getOptionalConfig('kubernetesIngestor');

      expect(kroConfig).toBeUndefined();
      expect(ingestorConfig).toBeUndefined();
    });

    it('should validate cluster configuration requirements', () => {
      const invalidConfig = new ConfigReader({
        kro: {
          clusters: [
            {
              name: 'invalid-cluster',
              // Missing required url field
              authProvider: 'serviceAccount',
            },
          ],
        },
      });

      const kroConfig = invalidConfig.getOptionalConfig('kro');
      const clusters = kroConfig!.getOptionalConfigArray('clusters') || [];
      const cluster = clusters[0];

      expect(cluster.getString('name')).toBe('invalid-cluster');
      expect(() => cluster.getString('url')).toThrow();
    });
  });

  describe('Error Handling', () => {
    it('should handle Kubernetes connection errors', () => {
      const error = new Error('ECONNREFUSED');

      const result = errorHandler.handleConnectionError(error, {
        cluster: 'test-cluster',
        operation: 'list-resources',
      });

      expect(result.statusCode).toBe(503);
      expect(result.userMessage).toContain('Unable to connect to Kubernetes cluster');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes connection error'),
        expect.objectContaining({
          errorType: 'CONNECTION_ERROR',
          cluster: 'test-cluster',
          operation: 'list-resources',
        })
      );
    });

    it('should handle authentication errors', () => {
      const error = new Error('Unauthorized');

      const result = errorHandler.handleAuthenticationError(error, mockUser, {
        cluster: 'test-cluster',
        operation: 'create-resource',
      });

      expect(result.statusCode).toBe(401);
      expect(result.userMessage).toContain('Authentication failed');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes authentication failed'),
        expect.objectContaining({
          errorType: 'AUTHENTICATION_FAILED',
        })
      );
    });

    it('should handle authorization errors', () => {
      const error = new Error('Forbidden');

      const result = errorHandler.handleAuthorizationError(error, mockUser, {
        cluster: 'test-cluster',
        operation: 'delete-resource',
        resource: 'resourcegroups',
      });

      expect(result.statusCode).toBe(403);
      expect(result.userMessage).toContain("don't have permission");
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes authorization failed'),
        expect.objectContaining({
          errorType: 'AUTHORIZATION_FAILED',
        })
      );
    });

    it('should handle timeout errors', () => {
      const error = new Error('Request timeout');

      const result = errorHandler.handleConnectionError(error, {
        cluster: 'test-cluster',
        operation: 'get-resource',
      });

      expect(result.statusCode).toBe(503);
      expect(result.userMessage).toContain('timed out');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes connection error'),
        expect.objectContaining({
          errorType: 'CONNECTION_ERROR',
        })
      );
    });

    it('should handle ResourceGroup operation errors', () => {
      const error = new Error('ResourceGroup not found');

      const result = errorHandler.handleResourceGroupError(error, mockUser, {
        resourceGroup: 'test-rg',
        namespace: 'default',
        operation: 'get',
      });

      expect(result.statusCode).toBe(404);
      expect(result.userMessage).toContain('not found');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('ResourceGroup operation failed'),
        expect.objectContaining({
          resourceGroup: 'test-rg',
          namespace: 'default',
          operation: 'get',
          component: 'kro-error-handler',
        })
      );
    });


  });

  describe('Integration Validation', () => {
    it('should validate Kro and Kubernetes Ingestor integration', () => {
      const kroConfig = config.getOptionalConfig('kro');
      const ingestorConfig = config.getOptionalConfig('kubernetesIngestor');

      expect(kroConfig).toBeDefined();
      expect(ingestorConfig).toBeDefined();

      // Validate that both configurations have matching cluster definitions
      const kroClusters = kroConfig!.getOptionalConfigArray('clusters') || [];
      const ingestorClusters = ingestorConfig!.getOptionalConfigArray('clusters') || [];

      expect(kroClusters).toHaveLength(1);
      expect(ingestorClusters).toHaveLength(1);

      const kroCluster = kroClusters[0];
      const ingestorCluster = ingestorClusters[0];

      expect(kroCluster.getString('name')).toBe(ingestorCluster.getString('name'));
      expect(kroCluster.getString('url')).toBe(ingestorCluster.getString('url'));
    });

    it('should validate Kro resource types in Kubernetes Ingestor', () => {
      const ingestorConfig = config.getOptionalConfig('kubernetesIngestor');
      const resources = ingestorConfig!.getOptionalConfigArray('resources') || [];

      const kroResourceTypes = resources
        .filter(resource => {
          const apiVersion = resource.getOptionalString('apiVersion');
          return apiVersion?.startsWith('kro.run/');
        })
        .map(resource => ({
          apiVersion: resource.getOptionalString('apiVersion'),
          kind: resource.getOptionalString('kind'),
        }));

      expect(kroResourceTypes).toEqual([
        { apiVersion: 'kro.run/v1alpha1', kind: 'ResourceGraphDefinition' },
        { apiVersion: 'kro.run/v1alpha1', kind: 'CICDPipeline' },
      ]);
    });
  });

  describe('Module Initialization', () => {
    it('should initialize with valid configuration', () => {
      // Simulate module initialization
      const initializeKroModule = (config: ConfigReader, logger: any) => {
        const kroConfig = config.getOptionalConfig('kro');

        if (!kroConfig) {
          logger.warn('Kro plugin configuration not found. Plugin may not function correctly.');
          return false;
        }

        const clusters = kroConfig.getOptionalConfigArray('clusters') || [];
        if (clusters.length === 0) {
          logger.warn('No Kubernetes clusters configured for Kro plugin');
          return false;
        }

        // Validate each cluster configuration
        for (const [index, clusterConfig] of clusters.entries()) {
          try {
            const clusterName = clusterConfig.getString('name');
            const clusterUrl = clusterConfig.getString('url');
            const authProvider = clusterConfig.getString('authProvider');

            if (!clusterUrl) {
              throw new Error(`Cluster URL is required for cluster: ${clusterName}`);
            }

            if (!authProvider) {
              throw new Error(`Auth provider is required for cluster: ${clusterName}`);
            }

            logger.info(`Kro cluster configuration validated successfully: ${clusterName}`);
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            logger.error(`Invalid Kro cluster configuration at index ${index}: ${errorMessage}`);
            throw new Error(`Kro plugin initialization failed due to invalid cluster configuration: ${errorMessage}`);
          }
        }

        logger.info(`Kro plugin initialized successfully with ${clusters.length} cluster(s)`);
        return true;
      };

      const result = initializeKroModule(config, mockLogger);

      expect(result).toBe(true);
      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.stringContaining('Kro plugin initialized successfully')
      );
    });

    it('should fail initialization with invalid configuration', () => {
      const invalidConfig = new ConfigReader({
        kro: {
          clusters: [
            {
              name: 'invalid-cluster',
              // Missing required url field
              authProvider: 'serviceAccount',
            },
          ],
        },
      });

      const initializeKroModule = (config: ConfigReader, logger: any) => {
        const kroConfig = config.getOptionalConfig('kro');
        const clusters = kroConfig!.getOptionalConfigArray('clusters') || [];

        for (const [index, clusterConfig] of clusters.entries()) {
          try {
            const clusterName = clusterConfig.getString('name');
            const clusterUrl = clusterConfig.getString('url');

            if (!clusterUrl) {
              throw new Error(`Cluster URL is required for cluster: ${clusterName}`);
            }
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            logger.error(`Invalid Kro cluster configuration at index ${index}: ${errorMessage}`);
            throw new Error(`Kro plugin initialization failed due to invalid cluster configuration: ${errorMessage}`);
          }
        }

        return true;
      };

      expect(() => initializeKroModule(invalidConfig, mockLogger)).toThrow(
        'Kro plugin initialization failed due to invalid cluster configuration'
      );
    });
  });
});