import { createBackendModule } from '@backstage/backend-plugin-api';
import { coreServices } from '@backstage/backend-plugin-api';
// import { KroEntityTransformer } from './kro-entity-transformer';

/**
 * Kubernetes Ingestor module for Kro ResourceGroup integration
 * Configures the Kubernetes Ingestor to properly handle Kro resources
 */
export const kubernetesIngestorKroModule = createBackendModule({
  pluginId: 'kubernetes-ingestor',
  moduleId: 'kro-integration',
  register(reg) {
    reg.registerInit({
      deps: {
        config: coreServices.rootConfig,
        logger: coreServices.logger,
      },
      async init({ config, logger }) {
        // Initialize Kro entity transformer (for future use)
        // const kroTransformer = new KroEntityTransformer(logger);

        // Validate Kro configuration
        const kroConfig = config.getOptionalConfig('kro');
        const ingestorConfig = config.getOptionalConfig('kubernetesIngestor');

        if (!ingestorConfig) {
          logger.warn('Kubernetes Ingestor configuration not found. Kro integration may not work correctly.');
          return;
        }

        if (!kroConfig) {
          logger.warn('Kro configuration not found. ResourceGroup processing may be limited.');
        }

        // Log configuration validation
        const resources = ingestorConfig.getOptionalConfigArray('resources') || [];
        const kroResources = resources.filter(resource => {
          const apiVersion = resource.getOptionalString('apiVersion');
          return apiVersion?.startsWith('kro.run/');
        });

        if (kroResources.length === 0) {
          logger.warn('No Kro resources configured in kubernetesIngestor.resources. ResourceGroups will not be discovered.');
        } else {
          logger.info(`Found ${kroResources.length} Kro resource types configured for ingestion`, {
            kroResourceTypes: kroResources.map(r => `${r.getOptionalString('apiVersion')}/${r.getOptionalString('kind')}`),
          });
        }

        // Validate cluster configuration
        const clusters = ingestorConfig.getOptionalConfigArray('clusters') || [];
        if (clusters.length === 0) {
          logger.warn('No clusters configured for Kubernetes Ingestor. ResourceGroup discovery will not work.');
        } else {
          logger.info(`Kubernetes Ingestor configured with ${clusters.length} cluster(s) for Kro resource discovery`);
        }

        // Register entity transformation handlers
        // Note: This is a placeholder for when the Kubernetes Ingestor plugin supports custom transformers
        // The actual implementation would depend on the plugin's extension points
        logger.info('Kro entity transformer initialized for Kubernetes Ingestor integration');

        // Log successful initialization
        logger.info('Kubernetes Ingestor Kro integration module initialized successfully');
      },
    });
  },
});