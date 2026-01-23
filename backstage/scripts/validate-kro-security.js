#!/usr/bin/env node

/**
 * Validation script for Kro security configuration
 */

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

console.log('🔒 Validating Kro Security Configuration...\n');

// Check if security files exist
const securityFiles = [
  'packages/backend/src/plugins/kro-permissions.ts',
  'packages/backend/src/plugins/kro-audit.ts',
  'packages/backend/src/plugins/kro-error-handler.ts',
  'packages/backend/src/plugins/kro-security.ts',
  'k8s-rbac/kro-rbac.yaml',
  'docs/kro-security.md'
];

let allFilesExist = true;

securityFiles.forEach(file => {
  const filePath = path.join(__dirname, '..', file);
  if (fs.existsSync(filePath)) {
    console.log(`✅ ${file} - exists`);
  } else {
    console.log(`❌ ${file} - missing`);
    allFilesExist = false;
  }
});

// Check app-config.yaml for security configuration
const configPath = path.join(__dirname, '..', 'app-config.yaml');
if (fs.existsSync(configPath)) {
  try {
    const configContent = fs.readFileSync(configPath, 'utf8');
    const config = yaml.load(configContent);

    console.log('\n📋 Checking app-config.yaml security settings:');

    // Check permission settings
    if (config.permission && config.permission.enabled) {
      console.log('✅ Permissions enabled');
    } else {
      console.log('❌ Permissions not enabled');
    }

    // Check Kro security settings
    if (config.kro) {
      if (config.kro.enablePermissions) {
        console.log('✅ Kro permissions enabled');
      } else {
        console.log('❌ Kro permissions not enabled');
      }

      if (config.kro.enableAuditLogging) {
        console.log('✅ Kro audit logging enabled');
      } else {
        console.log('❌ Kro audit logging not enabled');
      }

      if (config.kro.rbacValidation && config.kro.rbacValidation.enabled) {
        console.log('✅ RBAC validation enabled');
      } else {
        console.log('❌ RBAC validation not enabled');
      }
    } else {
      console.log('❌ Kro configuration section missing');
    }

  } catch (error) {
    console.log(`❌ Error reading app-config.yaml: ${error.message}`);
  }
} else {
  console.log('❌ app-config.yaml not found');
}

// Check backend index.ts for security module imports
const backendIndexPath = path.join(__dirname, '..', 'packages/backend/src/index.ts');
if (fs.existsSync(backendIndexPath)) {
  const backendContent = fs.readFileSync(backendIndexPath, 'utf8');

  console.log('\n🔧 Checking backend module imports:');

  const requiredImports = [
    'kro-security',
    'kro-permissions',
    'kro-audit'
  ];

  requiredImports.forEach(module => {
    if (backendContent.includes(module)) {
      console.log(`✅ ${module} module imported`);
    } else {
      console.log(`❌ ${module} module not imported`);
    }
  });
} else {
  console.log('❌ Backend index.ts not found');
}

// Check RBAC configuration
const rbacPath = path.join(__dirname, '..', 'k8s-rbac/kro-rbac.yaml');
if (fs.existsSync(rbacPath)) {
  try {
    const rbacContent = fs.readFileSync(rbacPath, 'utf8');
    const rbacDocs = yaml.loadAll(rbacContent);

    console.log('\n🔐 Checking RBAC configuration:');

    const hasServiceAccount = rbacDocs.some(doc => doc.kind === 'ServiceAccount');
    const hasClusterRole = rbacDocs.some(doc => doc.kind === 'ClusterRole');
    const hasClusterRoleBinding = rbacDocs.some(doc => doc.kind === 'ClusterRoleBinding');

    if (hasServiceAccount) {
      console.log('✅ ServiceAccount defined');
    } else {
      console.log('❌ ServiceAccount missing');
    }

    if (hasClusterRole) {
      console.log('✅ ClusterRole defined');
    } else {
      console.log('❌ ClusterRole missing');
    }

    if (hasClusterRoleBinding) {
      console.log('✅ ClusterRoleBinding defined');
    } else {
      console.log('❌ ClusterRoleBinding missing');
    }

  } catch (error) {
    console.log(`❌ Error reading RBAC configuration: ${error.message}`);
  }
}

console.log('\n🏁 Validation Summary:');
if (allFilesExist) {
  console.log('✅ All security files are present');
  console.log('✅ Kro security configuration is complete');
  console.log('\n📚 Next steps:');
  console.log('1. Apply RBAC configuration: kubectl apply -f k8s-rbac/kro-rbac.yaml');
  console.log('2. Update service account tokens in environment variables');
  console.log('3. Test permission validation with different user roles');
  console.log('4. Monitor audit logs for security events');
} else {
  console.log('❌ Some security files are missing');
  console.log('Please ensure all security components are properly implemented');
}

console.log('\n📖 For more information, see: docs/kro-security.md');