/**
 * Jest setup file for Kro plugin tests
 * Configures global test environment and mocks
 */

import '@testing-library/jest-dom';

// Global test configuration
beforeAll(() => {
  // Set test environment variables
  process.env.NODE_ENV = 'test';
  process.env.LOG_LEVEL = 'error'; // Reduce log noise during tests

  // Mock HTMLFormElement.prototype.requestSubmit for JSDOM compatibility
  if (typeof HTMLFormElement.prototype.requestSubmit === 'undefined') {
    HTMLFormElement.prototype.requestSubmit = function () {
      const submitEvent = new Event('submit', { bubbles: true, cancelable: true });
      this.dispatchEvent(submitEvent);
    };
  }
});

// Global mocks
global.fetch = jest.fn();

// Mock console methods to reduce noise during tests
const originalConsole = { ...console };
beforeEach(() => {
  // Suppress console output during tests unless debugging
  if (process.env.DEBUG_TESTS !== 'true') {
    console.log = jest.fn();
    console.info = jest.fn();
    console.warn = jest.fn();
    console.error = jest.fn();
  }
});

afterEach(() => {
  // Restore console for debugging if needed
  if (process.env.DEBUG_TESTS === 'true') {
    Object.assign(console, originalConsole);
  }

  // Clear all mocks
  jest.clearAllMocks();
});

// Mock Kubernetes client globally
jest.mock('@kubernetes/client-node', () => ({
  KubeConfig: jest.fn().mockImplementation(() => ({
    loadFromDefault: jest.fn(),
    loadFromString: jest.fn(),
    makeApiClient: jest.fn(),
  })),
  CoreV1Api: jest.fn(),
  CustomObjectsApi: jest.fn(),
  AppsV1Api: jest.fn(),
}));

// Mock Backstage test utilities
jest.mock('@backstage/backend-test-utils', () => ({
  TestBackend: jest.fn().mockImplementation(() => ({
    add: jest.fn(),
    start: jest.fn().mockResolvedValue({
      logger: {
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
      },
    }),
    stop: jest.fn(),
  })),
  mockServices: {
    rootConfig: {
      factory: jest.fn().mockImplementation((config) => ({
        data: config.data,
        getOptionalConfig: jest.fn().mockImplementation((key) => {
          const value = config.data[key];
          return value ? {
            getOptionalConfigArray: jest.fn().mockReturnValue(value.clusters || value.resources || []),
            getOptionalString: jest.fn().mockImplementation((subKey) => {
              return value[subKey];
            }),
            getString: jest.fn().mockImplementation((subKey) => {
              return value[subKey];
            }),
          } : undefined;
        }),
      })),
    },
    logger: {
      factory: jest.fn().mockReturnValue({
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
      }),
    },
  },
}));

// Mock catalog processing extension point
jest.mock('@backstage/plugin-catalog-node/alpha', () => ({
  catalogProcessingExtensionPoint: {
    id: 'catalog.processing',
  },
}));

// Global test helpers
global.createMockLogger = () => ({
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
});

global.createMockUser = (userRef = 'user:default/test-user', type = 'user') => ({
  identity: {
    userEntityRef: userRef,
    type,
    ownershipEntityRefs: [],
  },
  token: 'mock-token',
});

global.createMockKubernetesClient = () => ({
  listResourceGraphDefinitions: jest.fn(),
  getResourceGraphDefinition: jest.fn(),
  listResourceGroups: jest.fn(),
  getResourceGroup: jest.fn(),
  createResourceGroup: jest.fn(),
  updateResourceGroup: jest.fn(),
  deleteResourceGroup: jest.fn(),
  watchResourceGroup: jest.fn(),
  canI: jest.fn(),
  getServiceAccountPermissions: jest.fn(),
  validateClusterAccess: jest.fn(),
});

// Extend Jest matchers
declare global {
  namespace jest {
    interface Matchers<R> {
      toHaveBeenCalledWithKroAuditEvent(eventType: string): R;
      toHaveValidKroEntityStructure(): R;
    }
  }
}

// Custom Jest matchers for Kro-specific assertions
expect.extend({
  toHaveBeenCalledWithKroAuditEvent(received, eventType) {
    const calls = received.mock.calls;
    const auditCall = calls.find(call =>
      call[1] && call[1].eventType === eventType && call[1].component === 'kro-audit'
    );

    if (auditCall) {
      return {
        message: () => `Expected not to have been called with Kro audit event ${eventType}`,
        pass: true,
      };
    } else {
      return {
        message: () => `Expected to have been called with Kro audit event ${eventType}`,
        pass: false,
      };
    }
  },

  toHaveValidKroEntityStructure(received) {
    const entity = received;

    // Check required fields
    const hasApiVersion = entity.apiVersion === 'backstage.io/v1alpha1';
    const hasKind = entity.kind === 'Component';
    const hasName = entity.metadata && entity.metadata.name;
    const hasKroType = entity.spec && entity.spec.type === 'kro-resource-group';
    const hasKroAnnotations = entity.metadata && entity.metadata.annotations &&
      (entity.metadata.annotations['kro.run/resource-graph-definition'] ||
        entity.metadata.annotations['kro.run/resource-group']);

    const isValid = hasApiVersion && hasKind && hasName && hasKroType && hasKroAnnotations;

    if (isValid) {
      return {
        message: () => `Expected entity not to have valid Kro structure`,
        pass: true,
      };
    } else {
      const missing = [];
      if (!hasApiVersion) missing.push('apiVersion');
      if (!hasKind) missing.push('kind');
      if (!hasName) missing.push('metadata.name');
      if (!hasKroType) missing.push('spec.type');
      if (!hasKroAnnotations) missing.push('Kro annotations');

      return {
        message: () => `Expected entity to have valid Kro structure. Missing: ${missing.join(', ')}`,
        pass: false,
      };
    }
  },
});

// Test data factories
global.createMockResourceGraphDefinition = (name = 'test-rgd', namespace = 'default') => ({
  apiVersion: 'kro.run/v1alpha1',
  kind: 'ResourceGraphDefinition',
  metadata: {
    name,
    namespace,
    labels: {
      'app.kubernetes.io/name': name,
    },
  },
  spec: {
    schema: {
      apiVersion: 'kro.run/v1alpha1',
      kind: 'TestRG',
      spec: {
        properties: {
          name: { type: 'string' },
        },
        required: ['name'],
      },
    },
    resources: [],
  },
  status: {
    conditions: [
      {
        type: 'Ready',
        status: 'True',
        reason: 'ResourceGraphDefinitionReady',
      },
    ],
  },
});

global.createMockResourceGroup = (name = 'test-rg', namespace = 'default') => ({
  apiVersion: 'kro.run/v1alpha1',
  kind: 'TestRG',
  metadata: {
    name,
    namespace,
    labels: {
      'kro.run/resource-graph-definition': 'test-rgd',
    },
  },
  spec: {
    name: 'test-app',
  },
  status: {
    phase: 'Ready',
    conditions: [
      {
        type: 'Ready',
        status: 'True',
        reason: 'AllResourcesReady',
      },
    ],
  },
});

global.createMockCatalogEntity = (name = 'test-entity', namespace = 'default') => ({
  apiVersion: 'backstage.io/v1alpha1',
  kind: 'Component',
  metadata: {
    name,
    namespace,
    annotations: {
      'backstage.io/kubernetes-id': name,
      'kro.run/resource-group': name,
    },
    labels: {
      'backstage.io/kubernetes-cluster': 'test-cluster',
    },
  },
  spec: {
    type: 'kro-resource-group',
    lifecycle: 'production',
    owner: 'platform-team',
  },
});