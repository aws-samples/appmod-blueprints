import { KroRBACValidator } from '../kro-permissions';
import { KroAuditLogger, KroAuditEventType } from '../kro-audit';
import { ConfigReader } from '@backstage/config';

// Mock Kubernetes client
const mockKubernetesClient = {
  canI: jest.fn(),
  getServiceAccountPermissions: jest.fn(),
  validateClusterAccess: jest.fn(),
};

// Mock logger
const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};

// Mock users
const mockAdminUser = {
  identity: {
    userEntityRef: 'user:default/admin-user',
    type: 'user',
    ownershipEntityRefs: ['group:default/platform-admins'],
  },
  token: 'admin-token',
};

const mockDeveloperUser = {
  identity: {
    userEntityRef: 'user:default/developer',
    type: 'user',
    ownershipEntityRefs: ['group:default/developers'],
  },
  token: 'developer-token',
};

const mockServiceUser = {
  identity: {
    userEntityRef: 'user:default/backstage-service',
    type: 'service',
    ownershipEntityRefs: [],
  },
  token: 'service-token',
};

const mockGuestUser = {
  identity: {
    userEntityRef: 'user:default/guest',
    type: 'user',
    ownershipEntityRefs: [],
  },
  token: 'guest-token',
};

describe('Kro Permissions Validation', () => {
  let rbacValidator: KroRBACValidator;
  let auditLogger: KroAuditLogger;
  let config: ConfigReader;

  beforeEach(() => {
    jest.clearAllMocks();

    config = new ConfigReader({
      kro: {
        enablePermissions: true,
        rbacValidation: {
          enabled: true,
          strictMode: false,
          cacheTimeout: 300,
        },
        clusters: [
          {
            name: 'test-cluster',
            url: 'https://test-cluster.example.com',
            authProvider: 'serviceAccount',
            serviceAccountToken: 'test-token',
            rbac: {
              requiredPermissions: [
                {
                  apiGroups: ['kro.run'],
                  resources: ['resourcegraphdefinitions'],
                  verbs: ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete'],
                },
                {
                  apiGroups: ['kro.run'],
                  resources: ['cicdpipelines', 'eksclusters'],
                  verbs: ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete'],
                },
              ],
              readOnlyPermissions: [
                {
                  apiGroups: ['kro.run'],
                  resources: ['resourcegraphdefinitions', 'cicdpipelines', 'eksclusters'],
                  verbs: ['get', 'list', 'watch'],
                },
              ],
            },
          },
        ],
      },
    });

    auditLogger = new KroAuditLogger(mockLogger);
    rbacValidator = new KroRBACValidator(mockLogger, config);

    // Mock the Kubernetes client
    (rbacValidator as any).kubernetesClient = mockKubernetesClient;
  });

  describe('Admin User Permissions', () => {
    it('should allow all operations for admin users', async () => {
      mockKubernetesClient.canI.mockResolvedValue(true);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockAdminUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
      expect(result.reason).toContain('has permission');
      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes RBAC validation successful'),
        expect.objectContaining({
          user: 'user:default/admin-user',
          action: 'create',
          resource: 'kro.run/v1alpha1/resourcegraphdefinitions',
          namespace: 'default',
          cluster: 'test-cluster',
        })
      );
    });

    it('should allow admin users to delete ResourceGroups', async () => {
      mockKubernetesClient.canI.mockResolvedValue(true);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockAdminUser,
        'delete',
        'kro.run/v1alpha1/cicdpipelines',
        'production',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
      expect(mockKubernetesClient.canI).toHaveBeenCalledWith(
        'delete',
        'cicdpipelines',
        'kro.run',
        'production'
      );
    });

    it('should allow admin users to manage ResourceGraphDefinitions', async () => {
      mockKubernetesClient.canI.mockResolvedValue(true);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockAdminUser,
        'update',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
    });
  });

  describe('Developer User Permissions', () => {
    it('should allow developers to create ResourceGroups in development namespaces', async () => {
      mockKubernetesClient.canI.mockImplementation((verb, resource, apiGroup, namespace) => {
        // Allow create in development namespaces
        if (verb === 'create' && namespace?.startsWith('dev-')) {
          return Promise.resolve(true);
        }
        // Allow read operations everywhere
        if (['get', 'list', 'watch'].includes(verb)) {
          return Promise.resolve(true);
        }
        return Promise.resolve(false);
      });

      const result = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/cicdpipelines',
        'dev-team-a',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
      expect(result.reason).toContain('has permission');
    });

    it('should deny developers from creating ResourceGroups in production namespaces', async () => {
      mockKubernetesClient.canI.mockImplementation((verb, resource, apiGroup, namespace) => {
        // Deny create in production namespaces
        if (verb === 'create' && namespace === 'production') {
          return Promise.resolve(false);
        }
        // Allow read operations everywhere
        if (['get', 'list', 'watch'].includes(verb)) {
          return Promise.resolve(true);
        }
        return Promise.resolve(false);
      });

      const result = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/cicdpipelines',
        'production',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('does not have permission');
      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes RBAC validation failed'),
        expect.objectContaining({
          user: 'user:default/developer',
          action: 'create',
          namespace: 'production',
        })
      );
    });

    it('should allow developers to read ResourceGroups everywhere', async () => {
      mockKubernetesClient.canI.mockImplementation((verb) => {
        return Promise.resolve(['get', 'list', 'watch'].includes(verb));
      });

      const readResult = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/cicdpipelines',
        'production',
        'test-cluster'
      );

      expect(readResult.allowed).toBe(true);

      const listResult = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'list',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(listResult.allowed).toBe(true);
    });

    it('should deny developers from deleting ResourceGroups', async () => {
      mockKubernetesClient.canI.mockImplementation((verb) => {
        return Promise.resolve(verb !== 'delete');
      });

      const result = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'delete',
        'kro.run/v1alpha1/cicdpipelines',
        'dev-team-a',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('does not have permission');
    });
  });

  describe('Service Account Permissions', () => {
    it('should allow service accounts with proper permissions', async () => {
      mockKubernetesClient.canI.mockResolvedValue(true);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockServiceUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
      expect(result.reason).toContain('Service account has permission');
    });

    it('should validate service account token permissions', async () => {
      mockKubernetesClient.getServiceAccountPermissions.mockResolvedValue({
        rules: [
          {
            apiGroups: ['kro.run'],
            resources: ['resourcegraphdefinitions'],
            verbs: ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete'],
          },
        ],
      });

      const result = await rbacValidator.validateServiceAccountPermissions(
        'test-cluster',
        'test-token'
      );

      expect(result.valid).toBe(true);
      expect(result.permissions).toHaveLength(1);
      expect(result.permissions[0].resources).toContain('resourcegraphdefinitions');
    });

    it('should detect insufficient service account permissions', async () => {
      mockKubernetesClient.getServiceAccountPermissions.mockResolvedValue({
        rules: [
          {
            apiGroups: ['kro.run'],
            resources: ['resourcegraphdefinitions'],
            verbs: ['get', 'list'], // Missing create, update, delete
          },
        ],
      });

      const result = await rbacValidator.validateServiceAccountPermissions(
        'test-cluster',
        'test-token'
      );

      expect(result.valid).toBe(false);
      expect(result.missingPermissions).toContain('create');
      expect(result.missingPermissions).toContain('update');
      expect(result.missingPermissions).toContain('delete');
    });
  });

  describe('Guest User Permissions', () => {
    it('should deny all write operations for guest users', async () => {
      mockKubernetesClient.canI.mockImplementation((verb) => {
        // Guest users can only read
        return Promise.resolve(['get', 'list', 'watch'].includes(verb));
      });

      const createResult = await rbacValidator.validateKubernetesPermissions(
        mockGuestUser,
        'create',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(createResult.allowed).toBe(false);

      const updateResult = await rbacValidator.validateKubernetesPermissions(
        mockGuestUser,
        'update',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(updateResult.allowed).toBe(false);

      const deleteResult = await rbacValidator.validateKubernetesPermissions(
        mockGuestUser,
        'delete',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(deleteResult.allowed).toBe(false);
    });

    it('should allow read operations for guest users', async () => {
      mockKubernetesClient.canI.mockImplementation((verb) => {
        return Promise.resolve(['get', 'list', 'watch'].includes(verb));
      });

      const readResult = await rbacValidator.validateKubernetesPermissions(
        mockGuestUser,
        'get',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(readResult.allowed).toBe(true);

      const listResult = await rbacValidator.validateKubernetesPermissions(
        mockGuestUser,
        'list',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(listResult.allowed).toBe(true);
    });
  });

  describe('Permission Caching', () => {
    it('should cache permission results', async () => {
      mockKubernetesClient.canI.mockResolvedValue(true);

      // First call
      const result1 = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      // Second call with same parameters
      const result2 = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(result1.allowed).toBe(true);
      expect(result2.allowed).toBe(true);

      // Kubernetes API should only be called once due to caching
      expect(mockKubernetesClient.canI).toHaveBeenCalledTimes(1);
    });

    it('should respect cache timeout', async () => {
      // Create validator with short cache timeout
      const shortCacheConfig = new ConfigReader({
        kro: {
          rbacValidation: {
            enabled: true,
            cacheTimeout: 0.1, // 100ms
          },
        },
      });

      const shortCacheValidator = new KroRBACValidator(mockLogger, shortCacheConfig);
      (shortCacheValidator as any).kubernetesClient = mockKubernetesClient;

      mockKubernetesClient.canI.mockResolvedValue(true);

      // First call
      await shortCacheValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      // Wait for cache to expire
      await new Promise(resolve => setTimeout(resolve, 150));

      // Second call after cache expiry
      await shortCacheValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      // Should be called twice due to cache expiry
      expect(mockKubernetesClient.canI).toHaveBeenCalledTimes(2);
    });
  });

  describe('Error Handling', () => {
    it('should handle Kubernetes API errors', async () => {
      const apiError = new Error('Kubernetes API unavailable');
      mockKubernetesClient.canI.mockRejectedValue(apiError);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Permission check failed');
      expect(result.error).toBe('Kubernetes API unavailable');

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Failed to validate Kubernetes permissions'),
        expect.objectContaining({
          error: 'Kubernetes API unavailable',
          user: 'user:default/developer',
        })
      );
    });

    it('should handle authentication errors', async () => {
      const authError = new Error('Unauthorized');
      mockKubernetesClient.canI.mockRejectedValue(authError);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Authentication failed');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Authentication failed'),
        expect.any(Object)
      );
    });

    it('should handle network errors gracefully', async () => {
      const networkError = new Error('ECONNREFUSED');
      mockKubernetesClient.canI.mockRejectedValue(networkError);

      const result = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Network error');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Network error during permission validation'),
        expect.any(Object)
      );
    });
  });

  describe('Strict Mode', () => {
    it('should enforce strict permissions in strict mode', async () => {
      const strictConfig = new ConfigReader({
        kro: {
          rbacValidation: {
            enabled: true,
            strictMode: true,
            cacheTimeout: 300,
          },
        },
      });

      const strictValidator = new KroRBACValidator(mockLogger, strictConfig);
      (strictValidator as any).kubernetesClient = mockKubernetesClient;

      // In strict mode, even admin users need explicit permissions
      mockKubernetesClient.canI.mockResolvedValue(false);

      const result = await strictValidator.validateKubernetesPermissions(
        mockAdminUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Strict mode: explicit permission required');
    });

    it('should allow operations with explicit permissions in strict mode', async () => {
      const strictConfig = new ConfigReader({
        kro: {
          rbacValidation: {
            enabled: true,
            strictMode: true,
            cacheTimeout: 300,
          },
        },
      });

      const strictValidator = new KroRBACValidator(mockLogger, strictConfig);
      (strictValidator as any).kubernetesClient = mockKubernetesClient;

      mockKubernetesClient.canI.mockResolvedValue(true);

      const result = await strictValidator.validateKubernetesPermissions(
        mockAdminUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
      expect(result.reason).toContain('has explicit permission');
    });
  });

  describe('Resource-Specific Permissions', () => {
    it('should validate permissions for different ResourceGroup types', async () => {
      mockKubernetesClient.canI.mockImplementation((verb, resource) => {
        // Allow operations on CICDPipelines but not EksClusters
        return Promise.resolve(resource === 'cicdpipelines');
      });

      const cicdResult = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/cicdpipelines',
        'default',
        'test-cluster'
      );

      const eksResult = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/eksclusters',
        'default',
        'test-cluster'
      );

      expect(cicdResult.allowed).toBe(true);
      expect(eksResult.allowed).toBe(false);
    });

    it('should validate permissions for ResourceGraphDefinitions separately', async () => {
      mockKubernetesClient.canI.mockImplementation((verb, resource) => {
        // Only allow read operations on ResourceGraphDefinitions
        if (resource === 'resourcegraphdefinitions') {
          return Promise.resolve(['get', 'list', 'watch'].includes(verb));
        }
        return Promise.resolve(true);
      });

      const readRGDResult = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'get',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      const createRGDResult = await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(readRGDResult.allowed).toBe(true);
      expect(createRGDResult.allowed).toBe(false);
    });
  });

  describe('Audit Integration', () => {
    it('should log permission validation events', async () => {
      mockKubernetesClient.canI.mockResolvedValue(false);

      await rbacValidator.validateKubernetesPermissions(
        mockDeveloperUser,
        'delete',
        'kro.run/v1alpha1/cicdpipelines',
        'production',
        'test-cluster'
      );

      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes RBAC validation failed'),
        expect.objectContaining({
          user: 'user:default/developer',
          action: 'delete',
          resource: 'kro.run/v1alpha1/cicdpipelines',
          namespace: 'production',
          cluster: 'test-cluster',
          component: 'kro-rbac-validator',
        })
      );
    });

    it('should log successful permission validations', async () => {
      mockKubernetesClient.canI.mockResolvedValue(true);

      await rbacValidator.validateKubernetesPermissions(
        mockAdminUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes RBAC validation successful'),
        expect.objectContaining({
          user: 'user:default/admin-user',
          action: 'create',
          resource: 'kro.run/v1alpha1/resourcegraphdefinitions',
          namespace: 'default',
          cluster: 'test-cluster',
        })
      );
    });
  });
});