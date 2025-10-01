import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    testTimeout: 300000, // 5 minutes for integration tests
    hookTimeout: 60000,  // 1 minute for setup/teardown
    globals: true,
    environment: 'node',
    include: ['**/*.integration.test.js'],
    exclude: ['**/node_modules/**'],
    setupFiles: ['./setup/test-setup.js'],
    teardownTimeout: 60000,
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true // Run tests sequentially to avoid resource conflicts
      }
    }
  }
});