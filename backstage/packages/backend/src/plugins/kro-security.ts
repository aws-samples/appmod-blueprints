import { createBackendModule } from '@backstage/backend-plugin-api';
import { coreServices } from '@backstage/backend-plugin-api';
import { KroRBACValidator } from './kro-permissions';
import { KroAuditLogger } from './kro-audit';
import { KroErrorHandler } from './kro-error-handler';

/**
 * Security configuration for Kro plugin
 */
export interface KroSecurityConfig {
  enablePermissions: boolean;
  enableAuditLogging: boolean;
  rbacValidation: {
    enabled: boolean;
    strictMode: boolean;
    cacheTimeout: number;
  };
  auditLogging: {
    enabled: boolean;
    logLevel: 'info' | 'warn' | 'error';
    includeSuccessEvents: boolean;
  };
  errorHandling: {
    enableDetailedErrors: boolean;
    includeStackTrace: boolean;
  };
}

/**
 * Kro security service that coordinates all security components
 */
export class KroSecurityService {
  private rbacValidator: KroRBACValidator;
  private auditLogger: KroAuditLogger;
  private errorHandler: KroErrorHandler;
  private config: KroSecurityConfig;

  constructor(
    private logger: any,
    config: KroSecurityConfig,
    kubernetesApi?: any
  ) {
    this.config = config;
    this.auditLogger = new KroAuditLogger(logger);
    this.rbacValidator = new KroRBACValidator(logger, kubernetesApi);
    this.errorHandler = new KroErrorHandler(logger, this.auditLogger);

    this.logger.info('Kro security service initialized', {
      enablePermissions: config.enablePermissions,
      enableAuditLogging: config.enableAuditLogging,
      rbacValidationEnabled: config.rbacValidation.enabled,
      component: 'kro-security'
    });
  }

  /**
   * Get RBAC validator instance
   */
  getRBACValidator(): KroRBACValidator {
    return this.rbacValidator;
  }

  /**
   * Get audit logger instance
   */
  getAuditLogger(): KroAuditLogger {
    return this.auditLogger;
  }

  /**
   * Get error handler instance
   */
  getErrorHandler(): KroErrorHandler {
    return this.errorHandler;
  }

  /**
   * Get security configuration
   */
  getConfig(): KroSecurityConfig {
    return this.config;
  }

  /**
   * Validate security configuration
   */
  validateConfiguration(): { valid: boolean; errors: string[] } {
    const errors: string[] = [];

    if (this.config.enablePermissions && !this.config.rbacValidation.enabled) {
      errors.push('RBAC validation must be enabled when permissions are enabled');
    }

    if (this.config.rbacValidation.cacheTimeout < 0) {
      errors.push('RBAC cache timeout must be non-negative');
    }

    if (!['info', 'warn', 'error'].includes(this.config.auditLogging.logLevel)) {
      errors.push('Invalid audit logging level');
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }
}

/**
 * Kro security backend module
 */
export const kroSecurityModule = createBackendModule({
  pluginId: 'kro',
  moduleId: 'security',
  register(reg) {
    reg.registerInit({
      deps: {
        config: coreServices.rootConfig,
        logger: coreServices.logger,
      },
      async init({ config, logger }) {
        logger.info('Initializing Kro security module');

        // Load security configuration
        const kroConfig = config.getOptionalConfig('kro');
        const securityConfig: KroSecurityConfig = {
          enablePermissions: kroConfig?.getOptionalBoolean('enablePermissions') ?? true,
          enableAuditLogging: kroConfig?.getOptionalBoolean('enableAuditLogging') ?? true,
          rbacValidation: {
            enabled: kroConfig?.getOptionalConfig('rbacValidation')?.getOptionalBoolean('enabled') ?? true,
            strictMode: kroConfig?.getOptionalConfig('rbacValidation')?.getOptionalBoolean('strictMode') ?? false,
            cacheTimeout: kroConfig?.getOptionalConfig('rbacValidation')?.getOptionalNumber('cacheTimeout') ?? 300,
          },
          auditLogging: {
            enabled: kroConfig?.getOptionalConfig('auditLogging')?.getOptionalBoolean('enabled') ?? true,
            logLevel: (kroConfig?.getOptionalConfig('auditLogging')?.getOptionalString('logLevel') as 'info' | 'warn' | 'error') ?? 'info',
            includeSuccessEvents: kroConfig?.getOptionalConfig('auditLogging')?.getOptionalBoolean('includeSuccessEvents') ?? true,
          },
          errorHandling: {
            enableDetailedErrors: kroConfig?.getOptionalConfig('errorHandling')?.getOptionalBoolean('enableDetailedErrors') ?? true,
            includeStackTrace: kroConfig?.getOptionalConfig('errorHandling')?.getOptionalBoolean('includeStackTrace') ?? false,
          },
        };

        // Create security service
        const securityService = new KroSecurityService(logger, securityConfig);

        // Validate configuration
        const validation = securityService.validateConfiguration();
        if (!validation.valid) {
          const errorMessage = `Invalid Kro security configuration: ${validation.errors.join(', ')}`;
          logger.error(errorMessage);
          throw new Error(errorMessage);
        }

        // Log security configuration
        logger.info('Kro security configuration loaded', {
          enablePermissions: securityConfig.enablePermissions,
          enableAuditLogging: securityConfig.enableAuditLogging,
          rbacValidationEnabled: securityConfig.rbacValidation.enabled,
          strictMode: securityConfig.rbacValidation.strictMode,
          auditLogLevel: securityConfig.auditLogging.logLevel,
          component: 'kro-security'
        });

        // Register security service (in a real implementation, this would be made available to other modules)
        logger.info('Kro security module initialized successfully');
      },
    });
  },
});