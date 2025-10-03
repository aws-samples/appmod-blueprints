import { Config } from '@backstage/config';
import { Entity } from '@backstage/catalog-model';
import {
  CatalogProcessor,
  CatalogProcessorEmit,
  LocationSpec,
  processingResult,
} from '@backstage/plugin-catalog-node';

export class KroResourceGroupProcessor implements CatalogProcessor {
  private kubernetesClient: any;

  constructor(
    private config: Config,
    private logger: any,
  ) {
    this.initializeKubernetesClient();
  }

  private initializeKubernetesClient() {
    // Initialize Kubernetes client based on configuration
    // This would be implemented with actual Kubernetes client
  }

  getProcessorName(): string {
    return 'KroResourceGroupProcessor';
  }

  async readLocation(
    location: LocationSpec,
    _optional: boolean,
    emit: CatalogProcessorEmit,
  ): Promise<boolean> {
    if (location.type === 'kro-resource-graph-definitions') {
      await this.processResourceGraphDefinitions(location.target, emit);
      return true;
    }

    if (location.type === 'kro-resource-groups') {
      await this.processResourceGroups(location.target, emit);
      return true;
    }

    return false;
  }

  private async processResourceGraphDefinitions(
    cluster: string,
    emit: CatalogProcessorEmit,
  ): Promise<void> {
    try {
      this.logger.info('Processing ResourceGraphDefinitions', { cluster });

      const rgds = await this.kubernetesClient.listResourceGraphDefinitions(cluster);

      for (const rgd of rgds) {
        try {
          const entity = this.transformResourceGraphDefinitionToEntity(rgd, cluster);
          if (entity) {
            emit(processingResult.entity({
              type: 'kro-resource-graph-definitions',
              target: cluster,
            }, entity));
          }
        } catch (error) {
          this.logger.warn('Skipping malformed ResourceGraphDefinition', {
            name: rgd.metadata?.name,
            namespace: rgd.metadata?.namespace,
            error: (error as Error).message,
          });
        }
      }
    } catch (error) {
      if ((error as Error).message.includes('Unauthorized')) {
        this.logger.error('Authentication failed for cluster', {
          cluster,
          errorType: 'AUTHENTICATION_FAILED',
          error: (error as Error).message,
        });
      } else {
        this.logger.error('Failed to fetch ResourceGraphDefinitions', {
          cluster,
          error: (error as Error).message,
        });
      }
    }
  }

  private async processResourceGroups(
    cluster: string,
    emit: CatalogProcessorEmit,
  ): Promise<void> {
    try {
      this.logger.info('Processing ResourceGroups', { cluster });

      const resourceGroups = await this.kubernetesClient.listResourceGroups(cluster);

      for (const rg of resourceGroups) {
        try {
          const entity = this.transformResourceGroupToEntity(rg, cluster);
          if (entity) {
            emit(processingResult.entity({
              type: 'kro-resource-groups',
              target: cluster,
            }, entity));
          }
        } catch (error) {
          this.logger.warn('Skipping malformed ResourceGroup', {
            name: rg.metadata?.name,
            namespace: rg.metadata?.namespace,
            error: (error as Error).message,
          });
        }
      }
    } catch (error) {
      this.logger.error('Failed to fetch ResourceGroups', {
        cluster,
        error: (error as Error).message,
      });
    }
  }

  private transformResourceGraphDefinitionToEntity(rgd: any, cluster: string): Entity | null {
    if (!rgd.metadata?.name) {
      throw new Error('ResourceGraphDefinition missing required name');
    }

    const name = rgd.metadata.name;
    const namespace = rgd.metadata.namespace || 'default';
    const labels = rgd.metadata.labels || {};
    const annotations = rgd.metadata.annotations || {};

    // Determine lifecycle from labels or default to production
    const lifecycle = labels['backstage.io/lifecycle'] || 'production';

    // Determine owner from annotations or default to platform-team
    const owner = annotations['backstage.io/owner'] || 'platform-team';

    const entity: Entity = {
      apiVersion: 'backstage.io/v1alpha1',
      kind: 'Component',
      metadata: {
        name,
        namespace,
        annotations: {
          'backstage.io/kubernetes-id': name,
          'kro.run/resource-graph-definition': name,
          'backstage.io/source-location': `kro:${cluster}/${namespace}/${name}`,
          ...annotations,
        },
        labels: {
          'backstage.io/kubernetes-cluster': cluster,
          'kro.run/version': 'v1alpha1',
          ...labels,
        },
        title: annotations['kro.run/display-name'] || name,
        description: annotations['kro.run/description'],
      },
      spec: {
        type: 'kro-resource-group',
        lifecycle,
        owner,
        system: annotations['backstage.io/system'],
      },
    };

    // Add status if available
    if (rgd.status) {
      (entity as any).status = {
        phase: this.extractPhase(rgd.status),
        conditions: rgd.status.conditions || [],
      };

      // Add status annotation for failed resources
      if ((entity as any).status.phase === 'Failed') {
        entity.metadata.annotations!['backstage.io/status'] = 'Failed';
      }
    }

    return entity;
  }

  private transformResourceGroupToEntity(rg: any, cluster: string): Entity | null {
    if (!rg.metadata?.name) {
      throw new Error('ResourceGroup missing required name');
    }

    const name = rg.metadata.name;
    const namespace = rg.metadata.namespace || 'default';
    const labels = rg.metadata.labels || {};
    const annotations = rg.metadata.annotations || {};

    // Determine lifecycle from labels or namespace
    let lifecycle = labels['backstage.io/lifecycle'] || 'production';
    if (namespace.startsWith('dev-') || namespace === 'development') {
      lifecycle = 'development';
    } else if (namespace.startsWith('staging') || namespace === 'staging') {
      lifecycle = 'staging';
    }

    // Determine owner from annotations
    const owner = annotations['backstage.io/owner'] ||
      annotations['kro.run/created-by'] ||
      'platform-team';

    const entity: Entity = {
      apiVersion: 'backstage.io/v1alpha1',
      kind: 'Component',
      metadata: {
        name,
        namespace,
        annotations: {
          'backstage.io/kubernetes-id': name,
          'kro.run/resource-group': name,
          'backstage.io/source-location': `kro:${cluster}/${namespace}/${name}`,
          ...annotations,
        },
        labels: {
          'backstage.io/kubernetes-cluster': cluster,
          'kro.run/version': 'v1alpha1',
          ...labels,
        },
        title: annotations['kro.run/display-name'] || name,
        description: annotations['kro.run/description'],
      },
      spec: {
        type: 'kro-resource-group',
        lifecycle,
        owner,
        system: annotations['backstage.io/system'],
      },
    };

    // Add relationships
    const relations = [];

    // Relationship to ResourceGraphDefinition
    const rgdName = labels['kro.run/resource-graph-definition'];
    if (rgdName) {
      relations.push({
        type: 'ownedBy',
        targetRef: `component:${namespace}/${rgdName}`,
      });
    }

    // Relationships to managed resources
    if (rg.status?.managedResources) {
      for (const resource of rg.status.managedResources) {
        const resourceNamespace = resource.namespace || namespace;
        relations.push({
          type: 'dependsOn',
          targetRef: `resource:${resourceNamespace}/${resource.name}`,
        });
      }
    }

    if (relations.length > 0) {
      entity.relations = relations;
    }

    // Add status if available
    if (rg.status) {
      (entity as any).status = {
        phase: this.extractPhase(rg.status),
        conditions: rg.status.conditions || [],
      };

      // Add status annotation for failed resources
      if ((entity as any).status.phase === 'Failed') {
        entity.metadata.annotations!['backstage.io/status'] = 'Failed';
      }
    }

    return entity;
  }

  private extractPhase(status: any): string {
    if (status.phase) {
      return status.phase;
    }

    // Determine phase from conditions
    const readyCondition = status.conditions?.find((c: any) => c.type === 'Ready');
    if (readyCondition) {
      if (readyCondition.status === 'True') {
        return 'Ready';
      } else if (readyCondition.reason === 'Failed' || readyCondition.status === 'False') {
        return 'Failed';
      } else {
        return 'Pending';
      }
    }

    return 'Unknown';
  }
}

// Helper function to create location for ResourceGraphDefinitions
export function createResourceGraphDefinitionLocation(cluster: string): LocationSpec {
  return {
    type: 'kro-resource-graph-definitions',
    target: cluster,
  };
}

// Helper function to create location for ResourceGroups
export function createResourceGroupLocation(cluster: string): LocationSpec {
  return {
    type: 'kro-resource-groups',
    target: cluster,
  };
}