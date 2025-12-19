#!/usr/bin/env node

/**
 * Validation script for Kro catalog integration
 * Tests that ResourceGroup entities are properly configured and discoverable
 */

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

// Configuration paths
const APP_CONFIG_PATH = path.join(__dirname, '../app-config.yaml');
const ENTITIES_PATH = path.join(__dirname, '../examples/kro-resource-groups.yaml');
const BACKEND_INDEX_PATH = path.join(__dirname, '../packages/backend/src/index.ts');

// Validation results
const results = {
  passed: 0,
  failed: 0,
  warnings: 0,
  errors: []
};

function logResult(test, passed, message) {
  if (passed) {
    console.log(`✅ ${test}: ${message}`);
    results.passed++;
  } else {
    console.log(`❌ ${test}: ${message}`);
    results.failed++;
    results.errors.push(`${test}: ${message}`);
  }
}

function logWarning(test, message) {
  console.log(`⚠️  ${test}: ${message}`);
  results.warnings++;
}

function validateAppConfig() {
  console.log('\n🔍 Validating app-config.yaml...');

  try {
    const configContent = fs.readFileSync(APP_CONFIG_PATH, 'utf8');
    const config = yaml.load(configContent);

    // Check catalog rules
    const catalogRules = config.catalog?.rules || [];
    const hasKroRules = catalogRules.some(rule =>
      rule.allow?.includes('Component') &&
      rule.spec?.type === 'kro-resource-group'
    );

    logResult(
      'Catalog Rules',
      hasKroRules,
      hasKroRules
        ? 'Kro ResourceGroup entities are allowed in catalog rules'
        : 'Missing catalog rules for kro-resource-group type'
    );

    // Check kubernetesIngestor configuration
    const ingestorConfig = config.kubernetesIngestor;
    logResult(
      'Kubernetes Ingestor Config',
      !!ingestorConfig,
      ingestorConfig
        ? 'Kubernetes Ingestor configuration found'
        : 'Missing kubernetesIngestor configuration'
    );

    if (ingestorConfig) {
      const kroResources = ingestorConfig.resources?.filter(r =>
        r.apiVersion?.startsWith('kro.run/')
      ) || [];

      logResult(
        'Kro Resources Config',
        kroResources.length > 0,
        kroResources.length > 0
          ? `Found ${kroResources.length} Kro resource types configured`
          : 'No Kro resources configured for ingestion'
      );

      // Check for ResourceGraphDefinition
      const hasRGD = kroResources.some(r => r.kind === 'ResourceGraphDefinition');
      logResult(
        'ResourceGraphDefinition Config',
        hasRGD,
        hasRGD
          ? 'ResourceGraphDefinition configured for ingestion'
          : 'ResourceGraphDefinition not configured - this is required for Kro'
      );
    }

    // Check Kro plugin configuration
    const kroConfig = config.kro;
    logResult(
      'Kro Plugin Config',
      !!kroConfig,
      kroConfig
        ? 'Kro plugin configuration found'
        : 'Missing kro plugin configuration'
    );

    if (kroConfig) {
      const clusters = kroConfig.clusters || [];
      logResult(
        'Kro Clusters Config',
        clusters.length > 0,
        clusters.length > 0
          ? `Found ${clusters.length} cluster(s) configured for Kro`
          : 'No clusters configured for Kro plugin'
      );

      const entityProcessing = kroConfig.entityProcessing;
      logResult(
        'Entity Processing Config',
        entityProcessing?.enabled === true,
        entityProcessing?.enabled === true
          ? 'Entity processing enabled for ResourceGroups'
          : 'Entity processing not enabled - ResourceGroups may not appear in catalog'
      );
    }

    // Check catalog locations
    const locations = config.catalog?.locations || [];
    const hasKroEntities = locations.some(loc =>
      loc.target?.includes('kro-resource-groups.yaml')
    );

    logResult(
      'Catalog Locations',
      hasKroEntities,
      hasKroEntities
        ? 'Kro ResourceGroup entities file is configured in catalog locations'
        : 'Kro ResourceGroup entities file not found in catalog locations'
    );

  } catch (error) {
    logResult('App Config Validation', false, `Failed to parse app-config.yaml: ${error.message}`);
  }
}

function validateEntitiesFile() {
  console.log('\n🔍 Validating kro-resource-groups.yaml...');

  try {
    const entitiesContent = fs.readFileSync(ENTITIES_PATH, 'utf8');
    const entities = yaml.loadAll(entitiesContent);

    logResult(
      'Entities File',
      entities.length > 0,
      entities.length > 0
        ? `Found ${entities.length} entities in kro-resource-groups.yaml`
        : 'No entities found in kro-resource-groups.yaml'
    );

    let kroComponents = 0;
    let systems = 0;

    entities.forEach((entity, index) => {
      if (!entity) return;

      // Validate entity structure
      const hasApiVersion = !!entity.apiVersion;
      const hasKind = !!entity.kind;
      const hasMetadata = !!entity.metadata?.name;

      logResult(
        `Entity ${index + 1} Structure`,
        hasApiVersion && hasKind && hasMetadata,
        hasApiVersion && hasKind && hasMetadata
          ? `Entity ${entity.metadata?.name} has valid structure`
          : `Entity ${index + 1} missing required fields`
      );

      // Check for Kro-specific annotations
      if (entity.kind === 'Component' && entity.spec?.type === 'kro-resource-group') {
        kroComponents++;

        const hasKroAnnotations = !!(
          entity.metadata?.annotations?.['kro.run/resource-group'] &&
          entity.metadata?.annotations?.['backstage.io/kubernetes-id']
        );

        logResult(
          `Kro Component ${entity.metadata?.name}`,
          hasKroAnnotations,
          hasKroAnnotations
            ? 'Has required Kro annotations'
            : 'Missing required Kro annotations'
        );
      }

      if (entity.kind === 'System') {
        systems++;
      }
    });

    logResult(
      'Kro Components',
      kroComponents > 0,
      kroComponents > 0
        ? `Found ${kroComponents} Kro ResourceGroup components`
        : 'No Kro ResourceGroup components found'
    );

    logResult(
      'Systems',
      systems > 0,
      systems > 0
        ? `Found ${systems} system(s) for organizing ResourceGroups`
        : 'No systems found - consider adding systems for better organization'
    );

  } catch (error) {
    if (error.code === 'ENOENT') {
      logResult('Entities File', false, 'kro-resource-groups.yaml file not found');
    } else {
      logResult('Entities File Validation', false, `Failed to parse kro-resource-groups.yaml: ${error.message}`);
    }
  }
}

function validateBackendConfiguration() {
  console.log('\n🔍 Validating backend configuration...');

  try {
    const backendContent = fs.readFileSync(BACKEND_INDEX_PATH, 'utf8');

    // Check for required imports
    const hasKroModule = backendContent.includes('catalogKroModule');
    const hasIngestorModule = backendContent.includes('kubernetesIngestorKroModule');
    const hasKubernetesIngestor = backendContent.includes('@terasky/backstage-plugin-kubernetes-ingestor');
    const hasKroBackend = backendContent.includes('@terasky/backstage-plugin-kro-resources-backend');

    logResult(
      'Kro Catalog Module',
      hasKroModule,
      hasKroModule
        ? 'Kro catalog module is imported and registered'
        : 'Kro catalog module not found - ResourceGroup processing may not work'
    );

    logResult(
      'Kubernetes Ingestor Kro Module',
      hasIngestorModule,
      hasIngestorModule
        ? 'Kubernetes Ingestor Kro integration module is registered'
        : 'Kubernetes Ingestor Kro integration module not found'
    );

    logResult(
      'Kubernetes Ingestor Plugin',
      hasKubernetesIngestor,
      hasKubernetesIngestor
        ? 'Kubernetes Ingestor plugin is registered'
        : 'Kubernetes Ingestor plugin not found - ResourceGroup discovery will not work'
    );

    logResult(
      'Kro Backend Plugin',
      hasKroBackend,
      hasKroBackend
        ? 'Kro backend plugin is registered'
        : 'Kro backend plugin not found - ResourceGroup management will not work'
    );

  } catch (error) {
    logResult('Backend Config Validation', false, `Failed to read backend index.ts: ${error.message}`);
  }
}

function validateFileStructure() {
  console.log('\n🔍 Validating file structure...');

  const requiredFiles = [
    'packages/backend/src/plugins/catalog-processors/kro-resource-group-processor.ts',
    'packages/backend/src/plugins/catalog-kro-module.ts',
    'packages/backend/src/plugins/kro-entity-transformer.ts',
    'packages/backend/src/plugins/kubernetes-ingestor-kro-module.ts',
    'examples/kro-resource-groups.yaml'
  ];

  requiredFiles.forEach(file => {
    const fullPath = path.join(__dirname, '..', file);
    const exists = fs.existsSync(fullPath);

    logResult(
      `File: ${file}`,
      exists,
      exists ? 'File exists' : 'File missing'
    );
  });
}

function printSummary() {
  console.log('\n📊 Validation Summary');
  console.log('='.repeat(50));
  console.log(`✅ Passed: ${results.passed}`);
  console.log(`❌ Failed: ${results.failed}`);
  console.log(`⚠️  Warnings: ${results.warnings}`);

  if (results.failed > 0) {
    console.log('\n❌ Errors found:');
    results.errors.forEach(error => console.log(`  - ${error}`));
    console.log('\nPlease fix the errors above before proceeding.');
    process.exit(1);
  } else if (results.warnings > 0) {
    console.log('\n⚠️  Warnings found - review the warnings above.');
  } else {
    console.log('\n🎉 All validations passed! Kro catalog integration is properly configured.');
  }
}

// Run validations
console.log('🚀 Starting Kro Catalog Integration Validation...');

validateFileStructure();
validateAppConfig();
validateEntitiesFile();
validateBackendConfiguration();

printSummary();