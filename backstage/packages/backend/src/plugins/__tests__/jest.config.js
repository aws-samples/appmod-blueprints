module.exports = {
  displayName: 'Kro Plugin Tests',
  testMatch: [
    '<rootDir>/src/plugins/__tests__/**/*.test.{js,ts}',
    '<rootDir>/packages/app/src/components/__tests__/**/*.test.{js,ts,tsx}',
  ],
  testEnvironment: 'node',
  setupFilesAfterEnv: ['<rootDir>/src/plugins/__tests__/setup.ts'],
  collectCoverageFrom: [
    'src/plugins/**/*.{js,ts}',
    '!src/plugins/**/*.test.{js,ts}',
    '!src/plugins/__tests__/**',
    'packages/app/src/components/**/*.{js,ts,tsx}',
    '!packages/app/src/components/**/*.test.{js,ts,tsx}',
    '!packages/app/src/components/__tests__/**',
  ],
  coverageDirectory: '<rootDir>/coverage/kro-plugin',
  coverageReporters: ['text', 'lcov', 'html'],
  coverageThreshold: {
    global: {
      branches: 80,
      functions: 80,
      lines: 80,
      statements: 80,
    },
  },
  moduleNameMapping: {
    '^@backstage/(.*)$': '<rootDir>/node_modules/@backstage/$1',
    '^@terasky/(.*)$': '<rootDir>/node_modules/@terasky/$1',
  },
  transform: {
    '^.+\\.(ts|tsx)$': 'ts-jest',
    '^.+\\.(js|jsx)$': 'babel-jest',
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  testTimeout: 30000,
  verbose: true,
};