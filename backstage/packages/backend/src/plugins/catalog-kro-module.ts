import { createBackendModule } from '@backstage/backend-plugin-api';
import { catalogProcessingExtensionPoint } from '@backstage/plugin-catalog-node/alpha';
import { coreServices } from '@backstage/backend-plugin-api';
import { KroResourceGroupProcessor } from './catalog-processors/kro-resource-group-processor';

/**
 * Catalog module for Kro ResourceGroup integration
 * Registers the ResourceGroup processor and configures catalog rules
 */
export const catalogKroModule = createBackendModule({
  pluginId: 'catalog',
  moduleId: 'kro-resource-groups',
  register(reg) {
    reg.registerInit({
      deps: {
        catalog: catalogProcessingExtensionPoint,
        config: coreServices.rootConfig,
        logger: coreServices.logger,
      },
      async init({ catalog, config, logger }) {
        // Register the ResourceGroup processor
        catalog.addProcessor(
          new KroResourceGroupProcessor(config, logger),
        );

        logger.info('Kro ResourceGroup catalog processor registered successfully');
      },
    });
  },
});