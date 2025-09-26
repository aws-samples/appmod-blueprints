/**
 * Simple template engine for testing Kro template substitution
 * This simulates how Kro would substitute ${...} expressions
 */
export class TemplateEngine {
  constructor(schema, resourceStatuses = {}) {
    this.schema = schema;
    this.resourceStatuses = resourceStatuses;
  }

  /**
   * Substitute template expressions in a string
   */
  substitute(template) {
    if (typeof template !== 'string') {
      return template;
    }

    // Handle ${schema.spec.*} expressions
    template = template.replace(/\$\{schema\.spec\.([^}]+)\}/g, (match, path) => {
      return this.getNestedValue(this.schema.spec, path);
    });

    // Handle resource status expressions like ${ecrmainrepo.status.repositoryURI}
    template = template.replace(/\$\{([^.]+)\.status\.([^}]+)\}/g, (match, resourceId, statusPath) => {
      const resourceStatus = this.resourceStatuses[resourceId];
      if (resourceStatus && resourceStatus.status) {
        return this.getNestedValue(resourceStatus.status, statusPath);
      }
      return match; // Return original if not found
    });

    // Handle resource metadata expressions like ${iamrole.status.ackResourceMetadata.arn}
    template = template.replace(/\$\{([^.]+)\.status\.ackResourceMetadata\.([^}]+)\}/g, (match, resourceId, metadataPath) => {
      const resourceStatus = this.resourceStatuses[resourceId];
      if (resourceStatus && resourceStatus.status && resourceStatus.status.ackResourceMetadata) {
        return this.getNestedValue(resourceStatus.status.ackResourceMetadata, metadataPath);
      }
      return match; // Return original if not found
    });

    return template;
  }

  /**
   * Substitute template expressions in an object recursively
   */
  substituteObject(obj) {
    if (typeof obj === 'string') {
      return this.substitute(obj);
    }

    if (Array.isArray(obj)) {
      return obj.map(item => this.substituteObject(item));
    }

    if (obj && typeof obj === 'object') {
      const result = {};
      for (const [key, value] of Object.entries(obj)) {
        result[key] = this.substituteObject(value);
      }
      return result;
    }

    return obj;
  }

  /**
   * Evaluate readyWhen conditions
   */
  evaluateReadyWhen(conditions) {
    return conditions.every(condition => {
      return this.evaluateCondition(condition);
    });
  }

  /**
   * Evaluate a single condition expression
   */
  evaluateCondition(condition) {
    // Handle namespace.status.phase == "Active"
    if (condition.includes('namespace.status.phase == "Active"')) {
      const namespaceStatus = this.resourceStatuses.namespace;
      return namespaceStatus && namespaceStatus.status && namespaceStatus.status.phase === 'Active';
    }

    // Handle resource.status checks
    const statusCheckMatch = condition.match(/\$\{(\w+)\.status\}$/);
    if (statusCheckMatch) {
      const resourceId = statusCheckMatch[1];
      const resourceStatus = this.resourceStatuses[resourceId];
      // Return true only if resourceStatus exists and status is not null/undefined
      return resourceStatus && resourceStatus.status !== null && resourceStatus.status !== undefined;
    }

    // Handle conditions array checks like ecrmainrepo.status.conditions[0].status == "True"
    const conditionsMatch = condition.match(/(\w+)\.status\.conditions\[0\]\.status == "True"/);
    if (conditionsMatch) {
      const resourceId = conditionsMatch[1];
      const resourceStatus = this.resourceStatuses[resourceId];
      return resourceStatus &&
        resourceStatus.status &&
        resourceStatus.status.conditions &&
        resourceStatus.status.conditions[0] &&
        resourceStatus.status.conditions[0].status === 'True';
    }

    // Handle exists conditions like podidentityassoc.status.conditions.exists(x, x.type == 'ACK.ResourceSynced' && x.status == "True")
    const existsMatch = condition.match(/(\w+)\.status\.conditions\.exists\(x, x\.type == '([^']+)' && x\.status == "([^"]+)"\)/);
    if (existsMatch) {
      const resourceId = existsMatch[1];
      const conditionType = existsMatch[2];
      const conditionStatus = existsMatch[3];
      const resourceStatus = this.resourceStatuses[resourceId];

      if (resourceStatus && resourceStatus.status && resourceStatus.status.conditions) {
        return resourceStatus.status.conditions.some(cond =>
          cond.type === conditionType && cond.status === conditionStatus
        );
      }
      return false;
    }

    // Handle complex boolean expressions
    if (condition.includes('&&')) {
      const parts = condition.split('&&').map(part => part.trim());
      return parts.every(part => this.evaluateCondition(part));
    }

    // Default: assume condition is met if we can't parse it
    return true;
  }

  /**
   * Get nested value from object using dot notation
   */
  getNestedValue(obj, path) {
    return path.split('.').reduce((current, key) => {
      return current && current[key] !== undefined ? current[key] : '';
    }, obj);
  }
}