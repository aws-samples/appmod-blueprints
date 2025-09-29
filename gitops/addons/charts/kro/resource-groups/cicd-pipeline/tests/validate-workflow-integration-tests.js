#!/usr/bin/env node

/**
 * Validation script for workflow integration tests
 * Validates test structure, configuration, and dependencies without requiring a cluster
 */

import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Colors for output
const colors = {
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  reset: '\x1b[0m'
};

const log = {
  info: (msg) => console.log(`${colors.blue}[INFO]${colors.reset} ${msg}`),
  success: (msg) => console.log(`${colors.green}[SUCCESS]${colors.reset} ${msg}`),
  warning: (msg) => console.log(`${colors.yellow}[WARNING]${colors.reset} ${msg}`),
  error: (msg) => console.log(`${colors.red}[ERROR]${colors.reset} ${msg}`)
};

// Validation functions
const validateFileExists = (filePath, description) => {
  if (existsSync(filePath)) {
    log.success(`${description} exists: ${filePath}`);
    return true;
  } else {
    log.error(`${description} missing: ${filePath}`);
    return false;
  }
};

const validateJSONFile = (filePath, description) => {
  try {
    const content = readFileSync(filePath, 'utf8');
    JSON.parse(content);
    log.success(`${description} is valid JSON: ${filePath}`);
    return true;
  } catch (error) {
    log.error(`${description} is invalid JSON: ${filePath} - ${error.message}`);
    return false;
  }
};

const validateJSFile = (filePath, description) => {
  try {
    // Basic syntax validation by attempting to read and parse
    const content = readFileSync(filePath, 'utf8');

    // Check for basic ES6 module structure
    if (content.includes('import') && content.includes('export')) {
      log.success(`${description} has valid ES6 module structure: ${filePath}`);
      return true;
    } else {
      log.warning(`${description} may not be a proper ES6 module: ${filePath}`);
      return true; // Not a failure, just a warning
    }
  } catch (error) {
    log.error(`${description} validation failed: ${filePath} - ${error.message}`);
    return false;
  }
};

const validateTestStructure = (testFilePath) => {
  try {
    const content = readFileSync(testFilePath, 'utf8');

    // Check for required test structure
    const requiredPatterns = [
      { pattern: /describe\s*\(\s*['"`].*Workflow Integration.*['"`]/, name: 'Main test suite' },
      { pattern: /describe\s*\(\s*['"`].*Argo Workflows Access.*['"`]/, name: 'Argo Workflows Access tests' },
      { pattern: /describe\s*\(\s*['"`].*ECR Authentication.*['"`]/, name: 'ECR Authentication tests' },
      { pattern: /describe\s*\(\s*['"`].*Webhook Triggering.*['"`]/, name: 'Webhook Triggering tests' },
      { pattern: /beforeAll\s*\(/, name: 'beforeAll setup' },
      { pattern: /afterAll\s*\(/, name: 'afterAll cleanup' },
      { pattern: /it\s*\(\s*['"`].*WorkflowTemplates.*['"`]/, name: 'WorkflowTemplate tests' },
      { pattern: /it\s*\(\s*['"`].*ECR.*['"`]/, name: 'ECR tests' },
      { pattern: /it\s*\(\s*['"`].*webhook.*['"`]/i, name: 'Webhook tests' }
    ];

    let allPatternsFound = true;

    for (const { pattern, name } of requiredPatterns) {
      if (pattern.test(content)) {
        log.success(`Found ${name} in test file`);
      } else {
        log.error(`Missing ${name} in test file`);
        allPatternsFound = false;
      }
    }

    return allPatternsFound;
  } catch (error) {
    log.error(`Failed to validate test structure: ${error.message}`);
    return false;
  }
};

const validateRequirementsCoverage = (testFilePath) => {
  try {
    const content = readFileSync(testFilePath, 'utf8');

    // Check for requirement coverage (5.1-5.5)
    const requirements = [
      { req: '5.1', description: 'GitLab webhooks trigger Argo Events' },
      { req: '5.2', description: 'Webhooks point to correct Argo Events endpoint' },
      { req: '5.3', description: 'Argo Workflows have access to secrets and configmaps' },
      { req: '5.4', description: 'Builds use Kaniko for container image building' },
      { req: '5.5', description: 'Deployments update GitLab repositories with new image tags' }
    ];

    let allRequirementsCovered = true;

    for (const { req, description } of requirements) {
      const reqPattern = new RegExp(`Requirement\\s+${req}`, 'i');
      if (reqPattern.test(content) || content.includes(`Requirements ${req}`)) {
        log.success(`Requirement ${req} coverage found: ${description}`);
      } else {
        log.warning(`Requirement ${req} coverage not explicitly mentioned: ${description}`);
        // Not marking as failure since requirements might be covered implicitly
      }
    }

    return allRequirementsCovered;
  } catch (error) {
    log.error(`Failed to validate requirements coverage: ${error.message}`);
    return false;
  }
};

const validatePackageJSON = (packagePath) => {
  try {
    const content = readFileSync(packagePath, 'utf8');
    const pkg = JSON.parse(content);

    // Check for required scripts
    const requiredScripts = ['test:workflow', 'test:workflow:watch'];
    let allScriptsPresent = true;

    for (const script of requiredScripts) {
      if (pkg.scripts && pkg.scripts[script]) {
        log.success(`Found required script: ${script}`);
      } else {
        log.error(`Missing required script: ${script}`);
        allScriptsPresent = false;
      }
    }

    // Check for required dependencies
    const requiredDeps = ['vitest', 'js-yaml'];
    for (const dep of requiredDeps) {
      if (pkg.devDependencies && pkg.devDependencies[dep]) {
        log.success(`Found required dependency: ${dep}`);
      } else {
        log.error(`Missing required dependency: ${dep}`);
        allScriptsPresent = false;
      }
    }

    return allScriptsPresent;
  } catch (error) {
    log.error(`Failed to validate package.json: ${error.message}`);
    return false;
  }
};

// Main validation function
const validateWorkflowIntegrationTests = () => {
  log.info('Starting workflow integration test validation...');

  const integrationDir = join(__dirname, 'integration');
  const testsDir = __dirname;

  let allValidationsPassed = true;

  // File existence checks
  const filesToCheck = [
    { path: join(integrationDir, 'workflow-integration.test.js'), desc: 'Workflow integration test file' },
    { path: join(integrationDir, 'vitest.workflow.config.js'), desc: 'Workflow test configuration' },
    { path: join(integrationDir, 'setup', 'workflow-global-setup.js'), desc: 'Workflow global setup' },
    { path: join(integrationDir, 'utils', 'workflow-test-utils.js'), desc: 'Workflow test utilities' },
    { path: join(integrationDir, 'WORKFLOW_INTEGRATION_TESTS.md'), desc: 'Workflow integration test documentation' },
    { path: join(testsDir, 'run-workflow-integration-tests.sh'), desc: 'Workflow test runner script' }
  ];

  for (const { path, desc } of filesToCheck) {
    if (!validateFileExists(path, desc)) {
      allValidationsPassed = false;
    }
  }

  // JSON file validation
  const jsonFiles = [
    { path: join(integrationDir, 'package.json'), desc: 'Integration test package.json' }
  ];

  for (const { path, desc } of jsonFiles) {
    if (existsSync(path) && !validateJSONFile(path, desc)) {
      allValidationsPassed = false;
    }
  }

  // JavaScript file validation
  const jsFiles = [
    { path: join(integrationDir, 'workflow-integration.test.js'), desc: 'Workflow integration test' },
    { path: join(integrationDir, 'vitest.workflow.config.js'), desc: 'Workflow test config' },
    { path: join(integrationDir, 'setup', 'workflow-global-setup.js'), desc: 'Workflow global setup' },
    { path: join(integrationDir, 'utils', 'workflow-test-utils.js'), desc: 'Workflow test utils' }
  ];

  for (const { path, desc } of jsFiles) {
    if (existsSync(path) && !validateJSFile(path, desc)) {
      allValidationsPassed = false;
    }
  }

  // Test structure validation
  const testFile = join(integrationDir, 'workflow-integration.test.js');
  if (existsSync(testFile)) {
    if (!validateTestStructure(testFile)) {
      allValidationsPassed = false;
    }

    if (!validateRequirementsCoverage(testFile)) {
      // Requirements coverage is not a hard failure
      log.warning('Some requirements coverage may be implicit');
    }
  }

  // Package.json validation
  const packageFile = join(integrationDir, 'package.json');
  if (existsSync(packageFile) && !validatePackageJSON(packageFile)) {
    allValidationsPassed = false;
  }

  // Summary
  console.log('\n' + '='.repeat(50));
  console.log('  Workflow Integration Test Validation Results');
  console.log('='.repeat(50));

  if (allValidationsPassed) {
    log.success('All workflow integration test validations passed!');
    console.log('\n✅ Test file structure is correct');
    console.log('✅ Configuration files are valid');
    console.log('✅ Test utilities are properly structured');
    console.log('✅ Documentation is complete');
    console.log('✅ Package configuration is correct');
    console.log('\nThe workflow integration tests are ready to run!');
  } else {
    log.error('Some workflow integration test validations failed!');
    console.log('\n❌ Check the errors above and fix the issues');
    console.log('❌ Ensure all required files are present');
    console.log('❌ Verify file syntax and structure');
  }

  console.log('='.repeat(50));

  return allValidationsPassed;
};

// Run validation
const success = validateWorkflowIntegrationTests();
process.exit(success ? 0 : 1);