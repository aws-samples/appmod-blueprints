import { createBackendModule } from '@backstage/backend-plugin-api';
import { coreServices } from '@backstage/backend-plugin-api';

/**
 * Custom Kro backend module that provides enhanced error handling
 * and configuration for Kubernetes connection issues
 */
export const kroBackendModule = createBackendModule({
  pluginId: 'kro',
  moduleId: 'enhanced-error-handling',
  register(reg) {
    reg.registerInit({
      deps: {
        config: coreServices.rootConfig,
        logger: coreServices.logger,
      },
      async init({ config, logger }) {
        const kroConfig = config.getOptionalConfig('kro');

        if (!kroConfig) {
          logger.warn('Kro plugin configuration not found. Plugin may not function correctly.');
          return;
        }

        // Validate Kubernetes cluster configuration
        const clusters = kroConfig.getOptionalConfigArray('clusters') || [];

        if (clusters.length === 0) {
          logger.warn('No Kubernetes clusters configured for Kro plugin');
          return;
        }

        // Validate each cluster configuration
        for (const [index, clusterConfig] of clusters.entries()) {
          try {
            const clusterName = clusterConfig.getString('name');
            const clusterUrl = clusterConfig.getString('url');
            const authProvider = clusterConfig.getString('authProvider');

            logger.info(`Validating Kro cluster configuration: ${clusterName}`);

            // Validate required fields
            if (!clusterUrl) {
              throw new Error(`Cluster URL is required for cluster: ${clusterName}`);
            }

            if (!authProvider) {
              throw new Error(`Auth provider is required for cluster: ${clusterName}`);
            }

            // Validate service account token if using serviceAccount auth
            if (authProvider === 'serviceAccount') {
              const token = clusterConfig.getOptionalString('serviceAccountToken');
              if (!token) {
                logger.warn(`Service account token not configured for cluster: ${clusterName}. This may cause authentication failures.`);
              }
            }

            logger.info(`Kro cluster configuration validated successfully: ${clusterName}`);

          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error);
            logger.error(`Invalid Kro cluster configuration at index ${index}: ${errorMessage}`);
            throw new Error(`Kro plugin initialization failed due to invalid cluster configuration: ${errorMessage}`);
          }
        }

        // Log successful initialization
        logger.info(`Kro plugin initialized successfully with ${clusters.length} cluster(s)`);
      },
    });
  },
});

/**
 * Enhanced error logging utilities for Kro plugin operations
 */
export class KroErrorHandler {
  constructor(private logger: any) { }

  /**
   * Enhanced error logging for Kubernetes connection issues
   */
  logKubernetesError(error: Error, context: { cluster?: string; operation?: string }) {
    const { cluster, operation } = context;

    if (error.message.includes('ECONNREFUSED') || error.message.includes('ENOTFOUND')) {
      this.logger.error(`Kubernetes connection failed for cluster '${cluster}': Network connectivity issue. Please verify cluster URL and network access.`, {
        error: error.message,
        cluster,
        operation,
        errorType: 'CONNECTION_FAILED'
      });
    } else if (error.message.includes('Unauthorized') || error.message.includes('401')) {
      this.logger.error(`Kubernetes authentication failed for cluster '${cluster}': Invalid or expired credentials. Please verify service account token.`, {
        error: error.message,
        cluster,
        operation,
        errorType: 'AUTHENTICATION_FAILED'
      });
    } else if (error.message.includes('Forbidden') || error.message.includes('403')) {
      this.logger.error(`Kubernetes authorization failed for cluster '${cluster}': Insufficient permissions. Please verify RBAC configuration.`, {
        error: error.message,
        cluster,
        operation,
        errorType: 'AUTHORIZATION_FAILED'
      });
    } else if (error.message.includes('timeout')) {
      this.logger.error(`Kubernetes operation timed out for cluster '${cluster}': Request timeout. Please check cluster performance and network latency.`, {
        error: error.message,
        cluster,
        operation,
        errorType: 'TIMEOUT'
      });
    } else {
      this.logger.error(`Kubernetes operation failed for cluster '${cluster}': ${error.message}`, {
        error: error.message,
        stack: error.stack,
        cluster,
        operation,
        errorType: 'UNKNOWN'
      });
    }
  }

  /**
   * Log ResourceGroup operation errors with context
   */
  logResourceGroupError(error: Error, context: { resourceGroup?: string; namespace?: string; operation?: string }) {
    const { resourceGroup, namespace, operation } = context;

    this.logger.error(`ResourceGroup operation failed: ${operation}`, {
      error: error.message,
      stack: error.stack,
      resourceGroup,
      namespace,
      operation,
      component: 'kro-plugin'
    });
  }

  /**
   * Log successful operations for monitoring
   */
  logSuccess(message: string, context: Record<string, any> = {}) {
    this.logger.info(message, {
      ...context,
      component: 'kro-plugin'
    });
  }
}