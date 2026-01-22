import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Test configuration for workflow integration tests
    testTimeout: 600000, // 10 minutes for workflow tests
    hookTimeout: 600000, // 10 minutes for setup/teardown
    teardownTimeout: 300000, // 5 minutes for cleanup

    // Only run workflow integration tests
    include: ['**/workflow-integration.test.js'],

    // Sequential execution for integration tests to avoid resource conflicts
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true
      }
    },

    // Environment variables for tests
    env: {
      NODE_ENV: 'test',
      VITEST_WORKFLOW_INTEGRATION: 'true'
    },

    // Retry configuration for flaky integration tests
    retry: 1,

    // Reporter configuration
    reporter: ['verbose', 'json'],
    outputFile: {
      json: './workflow-integration-results.json'
    },

    // Global setup and teardown
    globalSetup: './setup/workflow-global-setup.js',

    // Coverage configuration (disabled for integration tests)
    coverage: {
      enabled: false
    }
  }
});