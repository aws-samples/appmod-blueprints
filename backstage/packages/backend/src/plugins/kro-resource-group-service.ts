import { Config } from '@backstage/config';
import { KroErrorHandler } from './kro-error-handler';
import { KroAuditLogger, KroAuditEventType } from './kro-audit';

export interface ResourceGraphDefinitionInfo {
  name: string;
  kind: string;
  schema: {
    properties: Record<string, any>;
    required: string[];
  };
  description?: string;
}

export interface ResourceGroupCreateRequest {
  templateName: string;
  name: string;
  namespace: string;
  cluster: string;
  parameters: Record<string, any>;
}

export interface ResourceGroupUpdateRequest {
  cluster: string;
  namespace: string;
  name: string;
  spec: Record<string, any>;
}

export interface ResourceGroupInfo {
  name: string;
  namespace: string;
  kind: string;
  status: string;
  spec: Record<string, any>;
  managedResources?: Array<{
    apiVersion: string;
    kind: string;
    name: string;
    namespace?: string;
  }>;
}

export interface ResourceGroupListOptions {
  namespace?: string;
  labelSelector?: string;
  fieldSelector?: string;
}

export interface ResourceGroupStatusUpdate {
  name: string;
  namespace: string;
  phase: string;
  type: 'ADDED' | 'MODIFIED' | 'DELETED';
}

export interface ResourceGroupWatcher {
  close(): void;
}

export class KroResourceGroupService {
  private kubernetesClient: any;

  constructor(
    private logger: any,
    private errorHandler: KroErrorHandler,
    private auditLogger: KroAuditLogger,
  ) {
    // Initialize Kubernetes client
    this.initializeKubernetesClient();
  }

  private initializeKubernetesClient() {
    // This would be implemented with actual Kubernetes client initialization
    // For now, it's mocked in tests
  }

  async discoverResourceGraphDefinitions(cluster: string): Promise<ResourceGraphDefinitionInfo[]> {
    try {
      this.logger.info('Discovering ResourceGraphDefinitions', { cluster });

      const rgds = await this.kubernetesClient.listResourceGraphDefinitions(cluster);

      if (rgds.length === 0) {
        this.logger.warn('No ResourceGraphDefinitions found', { cluster });
        return [];
      }

      const definitions = rgds.map((rgd: any) => ({
        name: rgd.metadata.name,
        kind: rgd.spec.schema.kind,
        schema: {
          properties: rgd.spec.schema.spec?.properties || {},
          required: rgd.spec.schema.spec?.required || [],
        },
        description: rgd.metadata.annotations?.['kro.run/description'],
      }));

      this.logger.info('Discovered ResourceGraphDefinitions', {
        cluster,
        count: definitions.length,
      });

      return definitions;
    } catch (error) {
      const connectionError = this.errorHandler.handleConnectionError(error as Error, {
        cluster,
        operation: 'discover-resource-graph-definitions',
      });
      throw new Error(`Failed to discover ResourceGraphDefinitions: ${connectionError.message}`);
    }
  }

  async createResourceGroup(user: any, request: ResourceGroupCreateRequest): Promise<ResourceGroupInfo> {
    try {
      // Validate permissions first
      if (this.rbacValidator) {
        const permissionResult = await this.rbacValidator.validateKubernetesPermissions(
          user,
          'create',
          `kro.run/v1alpha1/${request.templateName.toLowerCase()}s`,
          request.namespace,
          request.cluster
        );

        if (!permissionResult.allowed) {
          this.auditLogger.logPermissionDenied(
            user,
            {
              type: 'ResourceGroup',
              name: request.name,
              namespace: request.namespace,
            },
            'create',
            permissionResult.reason
          );
          throw new Error('Permission denied: ' + permissionResult.reason);
        }
      }

      // Get ResourceGraphDefinition
      const rgd = await this.kubernetesClient.getResourceGraphDefinition(
        request.cluster,
        'default', // Assuming RGDs are in default namespace
        request.templateName
      );

      // Validate parameters
      this.validateParameters(request.parameters, rgd.spec.schema.spec);

      // Create ResourceGroup
      const resourceGroup = {
        apiVersion: 'kro.run/v1alpha1',
        kind: rgd.spec.schema.kind,
        metadata: {
          name: request.name,
          namespace: request.namespace,
          labels: {
            'kro.run/resource-graph-definition': request.templateName,
          },
          annotations: {
            'kro.run/created-by': user.identity.userEntityRef,
          },
        },
        spec: request.parameters,
      };

      const created = await this.kubernetesClient.createResourceGroup(request.cluster, resourceGroup);

      const result: ResourceGroupInfo = {
        name: created.metadata.name,
        namespace: created.metadata.namespace,
        kind: created.kind,
        status: this.extractStatus(created.status),
        spec: created.spec,
      };

      this.auditLogger.logResourceGroupOperation(
        KroAuditEventType.RESOURCE_GROUP_CREATED,
        user,
        {
          type: 'ResourceGroup',
          name: request.name,
          namespace: request.namespace,
          cluster: request.cluster,
        },
        'create',
        'success',
        { templateUsed: request.templateName }
      );

      return result;
    } catch (error) {
      this.auditLogger.logResourceGroupOperation(
        KroAuditEventType.RESOURCE_GROUP_CREATION_FAILED,
        user,
        {
          type: 'ResourceGroup',
          name: request.name,
          namespace: request.namespace,
          cluster: request.cluster,
        },
        'create',
        'failure',
        undefined,
        (error as Error).message
      );
      throw new Error(`Failed to create ResourceGroup: ${(error as Error).message}`);
    }
  }

  async getResourceGroup(_user: any, cluster: string, namespace: string, name: string): Promise<ResourceGroupInfo> {
    const resourceGroup = await this.kubernetesClient.getResourceGroup(cluster, namespace, name);

    return {
      name: resourceGroup.metadata.name,
      namespace: resourceGroup.metadata.namespace,
      kind: resourceGroup.kind,
      status: this.extractStatus(resourceGroup.status),
      spec: resourceGroup.spec,
      managedResources: resourceGroup.status?.managedResources || [],
    };
  }

  async listResourceGroups(_user: any, cluster: string, options: ResourceGroupListOptions = {}): Promise<ResourceGroupInfo[]> {
    const resourceGroups = await this.kubernetesClient.listResourceGroups(cluster, options);

    return resourceGroups
      .filter((rg: any) => {
        // Apply client-side filtering if needed
        if (options.namespace && rg.metadata.namespace !== options.namespace) {
          return false;
        }
        return true;
      })
      .map((rg: any) => ({
        name: rg.metadata.name,
        namespace: rg.metadata.namespace,
        kind: rg.kind,
        status: this.extractStatus(rg.status),
        spec: rg.spec,
      }));
  }

  async updateResourceGroup(user: any, request: ResourceGroupUpdateRequest): Promise<ResourceGroupInfo> {
    try {
      // Get existing ResourceGroup
      const existing = await this.kubernetesClient.getResourceGroup(
        request.cluster,
        request.namespace,
        request.name
      );

      // Update spec
      const updated = {
        ...existing,
        spec: request.spec,
      };

      const result = await this.kubernetesClient.updateResourceGroup(request.cluster, updated);

      this.auditLogger.logResourceGroupOperation(
        KroAuditEventType.RESOURCE_GROUP_UPDATED,
        user,
        {
          type: 'ResourceGroup',
          name: request.name,
          namespace: request.namespace,
          cluster: request.cluster,
        },
        'update',
        'success'
      );

      return {
        name: result.metadata.name,
        namespace: result.metadata.namespace,
        kind: result.kind,
        status: this.extractStatus(result.status),
        spec: result.spec,
      };
    } catch (error) {
      throw new Error(`Failed to update ResourceGroup: ${(error as Error).message}`);
    }
  }

  async deleteResourceGroup(user: any, cluster: string, namespace: string, name: string): Promise<void> {
    await this.kubernetesClient.deleteResourceGroup(cluster, namespace, name);

    this.auditLogger.logResourceGroupOperation(
      KroAuditEventType.RESOURCE_GROUP_DELETED,
      user,
      {
        type: 'ResourceGroup',
        name,
        namespace,
        cluster,
      },
      'delete',
      'success'
    );
  }

  watchResourceGroupStatus(
    cluster: string,
    namespace: string,
    name: string,
    callback: (update: ResourceGroupStatusUpdate) => void,
    errorCallback?: (error: Error) => void
  ): ResourceGroupWatcher {
    const watcher = this.kubernetesClient.watchResourceGroup(cluster, namespace, name);

    watcher.on('data', (event: any) => {
      callback({
        name: event.object.metadata.name,
        namespace: event.object.metadata.namespace,
        phase: this.extractStatus(event.object.status),
        type: event.type,
      });
    });

    watcher.on('error', (error: Error) => {
      this.logger.error('ResourceGroup watch error', {
        cluster,
        namespace,
        name,
        error: error.message,
      });
      if (errorCallback) {
        errorCallback(error);
      }
    });

    return {
      close: () => watcher.close(),
    };
  }

  private validateParameters(parameters: Record<string, any>, schema: any): void {
    const required = schema.required || [];
    const properties = schema.properties || {};

    // Check required parameters
    const missing = required.filter((field: string) => !(field in parameters));
    if (missing.length > 0) {
      this.logger.error('Parameter validation failed', {
        missingRequired: missing,
        provided: Object.keys(parameters),
      });
      throw new Error(`Parameter validation failed: missing required fields: ${missing.join(', ')}`);
    }

    // Validate parameter types (basic validation)
    for (const [key, value] of Object.entries(parameters)) {
      const propertySchema = properties[key];
      if (propertySchema && propertySchema.type) {
        const expectedType = propertySchema.type;
        const actualType = typeof value;

        if (expectedType === 'string' && actualType !== 'string') {
          throw new Error(`Parameter '${key}' must be a string`);
        }
        if (expectedType === 'number' && actualType !== 'number') {
          throw new Error(`Parameter '${key}' must be a number`);
        }
        if (expectedType === 'boolean' && actualType !== 'boolean') {
          throw new Error(`Parameter '${key}' must be a boolean`);
        }
      }
    }
  }

  private extractStatus(status: any): string {
    if (!status) return 'Unknown';
    if (status.phase) return status.phase;

    const readyCondition = status.conditions?.find((c: any) => c.type === 'Ready');
    if (readyCondition) {
      return readyCondition.status === 'True' ? 'Ready' : 'Pending';
    }

    return 'Unknown';
  }

  private rbacValidator: any; // This would be injected in real implementation
}