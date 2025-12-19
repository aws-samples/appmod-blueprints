# Kro Plugin Test Suite

This directory contains comprehensive tests for the Kro Backstage plugin integration, covering all aspects of ResourceGroup management, catalog integration, and security validation.

## 🧪 Test Files Overview

### Backend Tests

1. **`kro-plugin-integration.test.ts`**
   - Plugin initialization and configuration validation
   - Backend module registration and error handling
   - Catalog module integration
   - Kubernetes Ingestor configuration validation

2. **`kro-catalog-integration.test.ts`**
   - ResourceGraphDefinition processing and entity transformation
   - ResourceGroup instance catalog integration
   - Entity relationships and status tracking
   - Error handling for malformed resources

3. **`kro-resource-group-workflows.test.ts`**
   - ResourceGraphDefinition discovery workflows
   - ResourceGroup creation with parameter validation
   - ResourceGroup management operations (CRUD)
   - Status monitoring and real-time updates

4. **`kro-permissions-validation.test.ts`**
   - RBAC validation for different user types
   - Permission caching and timeout handling
   - Authentication and authorization error scenarios
   - Strict mode and resource-specific permissions

5. **`kro-security.test.ts`**
   - Security service configuration validation
   - Audit logging functionality
   - Error handling utilities
   - Security policy enforcement

### Frontend Tests

6. **`KroIntegration.test.tsx`**
   - ResourceGroup table rendering and filtering
   - ResourceGroup details display components
   - Create form validation and submission
   - Catalog API integration and error handling

## 🛠️ Support Files

- **`setup.ts`** - Jest configuration and global mocks
- **`jest.config.js`** - Jest configuration for Kro tests
- **`run-kro-tests.ts`** - Comprehensive test runner script

## 🚀 Running Tests

### Using Package Scripts

```bash
# Run all Kro tests
yarn test:kro

# Run with coverage
yarn test:kro:coverage

# Run in watch mode
yarn test:kro:watch
```

### Using Jest Directly

```bash
# Run specific test file
yarn test --testPathPattern="kro-plugin-integration.test.ts"

# Run all backend tests
yarn test --testPathPattern="kro.*test.ts"

# Run frontend tests
yarn test --testPathPattern="KroIntegration.test.tsx"

# Run with coverage
yarn test --testPathPattern="kro" --coverage
```

### Using Custom Test Runner

```bash
# Run all tests with detailed output
node packages/backend/src/plugins/__tests__/run-kro-tests.ts

# Run specific test suite
node packages/backend/src/plugins/__tests__/run-kro-tests.ts integration

# Show help
node packages/backend/src/plugins/__tests__/run-kro-tests.ts --help
```

## 📋 Test Coverage Areas

### ✅ Plugin Integration
- [x] Backend module initialization
- [x] Configuration validation
- [x] Error handling for invalid configs
- [x] Catalog processor registration
- [x] Kubernetes Ingestor integration

### ✅ ResourceGroup Workflows
- [x] ResourceGraphDefinition discovery
- [x] Template parameter validation
- [x] ResourceGroup creation and management
- [x] Status monitoring and updates
- [x] Real-time status watching

### ✅ Catalog Integration
- [x] Entity transformation from Kubernetes resources
- [x] Relationship mapping between entities
- [x] Status propagation and error handling
- [x] Entity validation and structure verification
- [x] Catalog API integration

### ✅ Security & Permissions
- [x] RBAC validation for different user types
- [x] Permission caching and optimization
- [x] Authentication/authorization error handling
- [x] Audit logging for all operations
- [x] Security policy enforcement

### ✅ Error Handling
- [x] Kubernetes API connectivity issues
- [x] Authentication and authorization failures
- [x] Malformed resource handling
- [x] Network timeout scenarios
- [x] Configuration validation errors

### ✅ Frontend Components
- [x] ResourceGroup table and filtering
- [x] Details view and status display
- [x] Create form validation
- [x] Catalog integration
- [x] Error state handling

## 🎯 Test Data and Mocks

The test suite includes comprehensive mocking for:

- **Kubernetes Client** - Mock all K8s API operations
- **Backstage APIs** - Mock catalog and core services
- **User Authentication** - Mock different user types and permissions
- **Configuration** - Mock various configuration scenarios
- **Network Conditions** - Mock connection failures and timeouts

### Mock Data Factories

```typescript
// Create mock ResourceGraphDefinition
const mockRGD = createMockResourceGraphDefinition('cicd-pipeline', 'default');

// Create mock ResourceGroup
const mockRG = createMockResourceGroup('my-app-pipeline', 'default');

// Create mock catalog entity
const mockEntity = createMockCatalogEntity('test-entity', 'default');

// Create mock user with specific permissions
const mockUser = createMockUser('user:default/developer', 'user');
```

## 🔧 Custom Jest Matchers

The test suite includes custom Jest matchers for Kro-specific assertions:

```typescript
// Validate Kro audit events
expect(mockLogger.info).toHaveBeenCalledWithKroAuditEvent('RESOURCE_GROUP_CREATED');

// Validate entity structure
expect(entity).toHaveValidKroEntityStructure();
```

## 📊 Coverage Requirements

The test suite maintains high coverage standards:

- **Branches**: 80%
- **Functions**: 80%
- **Lines**: 80%
- **Statements**: 80%

## 🐛 Debugging Tests

### Enable Debug Output

```bash
# Enable console output during tests
DEBUG_TESTS=true yarn test:kro

# Run specific test with verbose output
yarn test --testPathPattern="kro-plugin-integration" --verbose
```

### Common Issues

1. **Mock Setup Issues**
   - Ensure all required mocks are configured in `setup.ts`
   - Check that Kubernetes client mocks return expected data

2. **Async Test Failures**
   - Use `waitFor` for async operations
   - Ensure proper cleanup in `afterEach` hooks

3. **Configuration Errors**
   - Verify mock configuration matches expected structure
   - Check that all required config fields are provided

## 🔄 Continuous Integration

The tests are designed to run in CI environments:

- **Timeout**: 30 seconds per test
- **Retry Logic**: Built-in for flaky network operations
- **Parallel Execution**: Safe for concurrent runs
- **Coverage Reports**: Generated in multiple formats

## 📝 Adding New Tests

When adding new tests:

1. Follow the existing naming convention: `kro-*.test.ts`
2. Use the provided mock factories and utilities
3. Include both success and error scenarios
4. Add appropriate audit logging validation
5. Update this README with new test coverage

## 🎉 Test Results

A successful test run should show:

```
🧪 Kro Plugin Test Suite
═══════════════════════════════════════════════════════════

📦 Backend Tests
✅ Plugin Integration (5 tests)
✅ Catalog Integration (8 tests)  
✅ ResourceGroup Workflows (12 tests)
✅ Permissions Validation (15 tests)
✅ Security Components (6 tests)

🎨 Frontend Tests
✅ Frontend Integration (10 tests)

📊 Test Summary
═══════════════════════════════════════════════════════════
Total Tests: 56
✅ Passed: 56
❌ Failed: 0
📈 Success Rate: 100%

🎉 All tests passed! Kro plugin is ready for deployment.
```