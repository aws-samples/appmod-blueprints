import {
  CatalogProcessor,
  CatalogProcessorEmit,
  processingResult,
} from '@backstage/plugin-catalog-node';
import { LocationSpec } from '@backstage/plugin-catalog-common';
import { Entity } from '@backstage/catalog-model';
import { Config } from '@backstage/config';
import { Logger } from 'winston';

/**
 * Catalog processor for Kro ResourceGroup entities
 * Processes ResourceGroups discovered by the Kubernetes Ingestor
 * and transforms them into Backstage catalog entities
 */
export class KroResourceGroupProcessor implements CatalogProcessor {
  constructor(
    private readonly config: Config,
    private readonly logger: Logger,
  ) { }

  getProcessorName(): string {
    return 'KroResourceGroupProcessor';
  }

  async validateEntityKind(entity: Entity): Promise<boolean> {
    return (
      entity.apiVersion === 'backstage.io/v1alpha1' &&
      entity.kind === 'Component' &&
      entity.spec?.type === 'kro-resource-group'
    );
  }

  async preProcessEntity(
    entity: Entity,
    location: LocationSpec,
    emit: CatalogProcessorEmit,
  ): Promise<Entity> {
    // Only process Kro ResourceGroup entities
    if (!await this.validateEntityKind(entity)) {
      return entity;
    }

    try {
      // Enhance entity with ResourceGroup-specific metadata
      const enhancedEntity = await this.enhanceResourceGroupEntity(entity);

      // Emit relationships for ResourceGroup dependencies
      await this.emitResourceGroupRelationships(enhancedEntity, emit);

      this.logger.info(`Processed ResourceGroup entity: ${entity.metadata.name}`, {
        processor: 'KroResourceGroupProcessor',
        entityName: entity.metadata.name,
        namespace: entity.metadata.namespace,
      });

      return enhancedEntity;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error(`Failed to process ResourceGroup entity: ${entity.metadata.name}`, {
        processor: 'KroResourceGroupProcessor',
        error: errorMessage,
        entityName: entity.metadata.name,
      });

      // Return original entity if processing fails
      return entity;
    }
  }

  /**
   * Enhance ResourceGroup entity with additional metadata and annotations
   */
  private async enhanceResourceGroupEntity(entity: Entity): Promise<Entity> {
    const enhanced = { ...entity };

    // Ensure proper annotations for ResourceGroups
    if (!enhanced.metadata.annotations) {
      enhanced.metadata.annotations = {};
    }

    // Add ResourceGroup-specific annotations
    if (!enhanced.metadata.annotations['kro.run/resource-group']) {
      enhanced.metadata.annotations['kro.run/resource-group'] = 'true';
    }

    // Add Kubernetes cluster information if available
    const kubernetesId = enhanced.metadata.annotations['backstage.io/kubernetes-id'];
    if (kubernetesId && !enhanced.metadata.annotations['backstage.io/kubernetes-cluster']) {
      // Extract cluster name from kubernetes-id or use default
      const clusterName = this.extractClusterName(kubernetesId);
      enhanced.metadata.annotations['backstage.io/kubernetes-cluster'] = clusterName;
    }

    // Ensure proper labels
    if (!enhanced.metadata.labels) {
      enhanced.metadata.labels = {};
    }

    // Add ResourceGroup type label
    enhanced.metadata.labels['kro.run/type'] = 'resource-group';

    // Add lifecycle label if not present
    if (!enhanced.spec?.lifecycle) {
      if (!enhanced.spec) enhanced.spec = {};
      enhanced.spec.lifecycle = 'production';
    }

    // Ensure owner is set
    if (!enhanced.spec?.owner) {
      if (!enhanced.spec) enhanced.spec = {};
      enhanced.spec.owner = 'platform-team';
    }

    return enhanced;
  }

  /**
   * Emit relationships for ResourceGroup entities
   */
  private async emitResourceGroupRelationships(
    entity: Entity,
    emit: CatalogProcessorEmit,
  ): Promise<void> {
    try {
      // Extract ResourceGroup definition from annotations
      const resourceGroupData = entity.metadata.annotations?.['kro.run/definition'];

      if (resourceGroupData) {
        const definition = JSON.parse(resourceGroupData);

        // Emit relationships for managed resources
        if (definition.spec?.resources) {
          for (const resource of definition.spec.resources) {
            if (resource.template?.metadata?.name) {
              emit(
                processingResult.relation({
                  source: {
                    kind: entity.kind,
                    namespace: entity.metadata.namespace || 'default',
                    name: entity.metadata.name,
                  },
                  target: {
                    kind: resource.template.kind || 'Component',
                    namespace: resource.template.metadata.namespace || entity.metadata.namespace || 'default',
                    name: resource.template.metadata.name,
                  },
                  type: 'ownedBy',
                }),
              );
            }
          }
        }

        // Emit system relationship if specified
        if (entity.spec?.system) {
          emit(
            processingResult.relation({
              source: {
                kind: entity.kind,
                namespace: entity.metadata.namespace || 'default',
                name: entity.metadata.name,
              },
              target: {
                kind: 'System',
                namespace: entity.metadata.namespace || 'default',
                name: entity.spec.system,
              },
              type: 'partOf',
            }),
          );
        }
      }
    } catch (error) {
      this.logger.warn(`Failed to emit relationships for ResourceGroup: ${entity.metadata.name}`, {
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  /**
   * Extract cluster name from kubernetes-id annotation
   */
  private extractClusterName(kubernetesId: string): string {
    // Try to extract cluster name from kubernetes-id format
    // Expected format: cluster-name:namespace:resource-name
    const parts = kubernetesId.split(':');
    if (parts.length >= 1) {
      return parts[0];
    }

    // Fallback to default cluster name from config
    const kroConfig = this.config.getOptionalConfig('kro');
    const clusters = kroConfig?.getOptionalConfigArray('clusters') || [];

    if (clusters.length > 0) {
      return clusters[0].getString('name');
    }

    return 'default';
  }
}