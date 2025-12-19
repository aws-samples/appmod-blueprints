import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['**/*.test.js'],
    exclude: [
      'node_modules/**',
      '**/node_modules/**',
      '**/integration/**',
      '**/*.integration.test.js',
      '**/*.config.js'
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'test/',
        '**/*.config.js',
        '**/integration/**'
      ]
    }
  }
});