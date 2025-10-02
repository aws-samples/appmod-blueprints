import { Entity } from '@backstage/catalog-model';
import { ConfigReader } from '@backstage/config';
import { KroResourceGroupProcessor } from '../catalog-processors/kro-resource-group-processor';

// Mock Kubernetes client
const mockKubernetesClient = {
  listResourceGraphDefinitions: jest.fn(),
  getResourceGroup: jest.fn(),
  listResourceGroups: jest.fn(),
};

// Mock logger
const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};

describe('Kro Catalog Integration Tests', () => {
  let processor: KroResourceGroupProcessor;
  let config: ConfigReader;

  beforeEach(() => {
    jest.clearAllMocks();

    config = new ConfigReader({
      kro: {
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

    processor = new KroResourceGroupProcessor(config, mockLogger);

    // Mock the Kubernetes client
    (processor as any).kubernetesClient = mockKubernetesClient;
  });

  describe('ResourceGraphDefinition Processing', () => {
    it('should process ResourceGraphDefinition and create catalog entity', async () => {
      const mockResourceGraphDefinition = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'cicd-pipeline',
          namespace: 'default',
          labels: {
            'app.kubernetes.io/name': 'cicd-pipeline',
            'app.kubernetes.io/version': 'v1.0.0',
          },
          annotations: {
            'kro.run/description': 'CI/CD Pipeline ResourceGroup template',
          },
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
            },
          },
          resources: [
            {
              id: 'pipeline-namespace',
              template: {
                apiVersion: 'v1',
                kind: 'Namespace',
                metadata: {
                  name: '{{ .spec.name }}',
                },
              },
            },
          ],
        },
        status: {
          conditions: [
            {
              type: 'Ready',
              status: 'True',
              reason: 'ResourceGraphDefinitionReady',
              message: 'ResourceGraphDefinition is ready',
            },
          ],
        },
      };

      mockKubernetesClient.listResourceGraphDefinitions.mockResolvedValue([
        mockResourceGraphDefinition,
      ]);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-graph-definitions',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);
      expect(mockEmit).toHaveBeenCalledTimes(1);

      // Verify the entity structure by calling the transform method directly
      const entity = (processor as any).transformResourceGraphDefinitionToEntity(
        mockResourceGraphDefinition,
        'test-cluster'
      );

      expect(entity.apiVersion).toBe('backstage.io/v1alpha1');
      expect(entity.kind).toBe('Component');
      expect(entity.metadata.name).toBe('cicd-pipeline');
      expect(entity.metadata.namespace).toBe('default');
      expect(entity.metadata.annotations).toMatchObject({
        'backstage.io/kubernetes-id': 'cicd-pipeline',
        'kro.run/resource-graph-definition': 'cicd-pipeline',
        'backstage.io/source-location': 'kro:test-cluster/default/cicd-pipeline',
      });
      expect(entity.spec).toMatchObject({
        type: 'kro-resource-group',
        lifecycle: 'production',
        owner: 'platform-team',
      });
    });

    it('should handle ResourceGraphDefinition with missing metadata', async () => {
      const mockResourceGraphDefinition = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'minimal-rg',
          namespace: 'default',
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'MinimalRG',
          },
          resources: [],
        },
      };

      mockKubernetesClient.listResourceGraphDefinitions.mockResolvedValue([
        mockResourceGraphDefinition,
      ]);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-graph-definitions',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);
      expect(mockEmit).toHaveBeenCalledTimes(1);

      // Verify the entity structure
      const entity = (processor as any).transformResourceGraphDefinitionToEntity(
        mockResourceGraphDefinition,
        'test-cluster'
      );

      expect(entity.metadata.name).toBe('minimal-rg');
      expect(entity.spec?.type).toBe('kro-resource-group');
      expect(entity.spec?.lifecycle).toBe('production'); // Default value
    });
  });

  describe('ResourceGroup Instance Processing', () => {
    it('should process ResourceGroup instances and create catalog entities', async () => {
      const mockResourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'CICDPipeline',
        metadata: {
          name: 'my-app-pipeline',
          namespace: 'default',
          labels: {
            'kro.run/resource-graph-definition': 'cicd-pipeline',
          },
          annotations: {
            'kro.run/created-by': 'user:default/developer',
          },
        },
        spec: {
          name: 'my-app',
          repository: 'https://github.com/example/my-app',
          branch: 'main',
        },
        status: {
          conditions: [
            {
              type: 'Ready',
              status: 'True',
              reason: 'ResourceGroupReady',
              message: 'All resources are ready',
            },
          ],
          topLevelResource: {
            apiVersion: 'v1',
            kind: 'Namespace',
            name: 'my-app',
          },
        },
      };

      mockKubernetesClient.listResourceGroups.mockResolvedValue([
        mockResourceGroup,
      ]);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-groups',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);
      expect(mockEmit).toHaveBeenCalledTimes(1);

      // Verify the entity structure
      const entity = (processor as any).transformResourceGroupToEntity(
        mockResourceGroup,
        'test-cluster'
      );

      expect(entity.apiVersion).toBe('backstage.io/v1alpha1');
      expect(entity.kind).toBe('Component');
      expect(entity.metadata.name).toBe('my-app-pipeline');
      expect(entity.metadata.annotations).toMatchObject({
        'backstage.io/kubernetes-id': 'my-app-pipeline',
        'kro.run/resource-group': 'my-app-pipeline',
        'kro.run/created-by': 'user:default/developer',
      });
      expect(entity.spec).toMatchObject({
        type: 'kro-resource-group',
        lifecycle: 'production',
      });
    });

    it('should create relationships between ResourceGroups and managed resources', async () => {
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
          conditions: [
            {
              type: 'Ready',
              status: 'True',
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

      mockKubernetesClient.listResourceGroups.mockResolvedValue([
        mockResourceGroup,
      ]);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-groups',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);

      // Verify the entity relationships
      const entity = (processor as any).transformResourceGroupToEntity(
        mockResourceGroup,
        'test-cluster'
      );

      expect(entity.relations).toEqual([
        {
          type: 'ownedBy',
          targetRef: 'component:default/cicd-pipeline', // ResourceGraphDefinition
        },
        {
          type: 'dependsOn',
          targetRef: 'resource:default/my-app', // Namespace
        },
        {
          type: 'dependsOn',
          targetRef: 'resource:my-app/my-app-deployment', // Deployment
        },
      ]);
    });
  });

  describe('Error Handling', () => {
    it('should handle Kubernetes API errors gracefully', async () => {
      const error = new Error('Kubernetes API error');
      mockKubernetesClient.listResourceGraphDefinitions.mockRejectedValue(error);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-graph-definitions',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);
      expect(mockEmit).not.toHaveBeenCalled();
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Failed to fetch ResourceGraphDefinitions'),
        expect.objectContaining({
          cluster: 'test-cluster',
          error: 'Kubernetes API error',
        })
      );
    });

    it('should handle malformed ResourceGraphDefinition', async () => {
      const malformedRGD = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          // Missing required name field
          namespace: 'default',
        },
        spec: {},
      };

      mockKubernetesClient.listResourceGraphDefinitions.mockResolvedValue([
        malformedRGD,
      ]);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-graph-definitions',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);
      expect(mockEmit).not.toHaveBeenCalled();
      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.stringContaining('Skipping malformed ResourceGraphDefinition'),
        expect.any(Object)
      );
    });

    it('should handle authentication errors', async () => {
      const authError = new Error('Unauthorized');
      mockKubernetesClient.listResourceGraphDefinitions.mockRejectedValue(authError);

      const mockEmit = jest.fn();
      const result = await processor.readLocation(
        {
          type: 'kro-resource-graph-definitions',
          target: 'test-cluster',
        },
        false,
        mockEmit,
      );

      expect(result).toBe(true);
      expect(mockEmit).not.toHaveBeenCalled();
      expect(mockLogger.error).toHaveBeenCalledWith(
        expect.stringContaining('Authentication failed'),
        expect.objectContaining({
          cluster: 'test-cluster',
          errorType: 'AUTHENTICATION_FAILED',
        })
      );
    });
  });

  describe('Entity Validation', () => {
    it('should validate entity structure', () => {
      const mockResourceGraphDefinition = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'test-rg',
          namespace: 'default',
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'TestRG',
          },
          resources: [],
        },
      };

      const entity = (processor as any).transformResourceGraphDefinitionToEntity(
        mockResourceGraphDefinition,
        'test-cluster'
      );

      // Validate required fields
      expect(entity.apiVersion).toBe('backstage.io/v1alpha1');
      expect(entity.kind).toBe('Component');
      expect(entity.metadata.name).toBe('test-rg');
      expect(entity.metadata.namespace).toBe('default');

      // Validate annotations
      expect(entity.metadata.annotations).toHaveProperty('backstage.io/kubernetes-id');
      expect(entity.metadata.annotations).toHaveProperty('kro.run/resource-graph-definition');
      expect(entity.metadata.annotations).toHaveProperty('backstage.io/source-location');

      // Validate labels
      expect(entity.metadata.labels).toHaveProperty('backstage.io/kubernetes-cluster');
      expect(entity.metadata.labels).toHaveProperty('kro.run/version');

      // Validate spec
      expect(entity.spec).toHaveProperty('type', 'kro-resource-group');
      expect(entity.spec).toHaveProperty('lifecycle');
      expect(entity.spec).toHaveProperty('owner');
    });

    it('should set appropriate lifecycle based on labels', () => {
      const mockResourceGraphDefinition = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'dev-rg',
          namespace: 'development',
          labels: {
            'backstage.io/lifecycle': 'development',
          },
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'DevRG',
          },
          resources: [],
        },
      };

      const entity = (processor as any).transformResourceGraphDefinitionToEntity(
        mockResourceGraphDefinition,
        'test-cluster'
      );

      expect(entity.spec?.lifecycle).toBe('development');
    });

    it('should set owner from annotations', () => {
      const mockResourceGraphDefinition = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'ResourceGraphDefinition',
        metadata: {
          name: 'owned-rg',
          namespace: 'default',
          annotations: {
            'backstage.io/owner': 'team:platform/infrastructure',
          },
        },
        spec: {
          schema: {
            apiVersion: 'kro.run/v1alpha1',
            kind: 'OwnedRG',
          },
          resources: [],
        },
      };

      const entity = (processor as any).transformResourceGraphDefinitionToEntity(
        mockResourceGraphDefinition,
        'test-cluster'
      );

      expect(entity.spec?.owner).toBe('team:platform/infrastructure');
    });
  });

  describe('Status Processing', () => {
    it('should include status information in entity', () => {
      const mockResourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'CICDPipeline',
        metadata: {
          name: 'status-test',
          namespace: 'default',
        },
        spec: {
          name: 'test-app',
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
            {
              type: 'Progressing',
              status: 'False',
              reason: 'Complete',
              message: 'ResourceGroup deployment complete',
            },
          ],
        },
      };

      const entity = (processor as any).transformResourceGroupToEntity(
        mockResourceGroup,
        'test-cluster'
      );

      expect(entity.status).toEqual({
        phase: 'Ready',
        conditions: [
          {
            type: 'Ready',
            status: 'True',
            reason: 'AllResourcesReady',
            message: 'All managed resources are ready',
          },
          {
            type: 'Progressing',
            status: 'False',
            reason: 'Complete',
            message: 'ResourceGroup deployment complete',
          },
        ],
      });
    });

    it('should handle ResourceGroup with failed status', () => {
      const mockResourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: 'CICDPipeline',
        metadata: {
          name: 'failed-rg',
          namespace: 'default',
        },
        spec: {
          name: 'failed-app',
        },
        status: {
          phase: 'Failed',
          conditions: [
            {
              type: 'Ready',
              status: 'False',
              reason: 'ResourceCreationFailed',
              message: 'Failed to create Deployment: insufficient resources',
            },
          ],
        },
      };

      const entity = (processor as any).transformResourceGroupToEntity(
        mockResourceGroup,
        'test-cluster'
      );

      expect(entity.status?.phase).toBe('Failed');
      expect(entity.metadata.annotations).toHaveProperty(
        'backstage.io/status',
        'Failed'
      );
    });
  });
});