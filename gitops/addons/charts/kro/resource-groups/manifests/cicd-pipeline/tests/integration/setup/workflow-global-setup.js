/**
 * Global setup for workflow integration tests
 * Ensures required CRDs and controllers are available
 */

import { execSync } from 'child_process';

const kubectl = (command, options = {}) => {
  try {
    const result = execSync(`kubectl ${command}`, {
      encoding: 'utf8',
      timeout: 30000,
      ...options
    });
    return result.trim();
  } catch (error) {
    if (options.allowFailure) {
      return null;
    }
    throw error;
  }
};

const checkCRD = (crdName, description) => {
  console.log(`Checking for ${description}...`);
  const result = kubectl(`get crd ${crdName}`, { allowFailure: true });
  if (!result) {
    console.warn(`⚠️  ${description} not found. Some tests may fail.`);
    return false;
  }
  console.log(`✅ ${description} found`);
  return true;
};

const checkNamespace = (namespace) => {
  console.log(`Checking for namespace ${namespace}...`);
  const result = kubectl(`get namespace ${namespace}`, { allowFailure: true });
  if (!result) {
    console.log(`Creating namespace ${namespace}...`);
    kubectl(`create namespace ${namespace}`);
  }
  console.log(`✅ Namespace ${namespace} ready`);
};

export async function setup() {
  console.log('🚀 Setting up workflow integration test environment...');

  try {
    // Check cluster connectivity
    console.log('Checking cluster connectivity...');
    kubectl('cluster-info');
    console.log('✅ Cluster connectivity verified');

    // Check required CRDs
    const requiredCRDs = [
      { name: 'ResourceGraphDefinitiondefinitions.kro.run', description: 'Kro ResourceGraphDefinitionDefinitions' },
      { name: 'workflows.argoproj.io', description: 'Argo Workflows' },
      { name: 'workflowtemplates.argoproj.io', description: 'Argo WorkflowTemplates' },
      { name: 'eventsources.argoproj.io', description: 'Argo Events EventSources' },
      { name: 'sensors.argoproj.io', description: 'Argo Events Sensors' },
    ];

    let allCRDsPresent = true;
    for (const crd of requiredCRDs) {
      if (!checkCRD(crd.name, crd.description)) {
        allCRDsPresent = false;
      }
    }

    // Check optional ACK CRDs
    const optionalCRDs = [
      { name: 'repositories.ecr.services.k8s.aws', description: 'ACK ECR Controller' },
      { name: 'policies.iam.services.k8s.aws', description: 'ACK IAM Controller' },
      { name: 'roles.iam.services.k8s.aws', description: 'ACK IAM Controller (Roles)' },
      { name: 'podidentityassociations.eks.services.k8s.aws', description: 'ACK EKS Controller' },
    ];

    for (const crd of optionalCRDs) {
      checkCRD(crd.name, crd.description);
    }

    if (!allCRDsPresent) {
      console.warn('⚠️  Some required CRDs are missing. Tests may fail.');
    }

    // Check if the CI/CD Pipeline RGD is installed
    console.log('Checking for CI/CD Pipeline ResourceGraphDefinitionDefinition...');
    const rgdResult = kubectl('get rgd cicdpipeline', { allowFailure: true });
    if (!rgdResult) {
      console.warn('⚠️  CI/CD Pipeline RGD not found. Please install it first.');
      console.warn('   Run: kubectl apply -f cicd-pipeline.yaml');
    } else {
      console.log('✅ CI/CD Pipeline RGD found');
    }

    console.log('✅ Global setup completed successfully');

  } catch (error) {
    console.error('❌ Global setup failed:', error.message);
    throw error;
  }
}

export async function teardown() {
  console.log('🧹 Running global teardown...');

  try {
    // Cleanup any leftover test resources
    const testNamespaces = ['test-workflow-integration'];

    for (const namespace of testNamespaces) {
      const exists = kubectl(`get namespace ${namespace}`, { allowFailure: true });
      if (exists) {
        console.log(`Cleaning up test namespace: ${namespace}`);
        kubectl(`delete namespace ${namespace} --timeout=300s`, { allowFailure: true });
      }
    }

    console.log('✅ Global teardown completed');

  } catch (error) {
    console.warn('⚠️  Global teardown encountered errors:', error.message);
  }
}