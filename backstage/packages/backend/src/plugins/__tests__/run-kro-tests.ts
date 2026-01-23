#!/usr/bin/env node

/**
 * Comprehensive test runner for Kro plugin functionality
 * This script runs all Kro-related tests and provides a summary report
 */

import { execSync } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';

interface TestResult {
  testFile: string;
  passed: boolean;
  duration: number;
  error?: string;
}

interface TestSuite {
  name: string;
  description: string;
  testFiles: string[];
}

const testSuites: TestSuite[] = [
  {
    name: 'Plugin Integration',
    description: 'Tests for Kro plugin initialization and configuration',
    testFiles: ['kro-plugin-integration.test.ts'],
  },
  {
    name: 'Catalog Integration',
    description: 'Tests for ResourceGroup catalog integration and entity processing',
    testFiles: ['kro-catalog-integration.test.ts'],
  },
  {
    name: 'ResourceGroup Workflows',
    description: 'Tests for ResourceGroup discovery, creation, and management',
    testFiles: ['kro-resource-group-workflows.test.ts'],
  },
  {
    name: 'Permissions Validation',
    description: 'Tests for RBAC and permission validation scenarios',
    testFiles: ['kro-permissions-validation.test.ts'],
  },
  {
    name: 'Security Components',
    description: 'Tests for security, audit logging, and error handling',
    testFiles: ['kro-security.test.ts'],
  },
];

const frontendTestSuites: TestSuite[] = [
  {
    name: 'Frontend Integration',
    description: 'Tests for Kro frontend components and catalog integration',
    testFiles: ['../../../app/src/components/__tests__/KroIntegration.test.tsx'],
  },
];

class KroTestRunner {
  private results: TestResult[] = [];
  private startTime: number = Date.now();

  async runTestSuite(suite: TestSuite, isBackend: boolean = true): Promise<void> {
    console.log(`\n🧪 Running ${suite.name} Tests`);
    console.log(`📝 ${suite.description}`);
    console.log('─'.repeat(60));

    for (const testFile of suite.testFiles) {
      await this.runTestFile(testFile, isBackend);
    }
  }

  async runTestFile(testFile: string, isBackend: boolean = true): Promise<void> {
    const startTime = Date.now();
    const testPath = isBackend
      ? join(__dirname, testFile)
      : join(__dirname, testFile);

    if (!existsSync(testPath)) {
      console.log(`⚠️  Test file not found: ${testFile}`);
      this.results.push({
        testFile,
        passed: false,
        duration: 0,
        error: 'Test file not found',
      });
      return;
    }

    try {
      console.log(`🔄 Running ${testFile}...`);

      // Run the test using Jest
      const command = isBackend
        ? `cd ${join(__dirname, '../../../..')} && yarn test --testPathPattern="${testFile}" --verbose --no-coverage`
        : `cd ${join(__dirname, '../../../..')} && yarn test --testPathPattern="${testFile}" --verbose --no-coverage`;

      execSync(command, {
        stdio: 'pipe',
        timeout: 60000, // 60 second timeout
      });

      const duration = Date.now() - startTime;
      console.log(`✅ ${testFile} passed (${duration}ms)`);

      this.results.push({
        testFile,
        passed: true,
        duration,
      });
    } catch (error) {
      const duration = Date.now() - startTime;
      const errorMessage = error instanceof Error ? error.message : String(error);

      console.log(`❌ ${testFile} failed (${duration}ms)`);
      console.log(`   Error: ${errorMessage.split('\n')[0]}`);

      this.results.push({
        testFile,
        passed: false,
        duration,
        error: errorMessage,
      });
    }
  }

  async runAllTests(): Promise<void> {
    console.log('🚀 Starting Kro Plugin Test Suite');
    console.log('═'.repeat(60));

    // Run backend tests
    console.log('\n📦 Backend Tests');
    for (const suite of testSuites) {
      await this.runTestSuite(suite, true);
    }

    // Run frontend tests
    console.log('\n🎨 Frontend Tests');
    for (const suite of frontendTestSuites) {
      await this.runTestSuite(suite, false);
    }

    this.printSummary();
  }

  printSummary(): void {
    const totalDuration = Date.now() - this.startTime;
    const passedTests = this.results.filter(r => r.passed);
    const failedTests = this.results.filter(r => !r.passed);

    console.log('\n📊 Test Summary');
    console.log('═'.repeat(60));
    console.log(`Total Tests: ${this.results.length}`);
    console.log(`✅ Passed: ${passedTests.length}`);
    console.log(`❌ Failed: ${failedTests.length}`);
    console.log(`⏱️  Total Duration: ${totalDuration}ms`);
    console.log(`📈 Success Rate: ${((passedTests.length / this.results.length) * 100).toFixed(1)}%`);

    if (failedTests.length > 0) {
      console.log('\n❌ Failed Tests:');
      failedTests.forEach(test => {
        console.log(`   • ${test.testFile}: ${test.error?.split('\n')[0] || 'Unknown error'}`);
      });
    }

    console.log('\n📋 Test Coverage Areas:');
    console.log('   ✓ Plugin initialization and configuration');
    console.log('   ✓ Kubernetes cluster connectivity');
    console.log('   ✓ ResourceGraphDefinition discovery');
    console.log('   ✓ ResourceGroup creation and management');
    console.log('   ✓ Catalog integration and entity processing');
    console.log('   ✓ Entity relationships and status tracking');
    console.log('   ✓ RBAC and permission validation');
    console.log('   ✓ Error handling and audit logging');
    console.log('   ✓ Frontend component integration');
    console.log('   ✓ User interface workflows');

    if (failedTests.length === 0) {
      console.log('\n🎉 All tests passed! Kro plugin is ready for deployment.');
    } else {
      console.log('\n⚠️  Some tests failed. Please review the errors above.');
      process.exit(1);
    }
  }

  async runSpecificTest(testName: string): Promise<void> {
    console.log(`🎯 Running specific test: ${testName}`);

    const allTestFiles = [
      ...testSuites.flatMap(suite => suite.testFiles),
      ...frontendTestSuites.flatMap(suite => suite.testFiles),
    ];

    const matchingTest = allTestFiles.find(file =>
      file.includes(testName) || file.endsWith(`${testName}.test.ts`) || file.endsWith(`${testName}.test.tsx`)
    );

    if (!matchingTest) {
      console.log(`❌ Test not found: ${testName}`);
      console.log('Available tests:');
      allTestFiles.forEach(file => console.log(`   • ${file}`));
      return;
    }

    const isBackend = !matchingTest.includes('app/src');
    await this.runTestFile(matchingTest, isBackend);
    this.printSummary();
  }
}

// CLI interface
async function main() {
  const args = process.argv.slice(2);
  const runner = new KroTestRunner();

  if (args.length === 0) {
    await runner.runAllTests();
  } else if (args[0] === '--help' || args[0] === '-h') {
    console.log('Kro Plugin Test Runner');
    console.log('Usage:');
    console.log('  yarn test:kro                    # Run all tests');
    console.log('  yarn test:kro <test-name>        # Run specific test');
    console.log('  yarn test:kro --help             # Show this help');
    console.log('');
    console.log('Available test suites:');
    testSuites.forEach(suite => {
      console.log(`  • ${suite.name}: ${suite.description}`);
    });
    frontendTestSuites.forEach(suite => {
      console.log(`  • ${suite.name}: ${suite.description}`);
    });
  } else {
    await runner.runSpecificTest(args[0]);
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error('❌ Test runner failed:', error);
    process.exit(1);
  });
}

export { KroTestRunner, testSuites, frontendTestSuites };