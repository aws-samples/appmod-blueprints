import { ConfigReader } from '@backstage/config';
import { KroResourceGroupService } from '../kro-resource-group-service';
import { KroErrorHandler } from '../kro-error-handler';
import { KroAuditLogger, KroAuditEventType } from '../kro-audit';

// Mock Kubernetes client
const mockKubernetesClient = {
  createResourceGroup: jest.fn(),
  getResourceGroup: jest.fn(),
  updateResourceGroup: jest.fn(),
  deleteResourceGroup: jest.fn(),
  listResourceGroups: jest.fn(),
  listResourceGraphDefinitions: jest.fn(),
  getResourceGraphDefinition: jest.fn(),
  watchResourceGroup: jest.fn(),
};

// Mock logger
const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
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

describe('Kro ResourceGroup Workflows', () => {
  let service: KroResourceGroupService;
  let errorHandler: KroErrorHandler;
  let auditLogger: KroAuditLogger;
  let config: ConfigReader;

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
    });

    auditLogger = new KroAuditLogger(mockLogger);
    errorHandler = new KroErrorHandler(mockLogger, auditLogger);
    service = new KroResourceGroupService(config, mockLogger, errorHandler, auditLogger);

    // Mock the Kubernetes client
    (service as any).kubernetesClient = mockKubernetesClient;
  });

  describe('ResourceGraphDefinition Discovery', () => {
    it('should discover available ResourceGraphDefinitions', async () => {
      const mockRGDs = [
        {
          apiVersion: 'kro.run/v1alpha1',
          kind: 'ResourceGraphDefinition',
          metadata: {
            name: 'cicd-pipeline',
            namespace: 'default',
          },
          spec: {
            schema: {
              apiVersion: 'kro.run/v1alpha1',
              kind: 'CICDPipeline',
              spec: {
                properties: {
                  name: { type: 'string' },
                  repository: { type: 'string' },
                  branch: { type: 'string', default: 'main' },
                },
                required: ['name', 'repository'],
              },
            },
            resources: [
              {
                id: 'namespace',
                template: {
                  apiVersion: 'v1',
                  kind: 'Namespace',
                  metadata: { name: '{{ .spec.name }}' },
                },
              },
            ],
          },
        },
        {
          apiVersion: 'kro.run/v1alpha1',
          kind: 'ResourceGraphDefinition',
          metadata: {
            name: 'eks-cluster',
            namespace: 'default',
          },
          spec: {
            schema: {
              apiVersion: 'kro.run/v1alpha1',
              kind: 'EksCluster',
              spec: {
                properties: {
                  clusterName: { type: 'string' },
                  region: { type: 'string', default: 'us-west-2' },
                  nodeGroupSize: { type: 'integer', default: 3 },
                },
                required: ['clusterName'],
              },
            },
            resources: [],
          },
        },
      ];

      mockKubernetesClient.listResourceGraphDefinitions.mockResolvedValue(mockRGDs);

      const result = await service.discoverResourceGraphDefinitions('test-cluster');

      expect(result).toHaveLength(2);
      expect(result[0].name).toBe('cicd-pipeline');
      expect(result[0].kind).toBe('CICDPipeline');
      expect(result[0].schema.properties).toHaveProperty('name');
      expect(result[0].schema.properties).toHaveProperty('repository');
      expect(result[0].schema.required).toEqual(['name', 'repository']);

      expect(result[1].name).toBe('eks-cluster');
      expect(result[1].kind).toBe('EksCluster');
      expect(result[1].schema.properties).toHaveProperty('clusterName');
      expect(result[1].schema.properties).toHaveProperty('region');

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Discovered ResourceGraphDefinitions',
        expect.objectContaining({
          cluster: 'test-cluster',
          count: 2,
        })
      );
    });

    it('should handle empty ResourceGraphDefinition list', async () => {
      mockKubernetesClient.listResourceGraphDefinitions.mockResolvedValue([]);

      const result = await service.discoverResourceGraphDefinitions('test-cluster');

      expect(result).toHaveLength(0);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        'No ResourceGraphDefinitions found',
        expect.objectContaining({
          cluster: 'test-cluster',
        })
      );
    });

    it('should handle discovery errors', async () => {
      const error = new Error('Kubernetes API error');
      mockKubernetesClient.listResourceGraphDefinitions.mockRejectedValue(error);

      await expect(
        service.discoverResourceGraphDefinitions('test-cluster')
      ).rejects.toThrow('Failed to discover ResourceGraphDefinitions');

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Failed to discover ResourceGraphDefinitions'),
        expect.objectContaining({
          cluster: 'test-cluster',
          error: 'Kubernetes API error',
        })
      );
    });
  });

  describe('ResourceGroup Creation', () => {
    it('should create ResourceGroup successfully', async () => {
      const mockRGD = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'cicd-pipeline',
          namespace: 'default',
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'CICDPipeline',
            spec: {
              properties: {
                name: { type: 'string' },
                repository: { type: 'string' },
              },
              required: ['name', 'repository'],
            },
          },
          resources: [],
        },
      };

      const createdResourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'CICDPipeline',
        metadata: {
          name: 'my-app-pipeline',
          namespace: 'default',
          labels: {
            'kro.run/resource-graph-definition': 'cicd-pipeline',
          },
          annotations: {
            'kro.run/created-by': 'user:default/test-user',
          },
        },
        spec: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
        },
        status: {
          phase: 'Creating',
          conditions: [
            {
              type: 'Ready',
              status: 'False',
              reason: 'Creating',
              message: 'Creating ResourceGroup resources',
            },
          ],
        },
      };

      mockKubernetesClient.getResourceGraphDefinition.mockResolvedValue(mockRGD);
      mockKubernetesClient.createResourceGroup.mockResolvedValue(createdResourceGroup);

      const createRequest = {
        templateName: 'cicd-pipeline',
        name: 'my-app-pipeline',
        namespace: 'default',
        cluster: 'test-cluster',
        parameters: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
        },
      };

      const result = await service.createResourceGroup(mockUser, createRequest);

      expect(result.name).toBe('my-app-pipeline');
      expect(result.namespace).toBe('default');
      expect(result.status).toBe('Creating');
      expect(result.spec).toEqual({
        name: 'my-app',
        repository: 'https://github.com/example/my-app',
      });

      expect(mockKubernetesClient.createResourceGroup).toHaveBeenCalledWith(
        'test-cluster',
        expect.objectContaining({
          apiVersion: 'kro.run/v1alpha1',
          kind: 'CICDPipeline',
          metadata: expect.objectContaining({
            name: 'my-app-pipeline',
            namespace: 'default',
          }),
          spec: {
            name: 'my-app',
            repository: 'https://github.com/example/my-app',
          },
        })
      );

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.RESOURCE_GROUP_CREATED,
          user: expect.objectContaining({
            userEntityRef: 'user:default/test-user',
          }),
          resource: expect.objectContaining({
            name: 'my-app-pipeline',
            namespace: 'default',
          }),
          action: 'create',
          result: 'success',
        })
      );
    });

    it('should validate parameters against schema', async () => {
      const mockRGD = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'cicd-pipeline',
          namespace: 'default',
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'CICDPipeline',
            spec: {
              properties: {
                name: { type: 'string' },
                repository: { type: 'string' },
              },
              required: ['name', 'repository'],
            },
          },
          resources: [],
        },
      };

      mockKubernetesClient.getResourceGraphDefinition.mockResolvedValue(mockRGD);

      const createRequest = {
        templateName: 'cicd-pipeline',
        name: 'invalid-pipeline',
        namespace: 'default',
        cluster: 'test-cluster',
        parameters: {
          name: 'my-app',
          // Missing required 'repository' parameter
        },
      };

      await expect(
        service.createResourceGroup(mockUser, createRequest)
      ).rejects.toThrow('Parameter validation failed');

      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Parameter validation failed'),
        expect.objectContaining({
          missingRequired: ['repository'],
        })
      );
    });

    it('should handle creation errors', async () => {
      const mockRGD = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'cicd-pipeline',
          namespace: 'default',
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'CICDPipeline',
            spec: {
              properties: {
                name: { type: 'string' },
                repository: { type: 'string' },
              },
              required: ['name', 'repository'],
            },
          },
          resources: [],
        },
      };

      const error = new Error('Resource already exists');
      mockKubernetesClient.getResourceGraphDefinition.mockResolvedValue(mockRGD);
      mockKubernetesClient.createResourceGroup.mockRejectedValue(error);

      const createRequest = {
        templateName: 'cicd-pipeline',
        name: 'existing-pipeline',
        namespace: 'default',
        cluster: 'test-cluster',
        parameters: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
        },
      };

      await expect(
        service.createResourceGroup(mockUser, createRequest)
      ).rejects.toThrow('Failed to create ResourceGroup');

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.RESOURCE_GROUP_CREATION_FAILED,
          result: 'failure',
          error: 'Resource already exists',
        })
      );
    });
  });

  describe('ResourceGroup Management', () => {
    it('should get ResourceGroup details', async () => {
      const mockResourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'CICDPipeline',
        metadata: {
          name: 'my-app-pipeline',
          namespace: 'default',
          labels: {
            'kro.run/resource-graph-definition': 'cicd-pipeline',
          },
        },
        spec: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
        },
        status: {
          phase: 'Ready',
          conditions: [
            {
              type: 'Ready',
              status: 'True',
              reason: 'AllResourcesReady',
              message: 'All managed resources are ready',
            },
          ],
          managedResources: [
            {
              apiVersion: 'v1',
              kind: 'Namespace',
              name: 'my-app',
            },
            {
              apiVersion: 'apps/v1',
              kind: 'Deployment',
              name: 'my-app-deployment',
              namespace: 'my-app',
            },
          ],
        },
      };

      mockKubernetesClient.getResourceGroup.mockResolvedValue(mockResourceGroup);

      const result = await service.getResourceGroup(
        mockUser,
        'test-cluster',
        'default',
        'my-app-pipeline'
      );

      expect(result.name).toBe('my-app-pipeline');
      expect(result.namespace).toBe('default');
      expect(result.status).toBe('Ready');
      expect(result.managedResources).toHaveLength(2);
      expect(result.managedResources[0]).toEqual({
        apiVersion: 'v1',
        kind: 'Namespace',
        name: 'my-app',
      });

      expect(mockKubernetesClient.getResourceGroup).toHaveBeenCalledWith(
        'test-cluster',
        'default',
        'my-app-pipeline'
      );
    });

    it('should list ResourceGroups with filtering', async () => {
      const mockResourceGroups = [
        {
          apiVersion: 'kro.run/v1alpha1',
          kind: 'CICDPipeline',
          metadata: {
            name: 'app1-pipeline',
            namespace: 'default',
            labels: {
              'app.kubernetes.io/name': 'app1',
              'kro.run/resource-graph-definition': 'cicd-pipeline',
            },
          },
          spec: { name: 'app1' },
          status: { phase: 'Ready' },
        },
        {
          apiVersion: 'kro.run/v1alpha1',
          kind: 'EksCluster',
          metadata: {
            name: 'prod-cluster',
            namespace: 'infrastructure',
            labels: {
              'environment': 'production',
              'kro.run/resource-graph-definition': 'eks-cluster',
            },
          },
          spec: { clusterName: 'prod-cluster' },
          status: { phase: 'Ready' },
        },
      ];

      mockKubernetesClient.listResourceGroups.mockResolvedValue(mockResourceGroups);

      const result = await service.listResourceGroups(mockUser, 'test-cluster', {
        namespace: 'default',
        labelSelector: 'kro.run/resource-graph-definition=cicd-pipeline',
      });

      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('app1-pipeline');
      expect(result[0].namespace).toBe('default');

      expect(mockKubernetesClient.listResourceGroups).toHaveBeenCalledWith(
        'test-cluster',
        expect.objectContaining({
          namespace: 'default',
          labelSelector: 'kro.run/resource-graph-definition=cicd-pipeline',
        })
      );
    });

    it('should update ResourceGroup', async () => {
      const existingResourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'CICDPipeline',
        metadata: {
          name: 'my-app-pipeline',
          namespace: 'default',
          resourceVersion: '12345',
        },
        spec: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
          branch: 'main',
        },
      };

      const updatedResourceGroup = {
        ...existingResourceGroup,
        metadata: {
          ...existingResourceGroup.metadata,
          resourceVersion: '12346',
        },
        spec: {
          ...existingResourceGroup.spec,
          branch: 'develop',
        },
      };

      mockKubernetesClient.getResourceGroup.mockResolvedValue(existingResourceGroup);
      mockKubernetesClient.updateResourceGroup.mockResolvedValue(updatedResourceGroup);

      const updateRequest = {
        cluster: 'test-cluster',
        namespace: 'default',
        name: 'my-app-pipeline',
        spec: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
          branch: 'develop',
        },
      };

      const result = await service.updateResourceGroup(mockUser, updateRequest);

      expect(result.spec.branch).toBe('develop');

      expect(mockKubernetesClient.updateResourceGroup).toHaveBeenCalledWith(
        'test-cluster',
        expect.objectContaining({
          metadata: expect.objectContaining({
            resourceVersion: '12345',
          }),
          spec: expect.objectContaining({
            branch: 'develop',
          }),
        })
      );

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.RESOURCE_GROUP_UPDATED,
          action: 'update',
          result: 'success',
        })
      );
    });

    it('should delete ResourceGroup', async () => {
      mockKubernetesClient.deleteResourceGroup.mockResolvedValue({
        status: 'Success',
      });

      await service.deleteResourceGroup(
        mockUser,
        'test-cluster',
        'default',
        'my-app-pipeline'
      );

      expect(mockKubernetesClient.deleteResourceGroup).toHaveBeenCalledWith(
        'test-cluster',
        'default',
        'my-app-pipeline'
      );

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.RESOURCE_GROUP_DELETED,
          action: 'delete',
          result: 'success',
        })
      );
    });
  });

  describe('ResourceGroup Status Monitoring', () => {
    it('should watch ResourceGroup status changes', async () => {
      const statusUpdates = [
        {
          type: 'ADDED',
          object: {
            metadata: { name: 'test-rg', namespace: 'default' },
            status: { phase: 'Pending' },
          },
        },
        {
          type: 'MODIFIED',
          object: {
            metadata: { name: 'test-rg', namespace: 'default' },
            status: { phase: 'Ready' },
          },
        },
      ];

      const mockWatcher = {
        on: jest.fn(),
        close: jest.fn(),
      };

      mockKubernetesClient.watchResourceGroup.mockReturnValue(mockWatcher);

      const statusCallback = jest.fn();
      const watcher = service.watchResourceGroupStatus(
        'test-cluster',
        'default',
        'test-rg',
        statusCallback
      );

      // Simulate status updates
      const onCallback = mockWatcher.on.mock.calls.find(call => call[0] === 'data')[1];
      statusUpdates.forEach(update => onCallback(update));

      expect(statusCallback).toHaveBeenCalledTimes(2);
      expect(statusCallback).toHaveBeenNthCalledWith(1, {
        name: 'test-rg',
        namespace: 'default',
        phase: 'Pending',
        type: 'ADDED',
      });
      expect(statusCallback).toHaveBeenNthCalledWith(2, {
        name: 'test-rg',
        namespace: 'default',
        phase: 'Ready',
        type: 'MODIFIED',
      });

      watcher.close();
      expect(mockWatcher.close).toHaveBeenCalled();
    });

    it('should handle watch errors', async () => {
      const mockWatcher = {
        on: jest.fn(),
        close: jest.fn(),
      };

      mockKubernetesClient.watchResourceGroup.mockReturnValue(mockWatcher);

      const statusCallback = jest.fn();
      const errorCallback = jest.fn();

      service.watchResourceGroupStatus(
        'test-cluster',
        'default',
        'test-rg',
        statusCallback,
        errorCallback
      );

      // Simulate error
      const onErrorCallback = mockWatcher.on.mock.calls.find(call => call[0] === 'error')[1];
      const error = new Error('Watch connection lost');
      onErrorCallback(error);

      expect(errorCallback).toHaveBeenCalledWith(error);
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('ResourceGroup watch error'),
        expect.objectContaining({
          cluster: 'test-cluster',
          namespace: 'default',
          name: 'test-rg',
          error: 'Watch connection lost',
        })
      );
    });
  });

  describe('Permission Validation', () => {
    it('should validate user permissions before operations', async () => {
      const mockRBACValidator = {
        validateKubernetesPermissions: jest.fn().mockResolvedValue({
          allowed: true,
          reason: 'User has required permissions',
        }),
      };

      (service as any).rbacValidator = mockRBACValidator;

      const createRequest = {
        templateName: 'cicd-pipeline',
        name: 'test-pipeline',
        namespace: 'default',
        cluster: 'test-cluster',
        parameters: { name: 'test', repository: 'https://github.com/test/repo' },
      };

      // Mock successful creation
      mockKubernetesClient.getResourceGraphDefinition.mockResolvedValue({
        spec: {
          schema: {
            spec: {
              properties: { name: { type: 'string' }, repository: { type: 'string' } },
              required: ['name', 'repository'],
            },
          },
        },
      });
      mockKubernetesClient.createResourceGroup.mockResolvedValue({
        metadata: { name: 'test-pipeline', namespace: 'default' },
        status: { conditions: [] },
      });

      await service.createResourceGroup(mockUser, createRequest);

      expect(mockRBACValidator.validateKubernetesPermissions).toHaveBeenCalledWith(
        mockUser,
        'create',
        'kro.run/v1alpha1/cicd-pipelines',
        'default',
        'test-cluster'
      );
    });

    it('should deny operations for unauthorized users', async () => {
      const mockRBACValidator = {
        validateKubernetesPermissions: jest.fn().mockResolvedValue({
          allowed: false,
          reason: 'User does not have permission to create ResourceGroups',
        }),
      };

      (service as any).rbacValidator = mockRBACValidator;

      const createRequest = {
        templateName: 'cicd-pipeline',
        name: 'test-pipeline',
        namespace: 'default',
        cluster: 'test-cluster',
        parameters: { name: 'test', repository: 'https://github.com/test/repo' },
      };

      await expect(
        service.createResourceGroup(mockUser, createRequest)
      ).rejects.toThrow('Permission denied');

      expect(mockLogger.info).toHaveBeenCalledWith(
        'Kro audit event',
        expect.objectContaining({
          eventType: KroAuditEventType.PERMISSION_DENIED,
          result: 'failure',
          error: 'User does not have permission to create ResourceGroups',
        })
      );
    });
  });
});