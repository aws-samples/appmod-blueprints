import { createBackendModule } from '@backstage/backend-plugin-api';
import { coreServices } from '@backstage/backend-plugin-api';
import { AuthorizeResult, PolicyDecision } from '@backstage/plugin-permission-common';
import { PermissionPolicy, PolicyQuery } from '@backstage/plugin-permission-node';
import { BackstageIdentityResponse } from '@backstage/plugin-auth-node';

/**
 * Kro-specific permissions for ResourceGroup operations
 */
export const kroPermissions = {
  kroResourceGroupRead: {
    name: 'kro.resourcegroup.read',
    attributes: {
      action: 'read',
      resourceType: 'kro-resource-group',
    },
  },
  kroResourceGroupCreate: {
    name: 'kro.resourcegroup.create',
    attributes: {
      action: 'create',
      resourceType: 'kro-resource-group',
    },
  },
  kroResourceGroupUpdate: {
    name: 'kro.resourcegroup.update',
    attributes: {
      action: 'update',
      resourceType: 'kro-resource-group',
    },
  },
  kroResourceGroupDelete: {
    name: 'kro.resourcegroup.delete',
    attributes: {
      action: 'delete',
      resourceType: 'kro-resource-group',
    },
  },
};

/**
 * Kubernetes RBAC validator for Kro operations
 */
export class KroRBACValidator {
  constructor(
    private logger: any,
    private kubernetesApi: any
  ) { }

  /**
   * Validate user permissions against Kubernetes RBAC for Kro operations
   */
  async validateKubernetesPermissions(
    user: BackstageIdentityResponse,
    action: string,
    resource: string,
    namespace?: string,
    cluster?: string
  ): Promise<{ allowed: boolean; reason?: string }> {
    try {
      this.logger.info(`Validating Kubernetes RBAC permissions for user: ${user.identity.userEntityRef}`, {
        user: user.identity.userEntityRef,
        action,
        resource,
        namespace,
        cluster,
        component: 'kro-permissions'
      });

      // For service account authentication, we assume the service account has proper permissions
      // In a real implementation, you would check the user's Kubernetes permissions
      if (user.identity.type === 'service') {
        return { allowed: true };
      }

      // Simulate RBAC check - in a real implementation, this would call Kubernetes API
      // to check if the user has the required permissions
      const hasPermission = await this.checkKubernetesRBAC(
        user.identity.userEntityRef,
        action,
        resource,
        namespace,
        cluster
      );

      if (!hasPermission) {
        const reason = `User ${user.identity.userEntityRef} does not have permission to ${action} ${resource}${namespace ? ` in namespace ${namespace}` : ''}${cluster ? ` on cluster ${cluster}` : ''}`;

        this.logger.warn(`Kubernetes RBAC validation failed`, {
          user: user.identity.userEntityRef,
          action,
          resource,
          namespace,
          cluster,
          reason,
          component: 'kro-permissions'
        });

        return { allowed: false, reason };
      }

      this.logger.info(`Kubernetes RBAC validation successful`, {
        user: user.identity.userEntityRef,
        action,
        resource,
        namespace,
        cluster,
        component: 'kro-permissions'
      });

      return { allowed: true };

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);

      this.logger.error(`Error validating Kubernetes RBAC permissions`, {
        user: user.identity.userEntityRef,
        action,
        resource,
        namespace,
        cluster,
        error: errorMessage,
        component: 'kro-permissions'
      });

      return {
        allowed: false,
        reason: `Permission validation failed: ${errorMessage}`
      };
    }
  }

  /**
   * Check Kubernetes RBAC permissions using SubjectAccessReview
   */
  private async checkKubernetesRBAC(
    userRef: string,
    action: string,
    resource: string,
    namespace?: string,
    cluster?: string
  ): Promise<boolean> {
    try {
      // In a real implementation, this would create a SubjectAccessReview
      // to check if the user has the required permissions

      // For now, we'll implement a basic permission check based on user groups
      // This should be replaced with actual Kubernetes RBAC checks

      // Extract user information from userRef (format: user:default/username)
      const userParts = userRef.split('/');
      const username = userParts[userParts.length - 1];

      // Define permission mappings (this would typically come from Kubernetes RBAC)
      const permissionMappings = {
        'kro.run/v1alpha1/resourcegraphdefinitions': {
          'get': ['kro-readers', 'kro-admins', 'platform-engineers'],
          'list': ['kro-readers', 'kro-admins', 'platform-engineers'],
          'create': ['kro-admins', 'platform-engineers'],
          'update': ['kro-admins', 'platform-engineers'],
          'delete': ['kro-admins', 'platform-engineers'],
        },
        'kro.run/v1alpha1/cicdpipelines': {
          'get': ['kro-readers', 'kro-admins', 'developers'],
          'list': ['kro-readers', 'kro-admins', 'developers'],
          'create': ['kro-admins', 'developers'],
          'update': ['kro-admins', 'developers'],
          'delete': ['kro-admins'],
        },
        'kro.run/v1alpha1/eksclusters': {
          'get': ['kro-readers', 'kro-admins', 'platform-engineers'],
          'list': ['kro-readers', 'kro-admins', 'platform-engineers'],
          'create': ['kro-admins', 'platform-engineers'],
          'update': ['kro-admins', 'platform-engineers'],
          'delete': ['kro-admins', 'platform-engineers'],
        },
      };

      // Get user groups (this would typically come from identity provider)
      const userGroups = await this.getUserGroups(username);

      // Check if user has required permissions
      const resourcePermissions = permissionMappings[resource];
      if (!resourcePermissions) {
        // If resource is not in our mapping, deny by default
        return false;
      }

      const allowedGroups = resourcePermissions[action];
      if (!allowedGroups) {
        // If action is not defined, deny by default
        return false;
      }

      // Check if user belongs to any of the allowed groups
      const hasPermission = userGroups.some(group => allowedGroups.includes(group));

      return hasPermission;

    } catch (error) {
      this.logger.error(`Error checking Kubernetes RBAC`, {
        userRef,
        action,
        resource,
        namespace,
        cluster,
        error: error instanceof Error ? error.message : String(error),
        component: 'kro-permissions'
      });
      return false;
    }
  }

  /**
   * Get user groups from identity provider
   */
  private async getUserGroups(username: string): Promise<string[]> {
    // In a real implementation, this would fetch user groups from the identity provider
    // For now, we'll return some default groups based on username patterns

    if (username.includes('admin')) {
      return ['kro-admins', 'platform-engineers'];
    } else if (username.includes('engineer')) {
      return ['platform-engineers', 'kro-readers'];
    } else if (username.includes('dev')) {
      return ['developers', 'kro-readers'];
    } else {
      return ['kro-readers'];
    }
  }
}

/**
 * Kro permission policy that integrates with Kubernetes RBAC
 */
export class KroPermissionPolicy implements PermissionPolicy {
  constructor(
    private rbacValidator: KroRBACValidator,
    private logger: any
  ) { }

  async handle(request: PolicyQuery, user?: BackstageIdentityResponse): Promise<PolicyDecision> {
    try {
      // Check if this is a Kro-related permission
      if (!request.permission.name.startsWith('kro.')) {
        return { result: AuthorizeResult.ALLOW };
      }

      if (!user) {
        this.logger.warn(`Permission denied: No user context provided for ${request.permission.name}`);
        return { result: AuthorizeResult.DENY };
      }

      // Extract action and resource from permission
      const permissionParts = request.permission.name.split('.');
      const action = permissionParts[permissionParts.length - 1]; // read, create, update, delete
      const resourceType = permissionParts[1]; // resourcegroup

      // Map to Kubernetes resource
      let kubernetesResource: string;
      switch (resourceType) {
        case 'resourcegroup':
          kubernetesResource = 'kro.run/v1alpha1/resourcegraphdefinitions';
          break;
        default:
          kubernetesResource = `kro.run/v1alpha1/${resourceType}s`;
      }

      // Map Backstage actions to Kubernetes verbs
      let kubernetesVerb: string;
      switch (action) {
        case 'read':
          kubernetesVerb = 'get';
          break;
        case 'create':
          kubernetesVerb = 'create';
          break;
        case 'update':
          kubernetesVerb = 'update';
          break;
        case 'delete':
          kubernetesVerb = 'delete';
          break;
        default:
          kubernetesVerb = action;
      }

      // Validate permissions against Kubernetes RBAC
      const validation = await this.rbacValidator.validateKubernetesPermissions(
        user,
        kubernetesVerb,
        kubernetesResource,
        request.resourceRef?.namespace,
        request.resourceRef?.cluster
      );

      if (validation.allowed) {
        this.logger.info(`Permission granted for ${request.permission.name}`, {
          user: user.identity.userEntityRef,
          permission: request.permission.name,
          component: 'kro-permissions'
        });
        return { result: AuthorizeResult.ALLOW };
      } else {
        this.logger.warn(`Permission denied for ${request.permission.name}`, {
          user: user.identity.userEntityRef,
          permission: request.permission.name,
          reason: validation.reason,
          component: 'kro-permissions'
        });
        return { result: AuthorizeResult.DENY };
      }

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);

      this.logger.error(`Error evaluating permission policy`, {
        permission: request.permission.name,
        user: user?.identity.userEntityRef,
        error: errorMessage,
        component: 'kro-permissions'
      });

      // Deny by default on error
      return { result: AuthorizeResult.DENY };
    }
  }
}

/**
 * Kro permissions backend module
 */
export const kroPermissionsModule = createBackendModule({
  pluginId: 'permission',
  moduleId: 'kro-permissions',
  register(reg) {
    reg.registerInit({
      deps: {
        config: coreServices.rootConfig,
        logger: coreServices.logger,
        policy: coreServices.permissions,
      },
      async init({ config, logger, policy }) {
        logger.info('Initializing Kro permissions module');

        // Create RBAC validator
        const rbacValidator = new KroRBACValidator(logger, null); // kubernetesApi would be injected here

        // Create and register permission policy
        const kroPolicy = new KroPermissionPolicy(rbacValidator, logger);

        // Note: In a real implementation, you would register this policy with the permission system
        // This is a simplified example showing the structure

        logger.info('Kro permissions module initialized successfully');
      },
    });
  },
});