import { createBackendModule } from '@backstage/backend-plugin-api';
import { coreServices } from '@backstage/backend-plugin-api';
import { BackstageIdentityResponse } from '@backstage/plugin-auth-node';

/**
 * Audit event types for ResourceGroup operations
 */
export enum KroAuditEventType {
  RESOURCE_GROUP_VIEWED = 'resourcegroup.viewed',
  RESOURCE_GROUP_CREATED = 'resourcegroup.created',
  RESOURCE_GROUP_UPDATED = 'resourcegroup.updated',
  RESOURCE_GROUP_DELETED = 'resourcegroup.deleted',
  RESOURCE_GROUP_TEMPLATE_EXECUTED = 'resourcegroup.template.executed',
  PERMISSION_DENIED = 'permission.denied',
  AUTHENTICATION_FAILED = 'authentication.failed',
  AUTHORIZATION_FAILED = 'authorization.failed',
}

/**
 * Audit event interface
 */
export interface KroAuditEvent {
  eventType: KroAuditEventType;
  timestamp: Date;
  user: {
    userEntityRef: string;
    type: string;
  };
  resource: {
    type: string;
    name: string;
    namespace?: string;
    cluster?: string;
  };
  action: string;
  result: 'success' | 'failure';
  details?: Record<string, any>;
  error?: string;
  clientInfo?: {
    userAgent?: string;
    ipAddress?: string;
  };
}

/**
 * Kro audit logger for ResourceGroup operations
 */
export class KroAuditLogger {
  constructor(private logger: any) { }

  /**
   * Log ResourceGroup operation audit event
   */
  logResourceGroupOperation(
    eventType: KroAuditEventType,
    user: BackstageIdentityResponse,
    resource: {
      type: string;
      name: string;
      namespace?: string;
      cluster?: string;
    },
    action: string,
    result: 'success' | 'failure',
    details?: Record<string, any>,
    error?: string
  ): void {
    const auditEvent: KroAuditEvent = {
      eventType,
      timestamp: new Date(),
      user: {
        userEntityRef: user.identity.userEntityRef,
        type: user.identity.type,
      },
      resource,
      action,
      result,
      details,
      error,
    };

    this.logger.info('Kro audit event', {
      ...auditEvent,
      component: 'kro-audit',
      audit: true,
    });
  }
}  /**
  
 * Log permission denied events
   */
logPermissionDenied(
  user: BackstageIdentityResponse,
  resource: {
  type: string;
  name?: string;
  namespace?: string;
  cluster?: string;
},
  action: string,
  reason ?: string
): void {
  this.logResourceGroupOperation(
    KroAuditEventType.PERMISSION_DENIED,
    user,
    {
      type: resource.type,
      name: resource.name || 'unknown',
      namespace: resource.namespace,
      cluster: resource.cluster,
    },
    action,
    'failure',
    { reason },
    reason
  );
}

/**
 * Log authentication failures
 */
logAuthenticationFailure(
  user: BackstageIdentityResponse,
  resource: {
  type: string;
  name?: string;
  namespace?: string;
  cluster?: string;
},
  action: string,
  error: string
): void {
  this.logResourceGroupOperation(
    KroAuditEventType.AUTHENTICATION_FAILED,
    user,
    {
      type: resource.type,
      name: resource.name || 'unknown',
      namespace: resource.namespace,
      cluster: resource.cluster,
    },
    action,
    'failure',
    {},
    error
  );
}

/**
 * Log authorization failures
 */
logAuthorizationFailure(
  user: BackstageIdentityResponse,
  resource: {
  type: string;
  name?: string;
  namespace?: string;
  cluster?: string;
},
  action: string,
  error: string
): void {
  this.logResourceGroupOperation(
    KroAuditEventType.AUTHORIZATION_FAILED,
    user,
    {
      type: resource.type,
      name: resource.name || 'unknown',
      namespace: resource.namespace,
      cluster: resource.cluster,
    },
    action,
    'failure',
    {},
    error
  );
}

/**
 * Log successful ResourceGroup operations
 */
logResourceGroupSuccess(
  eventType: KroAuditEventType,
  user: BackstageIdentityResponse,
  resource: {
  type: string;
  name: string;
  namespace?: string;
  cluster?: string;
},
  action: string,
  details ?: Record<string, any>
): void {
  this.logResourceGroupOperation(
    eventType,
    user,
    resource,
    action,
    'success',
    details
  );
}
}

/**
 * Kro audit backend module
 */
export const kroAuditModule = createBackendModule({
  pluginId: 'kro',
  moduleId: 'audit-logging',
  register(reg) {
    reg.registerInit({
      deps: {
        config: coreServices.rootConfig,
        logger: coreServices.logger,
      },
      async init({ config, logger }) {
        logger.info('Initializing Kro audit logging module');

        // Create audit logger instance
        const auditLogger = new KroAuditLogger(logger);

        // Register audit logger as a service (in a real implementation)
        // This would be made available to other parts of the application

        logger.info('Kro audit logging module initialized successfully');
      },
    });
  },
});