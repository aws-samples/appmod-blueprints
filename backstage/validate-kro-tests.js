#!/usr/bin/env node

/**
 * Validate Kro test files and setup
 */

const fs = require('fs');
const path = require('path');

const testFiles = [
  'packages/backend/src/plugins/__tests__/kro-plugin-integration.test.ts',
  'packages/backend/src/plugins/__tests__/kro-catalog-integration.test.ts',
  'packages/backend/src/plugins/__tests__/kro-resource-group-workflows.test.ts',
  'packages/backend/src/plugins/__tests__/kro-permissions-validation.test.ts',
  'packages/backend/src/plugins/__tests__/kro-security.test.ts',
  'packages/app/src/components/__tests__/KroIntegration.test.tsx',
];

const supportFiles = [
  'packages/backend/src/plugins/__tests__/setup.ts',
  'packages/backend/src/plugins/__tests__/jest.config.js',
  'packages/backend/src/plugins/kro-resource-group-service.ts',
  'packages/backend/src/plugins/catalog-processors/kro-resource-group-processor.ts',
];

function validateFile(filePath) {
  const fullPath = path.join(__dirname, filePath);

  if (!fs.existsSync(fullPath)) {
    console.log(`❌ Missing: ${filePath}`);
    return false;
  }

  const content = fs.readFileSync(fullPath, 'utf8');

  // Basic validation
  if (content.length < 100) {
    console.log(`⚠️  Suspiciously small: ${filePath} (${content.length} chars)`);
    return false;
  }

  // Check for test structure
  if (filePath.includes('.test.')) {
    if (!content.includes('describe(') && !content.includes('it(')) {
      console.log(`⚠️  No test structure found: ${filePath}`);
      return false;
    }
  }

  console.log(`✅ Valid: ${filePath}`);
  return true;
}

function main() {
  console.log('🔍 Validating Kro test files...');
  console.log('═'.repeat(60));

  let allValid = true;

  console.log('\n📋 Test Files:');
  testFiles.forEach(file => {
    if (!validateFile(file)) {
      allValid = false;
    }
  });

  console.log('\n🛠️  Support Files:');
  supportFiles.forEach(file => {
    if (!validateFile(file)) {
      allValid = false;
    }
  });

  console.log('\n📊 Summary:');
  if (allValid) {
    console.log('✅ All files are present and valid!');
    console.log('\n🚀 You can now run tests using:');
    console.log('   yarn test:kro                    # All Kro tests');
    console.log('   node test-kro.js                 # Using custom runner');
    console.log('   node test-kro.js integration     # Specific test suite');
    console.log('   node test-kro.js --help          # Show help');
  } else {
    console.log('❌ Some files are missing or invalid');
    process.exit(1);
  }
}

main();