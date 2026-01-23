import { KroRBACValidator } from '../kro-permissions';
import { KroAuditLogger, KroAuditEventType } from '../kro-audit';
import { KroErrorHandler } from '../kro-error-handler';
import { KroSecurityService } from '../kro-security';

// Mock logger
const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
};

// Mock user
const mockUser = {
  identity: {
    userEntityRef: 'user:default/test-user',
    type: 'user',
    ownershipEntityRefs: [],
  },
  token: 'mock-token',
};

describe('Kro Security Components', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('KroRBACValidator', () => {
    let rbacValidator: KroRBACValidator;

    beforeEach(() => {
      rbacValidator = new KroRBACValidator(mockLogger, null);
    });

    it('should validate permissions for admin users', async () => {
      const adminUser = {
        ...mockUser,
        identity: {
          ...mockUser.identity,
          userEntityRef: 'user:default/admin-user',
        },
      };

      const result = await rbacValidator.validateKubernetesPermissions(
        adminUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(true);
      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes RBAC validation successful'),
        expect.any(Object)
      );
    });

    it('should deny permissions for unauthorized users', async () => {
      const result = await rbacValidator.validateKubernetesPermissions(
        mockUser,
        'delete',
        'kro.run/v1alpha1/resourcegraphdefinitions',
        'default',
        'test-cluster'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('does not have permission');
      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes RBAC validation failed'),
        expect.any(Object)
      );
    });

    it('should allow service account authentication', async () => {
      const serviceUser = {
        ...mockUser,
        identity: {
          ...mockUser.identity,
          type: 'service',
        },
      };

      const result = await rbacValidator.validateKubernetesPermissions(
        serviceUser,
        'create',
        'kro.run/v1alpha1/resourcegraphdefinitions'
      );

      expect(result.allowed).toBe(true);
    });
  });

  describe('KroAuditLogger', () => {
    let auditLogger: KroAuditLogger;

    beforeEach(() => {
      auditLogger = new KroAuditLogger(mockLogger);
    });

    it('should log ResourceGroup operations', () => {
      auditLogger.logResourceGroupOperation(
        KroAuditEventType.RESOURCE_GROUP_CREATED,
        mockUser,
        {
          type: 'ResourceGroup',
          name: 'test-rg',
          namespace: 'default',
          cluster: 'test-cluster',
        },
        'create',
        'success',
        { templateUsed: 'cicd-pipeline' }
      );

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.RESOURCE_GROUP_CREATED,
          user: {
            userEntityRef: 'user:default/test-user',
            type: 'user',
          },
          resource: {
            type: 'ResourceGroup',
            name: 'test-rg',
            namespace: 'default',
            cluster: 'test-cluster',
          },
          action: 'create',
          result: 'success',
          details: { templateUsed: 'cicd-pipeline' },
          component: 'kro-audit',
          audit: true,
        })
      );
    });

    it('should log permission denied events', () => {
      auditLogger.logPermissionDenied(
        mockUser,
        {
          type: 'ResourceGroup',
          name: 'test-rg',
          namespace: 'default',
        },
        'delete',
        'Insufficient permissions'
      );

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.PERMISSION_DENIED,
          result: 'failure',
          error: 'Insufficient permissions',
        })
      );
    });
  });

  describe('KroErrorHandler', () => {
    let errorHandler: KroErrorHandler;
    let auditLogger: KroAuditLogger;

    beforeEach(() => {
      auditLogger = new KroAuditLogger(mockLogger);
      errorHandler = new KroErrorHandler(mockLogger, auditLogger);
    });

    it('should handle authentication errors', () => {
      const error = new Error('Unauthorized');
      const result = errorHandler.handleAuthenticationError(
        error,
        mockUser,
        {
          cluster: 'test-cluster',
          operation: 'create',
          resource: 'ResourceGroup',
        }
      );

      expect(result.statusCode).toBe(401);
      expect(result.userMessage).toContain('Authentication failed');
      expect(result.userMessage).toContain('test-cluster');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Kubernetes authentication failed'),
        expect.any(Object)
      );
    });

    it('should handle authorization errors with guidance', () => {
      const error = new Error('Forbidden');
      const result = errorHandler.handleAuthorizationError(
        error,
        mockUser,
        {
          cluster: 'test-cluster',
          operation: 'create',
          resource: 'ResourceGroup',
          requiredPermissions: ['kro.run/resourcegraphdefinitions:create'],
        }
      );

      expect(result.statusCode).toBe(403);
      expect(result.userMessage).toContain("don't have permission");
      expect(result.guidance).toContain('Required permissions');
      expect(result.guidance).toContain('kro.run/resourcegraphdefinitions:create');
    });

    it('should handle ResourceGroup operation errors', () => {
      const error = new Error('ResourceGroup not found');
      const result = errorHandler.handleResourceGroupError(
        error,
        mockUser,
        {
          resourceGroup: 'test-rg',
          namespace: 'default',
          cluster: 'test-cluster',
          operation: 'get',
        }
      );

      expect(result.statusCode).toBe(404);
      expect(result.userMessage).toContain('not found');
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('ResourceGroup operation failed'),
        expect.any(Object)
      );
    });
  });

  describe('KroSecurityService', () => {
    it('should initialize with valid configuration', () => {
      const config = {
        enablePermissions: true,
        enableAuditLogging: true,
        rbacValidation: {
          enabled: true,
          strictMode: false,
          cacheTimeout: 300,
        },
        auditLogging: {
          enabled: true,
          logLevel: 'info' as const,
          includeSuccessEvents: true,
        },
        errorHandling: {
          enableDetailedErrors: true,
          includeStackTrace: false,
        },
      };

      const securityService = new KroSecurityService(mockLogger, config);
      const validation = securityService.validateConfiguration();

      expect(validation.valid).toBe(true);
      expect(validation.errors).toHaveLength(0);
      expect(mockLogger.info).toHaveBeenCalledWith(
        expect.stringContaining('Kro security service initialized'),
        expect.any(Object)
      );
    });

    it('should validate configuration and report errors', () => {
      const invalidConfig = {
        enablePermissions: true,
        enableAuditLogging: true,
        rbacValidation: {
          enabled: false, // This should cause an error
          strictMode: false,
          cacheTimeout: -1, // This should also cause an error
        },
        auditLogging: {
          enabled: true,
          logLevel: 'invalid' as any, // This should cause an error
          includeSuccessEvents: true,
        },
        errorHandling: {
          enableDetailedErrors: true,
          includeStackTrace: false,
        },
      };

      const securityService = new KroSecurityService(mockLogger, invalidConfig);
      const validation = securityService.validateConfiguration();

      expect(validation.valid).toBe(false);
      expect(validation.errors).toContain('RBAC validation must be enabled when permissions are enabled');
      expect(validation.errors).toContain('RBAC cache timeout must be non-negative');
      expect(validation.errors).toContain('Invalid audit logging level');
    });
  });
});