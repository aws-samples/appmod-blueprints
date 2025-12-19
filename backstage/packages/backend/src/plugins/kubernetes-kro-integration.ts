import { createBackendModule } from '@backstage/backend-plugin-api';
import { coreServices } from '@backstage/backend-plugin-api';

/**
 * Backend module that enhances the Kubernetes plugin to include
 * Kro ResourceGroups in resource discovery and filtering
 */
export const kubernetesKroIntegrationModule = createBackendModule({
  pluginId: 'kubernetes',
  moduleId: 'kro-integration',
  register(reg) {
    reg.registerInit({
      deps: {
        config: coreServices.rootConfig,
        logger: coreServices.logger,
      },
      async init({ config, logger }) {
        logger.info('Initializing Kubernetes-Kro integration module');

        // Get Kro configuration
        const kroConfig = config.getOptionalConfig('kro');
        const kubernetesConfig = config.getOptionalConfig('kubernetes');

        if (!kubernetesConfig) {
          logger.warn('Kubernetes configuration not found. Kro integration will be limited.');
          return;
        }

        // Enhance Kubernetes plugin with Kro resource types
        const clusterConfig = kubernetesConfig.getOptionalConfigArray('clusterLocatorMethods')
          ?.find(method => method.getString('type') === 'config')
          ?.getOptionalConfigArray('clusters')
          ?.find(() => true); // Get first cluster config
        
        const customResources = clusterConfig?.getOptionalConfigArray('customResources') || [];

        const kroResourceTypes = [
          {
            group: 'kro.run',
            apiVersion: 'v1alpha1',
            plural: 'resourcegraphdefinitions',
          },
          {
            group: 'kro.run',
            apiVersion: 'v1alpha1',
            plural: 'cicdpipelines',
          },
          {
            group: 'kro.run',
            apiVersion: 'v1alpha1',
            plural: 'eksclusters',
          },
          {
            group: 'kro.run',
            apiVersion: 'v1alpha1',
            plural: 'eksclusterwithvpcs',
          },
          {
            group: 'kro.run',
            apiVersion: 'v1alpha1',
            plural: 'vpcs',
          },
        ];

        logger.info(`Registered ${kroResourceTypes.length} Kro resource types for Kubernetes plugin discovery`, {
          resourceTypes: kroResourceTypes.map(rt => `${rt.group}/${rt.apiVersion}/${rt.plural}`),
        });

        // Log integration status
        if (kroConfig) {
          const integrationConfig = kroConfig.getOptionalConfig('integration');
          const showInKubernetesViews = integrationConfig?.getOptionalBoolean('showInKubernetesViews') ?? true;
          const enableRelationshipMapping = integrationConfig?.getOptionalBoolean('enableRelationshipMapping') ?? true;

          logger.info('Kro-Kubernetes integration configured', {
            showInKubernetesViews,
            enableRelationshipMapping,
          });
        }

        logger.info('Kubernetes-Kro integration module initialized successfully');
      },
    });
  },
});

/**
 * Resource relationship mapper for Kro ResourceGroups
 */
export class KroResourceRelationshipMapper {
  constructor(private logger: any) { }

  /**
   * Map relationships between ResourceGroups and their managed resources
   */
  mapResourceRelationships(resources: any[]): Map<string, string[]> {
    const relationships = new Map<string, string[]>();

    try {
      // Find ResourceGroups and their managed resources
      const resourceGroups = resources.filter(r =>
        r.metadata?.labels?.['kro.run/resource-type'] === 'ResourceGroup' ||
        r.kind === 'ResourceGraphDefinition'
      );

      resourceGroups.forEach(rg => {
        const rgKey = `${rg.metadata.namespace}/${rg.metadata.name}`;
        const managedResources: string[] = [];

        // Extract managed resources from ResourceGroup spec
        if (rg.spec?.resources) {
          rg.spec.resources.forEach((resource: any) => {
            if (resource.template?.metadata?.name) {
              const resourceKey = `${resource.template.metadata.namespace || rg.metadata.namespace}/${resource.template.metadata.name}`;
              managedResources.push(resourceKey);
            }
          });
        }

        // Look for resources with Kro annotations
        resources.forEach(resource => {
          const kroResourceGroup = resource.metadata?.annotations?.['kro.run/resource-group'];
          if (kroResourceGroup === rg.metadata.name) {
            const resourceKey = `${resource.metadata.namespace}/${resource.metadata.name}`;
            managedResources.push(resourceKey);
          }
        });

        if (managedResources.length > 0) {
          relationships.set(rgKey, managedResources);
          this.logger.debug(`Mapped ResourceGroup ${rgKey} to ${managedResources.length} managed resources`);
        }
      });

      this.logger.info(`Mapped relationships for ${relationships.size} ResourceGroups`);
      return relationships;

    } catch (error) {
      this.logger.error('Failed to map Kro resource relationships', { error: (error as Error).message });
      return new Map();
    }
  }

  /**
   * Enhance resource objects with relationship metadata
   */
  enhanceResourcesWithRelationships(resources: any[], relationships: Map<string, string[]>): any[] {
    return resources.map(resource => {
      const resourceKey = `${resource.metadata.namespace}/${resource.metadata.name}`;

      // Add managed resources annotation for ResourceGroups
      const managedResources = relationships.get(resourceKey);
      if (managedResources && managedResources.length > 0) {
        resource.metadata.annotations = {
          ...resource.metadata.annotations,
          'kro.run/managed-resources': JSON.stringify(
            managedResources.map(mr => {
              const [namespace, name] = mr.split('/');
              return { namespace, name };
            })
          ),
        };
      }

      // Add ResourceGroup reference for managed resources
      for (const [rgKey, managed] of relationships.entries()) {
        if (managed.includes(resourceKey)) {
          const [rgNamespace, rgName] = rgKey.split('/');
          resource.metadata.annotations = {
            ...resource.metadata.annotations,
            'kro.run/resource-group': rgName,
            'kro.run/resource-group-namespace': rgNamespace,
          };
          break;
        }
      }

      return resource;
    });
  }
}

/**
 * Kro resource filter for Kubernetes plugin
 */
export class KroResourceFilter {
  private kroResourceTypes = new Set([
    'kro.run/v1alpha1/ResourceGraphDefinition',
    'kro.run/v1alpha1/CICDPipeline',
    'kro.run/v1alpha1/EksCluster',
    'kro.run/v1alpha1/EksclusterWithVpc',
    'kro.run/v1alpha1/Vpc',
  ]);

  /**
   * Check if a resource is a Kro resource
   */
  isKroResource(resource: any): boolean {
    const resourceType = `${resource.apiVersion}/${resource.kind}`;
    return this.kroResourceTypes.has(resourceType) ||
      Boolean(resource.metadata?.labels?.['kro.run/resource-type']);
  }

  /**
   * Filter resources to include/exclude Kro resources based on configuration
   */
  filterResources(resources: any[], includeKroResources: boolean = true): any[] {
    if (includeKroResources) {
      return resources; // Include all resources
    }

    return resources.filter(resource => !this.isKroResource(resource));
  }

  /**
   * Get available resource types including Kro resources
   */
  getAvailableResourceTypes(resources: any[]): string[] {
    const types = new Set<string>();

    resources.forEach(resource => {
      const resourceType = `${resource.apiVersion}/${resource.kind}`;
      types.add(resourceType);
    });

    return Array.from(types).sort((a, b) => {
      // Sort Kro resources first
      const aIsKro = this.kroResourceTypes.has(a);
      const bIsKro = this.kroResourceTypes.has(b);

      if (aIsKro && !bIsKro) return -1;
      if (!aIsKro && bIsKro) return 1;
      return a.localeCompare(b);
    });
  }
}

export default kubernetesKroIntegrationModule;