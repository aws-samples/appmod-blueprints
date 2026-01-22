import { BackstageIdentityResponse } from '@backstage/plugin-auth-node';
import { KroAuditLogger, KroAuditEventType } from './kro-audit';

/**
 * Enhanced error handler for Kro plugin with proper authorization error messages
 */
export class KroErrorHandler {
  constructor(
    private logger: any,
    private auditLogger: KroAuditLogger
  ) { }

  /**
   * Handle authentication errors with proper user messaging
   */
  handleAuthenticationError(
    error: Error,
    user: BackstageIdentityResponse,
    context: {
      cluster?: string;
      operation?: string;
      resource?: string;
      namespace?: string;
    }
  ): { message: string; userMessage: string; statusCode: number } {
    const { cluster, operation, resource, namespace } = context;

    // Log audit event
    this.auditLogger.logAuthenticationFailure(
      user,
      {
        type: resource || 'unknown',
        name: resource,
        namespace,
        cluster,
      },
      operation || 'unknown',
      error.message
    );

    // Enhanced error logging
    this.logger.error(`Kubernetes authentication failed for user ${user.identity.userEntityRef}`, {
      user: user.identity.userEntityRef,
      cluster,
      operation,
      resource,
      namespace,
      error: error.message,
      errorType: 'AUTHENTICATION_FAILED',
      component: 'kro-error-handler'
    });

    // User-friendly error messages
    let userMessage: string;
    if (error.message.includes('Unauthorized') || error.message.includes('401')) {
      userMessage = `Authentication failed when accessing Kubernetes cluster '${cluster}'. Your credentials may be invalid or expired. Please contact your platform administrator to verify your access.`;
    } else if (error.message.includes('token')) {
      userMessage = `Authentication token is invalid or expired for cluster '${cluster}'. Please refresh your session or contact your platform administrator.`;
    } else {
      userMessage = `Unable to authenticate with Kubernetes cluster '${cluster}'. Please verify your credentials and try again.`;
    }

    return {
      message: error.message,
      userMessage,
      statusCode: 401
    };
  }

  /**
   * Handle authorization errors with proper user messaging and RBAC guidance
   */
  handleAuthorizationError(
    error: Error,
    user: BackstageIdentityResponse,
    context: {
      cluster?: string;
      operation?: string;
      resource?: string;
      namespace?: string;
      requiredPermissions?: string[];
    }
  ): { message: string; userMessage: string; statusCode: number; guidance?: string } {
    const { cluster, operation, resource, namespace, requiredPermissions } = context;

    // Log audit event
    this.auditLogger.logAuthorizationFailure(
      user,
      {
        type: resource || 'unknown',
        name: resource,
        namespace,
        cluster,
      },
      operation || 'unknown',
      error.message
    );

    // Enhanced error logging
    this.logger.error(`Kubernetes authorization failed for user ${user.identity.userEntityRef}`, {
      user: user.identity.userEntityRef,
      cluster,
      operation,
      resource,
      namespace,
      requiredPermissions,
      error: error.message,
      errorType: 'AUTHORIZATION_FAILED',
      component: 'kro-error-handler'
    });

    // Generate user-friendly error message with RBAC guidance
    let userMessage: string;
    let guidance: string;

    if (error.message.includes('Forbidden') || error.message.includes('403')) {
      userMessage = `You don't have permission to ${operation} ${resource}${namespace ? ` in namespace '${namespace}'` : ''} on cluster '${cluster}'.`;

      if (requiredPermissions && requiredPermissions.length > 0) {
        guidance = `Required permissions: ${requiredPermissions.join(', ')}. Please contact your platform administrator to request these permissions.`;
      } else {
        guidance = `Please contact your platform administrator to request the necessary permissions for this operation.`;
      }
    } else {
      userMessage = `Access denied for ${operation} operation on ${resource}${namespace ? ` in namespace '${namespace}'` : ''}.`;
      guidance = `Please verify your permissions and contact your platform administrator if you believe you should have access.`;
    }

    return {
      message: error.message,
      userMessage,
      statusCode: 403,
      guidance
    };
  }

  /**
   * Handle ResourceGroup operation errors with context
   */
  handleResourceGroupError(
    error: Error,
    user: BackstageIdentityResponse,
    context: {
      resourceGroup: string;
      namespace?: string;
      cluster?: string;
      operation: string;
    }
  ): { message: string; userMessage: string; statusCode: number } {
    const { resourceGroup, namespace, cluster, operation } = context;

    // Log audit event
    this.auditLogger.logResourceGroupOperation(
      this.getAuditEventType(operation),
      user,
      {
        type: 'ResourceGroup',
        name: resourceGroup,
        namespace,
        cluster,
      },
      operation,
      'failure',
      {},
      error.message
    );

    // Enhanced error logging
    this.logger.error(`ResourceGroup operation failed`, {
      user: user.identity.userEntityRef,
      resourceGroup,
      namespace,
      cluster,
      operation,
      error: error.message,
      stack: error.stack,
      component: 'kro-error-handler'
    });

    // Generate user-friendly error message
    let userMessage: string;
    let statusCode: number = 500;

    if (error.message.includes('not found') || error.message.includes('404')) {
      userMessage = `ResourceGroup '${resourceGroup}' not found${namespace ? ` in namespace '${namespace}'` : ''}.`;
      statusCode = 404;
    } else if (error.message.includes('already exists') || error.message.includes('409')) {
      userMessage = `ResourceGroup '${resourceGroup}' already exists${namespace ? ` in namespace '${namespace}'` : ''}.`;
      statusCode = 409;
    } else if (error.message.includes('validation')) {
      userMessage = `ResourceGroup '${resourceGroup}' validation failed. Please check the resource specification.`;
      statusCode = 400;
    } else {
      userMessage = `Failed to ${operation} ResourceGroup '${resourceGroup}'. Please try again or contact support.`;
    }

    return {
      message: error.message,
      userMessage,
      statusCode
    };
  }

  /**
   * Map operation to audit event type
   */
  private getAuditEventType(operation: string): KroAuditEventType {
    switch (operation.toLowerCase()) {
      case 'create':
        return KroAuditEventType.RESOURCE_GROUP_CREATED;
      case 'update':
        return KroAuditEventType.RESOURCE_GROUP_UPDATED;
      case 'delete':
        return KroAuditEventType.RESOURCE_GROUP_DELETED;
      case 'view':
      case 'get':
        return KroAuditEventType.RESOURCE_GROUP_VIEWED;
      default:
        return KroAuditEventType.RESOURCE_GROUP_VIEWED;
    }
  }

  /**
   * Handle general Kubernetes connection errors
   */
  handleConnectionError(
    error: Error,
    context: {
      cluster?: string;
      operation?: string;
    }
  ): { message: string; userMessage: string; statusCode: number } {
    const { cluster, operation } = context;

    this.logger.error(`Kubernetes connection error`, {
      cluster,
      operation,
      error: error.message,
      errorType: 'CONNECTION_ERROR',
      component: 'kro-error-handler'
    });

    let userMessage: string;
    if (error.message.includes('ECONNREFUSED') || error.message.includes('ENOTFOUND')) {
      userMessage = `Unable to connect to Kubernetes cluster '${cluster}'. The cluster may be unavailable or there may be network connectivity issues.`;
    } else if (error.message.includes('timeout')) {
      userMessage = `Connection to Kubernetes cluster '${cluster}' timed out. Please try again later.`;
    } else {
      userMessage = `Connection error when accessing Kubernetes cluster '${cluster}'. Please try again or contact support.`;
    }

    return {
      message: error.message,
      userMessage,
      statusCode: 503
    };
  }
}