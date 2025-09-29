import { Entity } from '@backstage/catalog-model';
import { Logger } from 'winston';

/**
 * Entity transformer for Kro ResourceGroups
 * Transforms Kubernetes ResourceGroup resources into Backstage catalog entities
 */
export class KroEntityTransformer {
  constructor(private readonly logger: Logger) { }

  /**
   * Transform a Kubernetes ResourceGroup into a Backstage catalog entity
   */
  transformResourceGroup(kubernetesResource: any, clusterName: string): Entity | null {
    try {
      const { metadata, spec, status } = kubernetesResource;

      if (!metadata?.name) {
        this.logger.warn('ResourceGroup missing required metadata.name, skipping transformation');
        return null;
      }

      // Create Backstage entity from ResourceGroup
      const entity: Entity = {
        apiVersion: 'backstage.io/v1alpha1',
        kind: 'Component',
        metadata: {
          name: this.sanitizeEntityName(metadata.name),
          namespace: metadata.namespace || 'default',
          title: metadata.name,
          description: this.generateDescription(kubernetesResource),
          annotations: {
            'backstage.io/kubernetes-id': `${clusterName}:${metadata.namespace || 'default'}:${metadata.name}`,
            'backstage.io/kubernetes-cluster': clusterName,
            'kro.run/resource-group': 'true',
            'kro.run/definition': JSON.stringify(kubernetesResource),
            'backstage.io/source-location': this.generateSourceLocation(metadata),
          },
          labels: {
            'backstage.io/kubernetes-cluster': clusterName,
            'kro.run/type': 'resource-group',
            'kro.run/version': kubernetesResource.apiVersion?.split('/')[1] || 'v1alpha1',
            ...this.extractLabels(metadata.labels),
          },
        },
        spec: {
          type: 'kro-resource-group',
          lifecycle: this.determineLifecycle(metadata.labels),
          owner: this.determineOwner(metadata.labels, metadata.annotations),
          system: this.determineSystem(metadata.labels, metadata.annotations),
        },
      };

      // Add status information if available
      if (status) {
        entity.status = {
          phase: status.phase || 'Unknown',
          conditions: status.conditions || [],
        };
      }

      this.logger.debug(`Transformed ResourceGroup ${metadata.name} into catalog entity`, {
        resourceGroup: metadata.name,
        namespace: metadata.namespace,
        cluster: clusterName,
      });

      return entity;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error(`Failed to transform ResourceGroup into catalog entity`, {
        error: errorMessage,
        resourceName: kubernetesResource?.metadata?.name,
        cluster: clusterName,
      });
      return null;
    }
  }

  /**
   * Transform a ResourceGraphDefinition into a Backstage catalog entity
   */
  transformResourceGraphDefinition(kubernetesResource: any, clusterName: string): Entity | null {
    try {
      const { metadata, spec } = kubernetesResource;

      if (!metadata?.name) {
        this.logger.warn('ResourceGraphDefinition missing required metadata.name, skipping transformation');
        return null;
      }

      // Create Backstage entity from ResourceGraphDefinition
      const entity: Entity = {
        apiVersion: 'backstage.io/v1alpha1',
        kind: 'Component',
        metadata: {
          name: this.sanitizeEntityName(`${metadata.name}-rgd`),
          namespace: metadata.namespace || 'default',
          title: `${metadata.name} Definition`,
          description: this.generateRGDDescription(kubernetesResource),
          annotations: {
            'backstage.io/kubernetes-id': `${clusterName}:${metadata.namespace || 'default'}:${metadata.name}`,
            'backstage.io/kubernetes-cluster': clusterName,
            'kro.run/resource-graph-definition': 'true',
            'kro.run/definition': JSON.stringify(kubernetesResource),
            'backstage.io/source-location': this.generateSourceLocation(metadata),
          },
          labels: {
            'backstage.io/kubernetes-cluster': clusterName,
            'kro.run/type': 'resource-graph-definition',
            'kro.run/version': kubernetesResource.apiVersion?.split('/')[1] || 'v1alpha1',
            ...this.extractLabels(metadata.labels),
          },
        },
        spec: {
          type: 'kro-resource-group',
          lifecycle: this.determineLifecycle(metadata.labels),
          owner: this.determineOwner(metadata.labels, metadata.annotations),
          system: this.determineSystem(metadata.labels, metadata.annotations),
        },
      };

      this.logger.debug(`Transformed ResourceGraphDefinition ${metadata.name} into catalog entity`, {
        resourceGraphDefinition: metadata.name,
        namespace: metadata.namespace,
        cluster: clusterName,
      });

      return entity;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error(`Failed to transform ResourceGraphDefinition into catalog entity`, {
        error: errorMessage,
        resourceName: kubernetesResource?.metadata?.name,
        cluster: clusterName,
      });
      return null;
    }
  }

  /**
   * Sanitize entity name to comply with Backstage naming requirements
   */
  private sanitizeEntityName(name: string): string {
    // Convert to lowercase and replace invalid characters with hyphens
    return name
      .toLowerCase()
      .replace(/[^a-z0-9\-_.]/g, '-')
      .replace(/^[-_.]+|[-_.]+$/g, '')
      .substring(0, 63); // Kubernetes name length limit
  }

  /**
   * Generate description for ResourceGroup entity
   */
  private generateDescription(resource: any): string {
    const kind = resource.spec?.schema?.kind || 'ResourceGroup';
    const namespace = resource.metadata?.namespace || 'default';

    return `Kro ${kind} in namespace ${namespace}. This ResourceGroup manages composite Kubernetes resources.`;
  }

  /**
   * Generate description for ResourceGraphDefinition entity
   */
  private generateRGDDescription(resource: any): string {
    const kind = resource.spec?.schema?.kind || 'Unknown';
    const namespace = resource.metadata?.namespace || 'default';

    return `Kro ResourceGraphDefinition for ${kind} in namespace ${namespace}. Defines the schema and resources for composite resource creation.`;
  }

  /**
   * Generate source location annotation
   */
  private generateSourceLocation(metadata: any): string {
    // Try to extract source location from annotations
    const sourceRepo = metadata.annotations?.['kro.run/source-repo'];
    const sourcePath = metadata.annotations?.['kro.run/source-path'];

    if (sourceRepo && sourcePath) {
      return `url:${sourceRepo}/tree/main/${sourcePath}`;
    }

    if (sourceRepo) {
      return `url:${sourceRepo}`;
    }

    // Default to Kro examples
    return 'url:https://github.com/awslabs/kro/tree/main/examples';
  }

  /**
   * Extract and sanitize labels
   */
  private extractLabels(labels: Record<string, string> = {}): Record<string, string> {
    const sanitizedLabels: Record<string, string> = {};

    for (const [key, value] of Object.entries(labels)) {
      // Only include labels that are safe for Backstage
      if (key.startsWith('app.kubernetes.io/') ||
        key.startsWith('kro.run/') ||
        key.startsWith('backstage.io/')) {
        sanitizedLabels[key] = value;
      }
    }

    return sanitizedLabels;
  }

  /**
   * Determine lifecycle from labels or default to production
   */
  private determineLifecycle(labels: Record<string, string> = {}): string {
    const lifecycle = labels['app.kubernetes.io/environment'] ||
      labels['kro.run/lifecycle'] ||
      labels['backstage.io/lifecycle'];

    if (lifecycle && ['experimental', 'production', 'deprecated'].includes(lifecycle)) {
      return lifecycle;
    }

    return 'production';
  }

  /**
   * Determine owner from labels/annotations or default to platform-team
   */
  private determineOwner(labels: Record<string, string> = {}, annotations: Record<string, string> = {}): string {
    return labels['app.kubernetes.io/managed-by'] ||
      labels['kro.run/owner'] ||
      annotations['kro.run/owner'] ||
      'platform-team';
  }

  /**
   * Determine system from labels/annotations
   */
  private determineSystem(labels: Record<string, string> = {}, annotations: Record<string, string> = {}): string | undefined {
    return labels['app.kubernetes.io/part-of'] ||
      labels['kro.run/system'] ||
      annotations['kro.run/system'] ||
      'platform-infrastructure';
  }
}