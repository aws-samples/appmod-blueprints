/**
 * Utility functions for workflow integration testing
 */

import { execSync } from 'child_process';

// Kubernetes utility functions
export const kubectl = (command, options = {}) => {
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

// Wait for resource to be ready
export const waitForResource = async (resourceType, name, namespace, condition = 'Ready', timeout = 300000) => {
  const startTime = Date.now();
  const pollInterval = 5000;

  console.log(`Waiting for ${resourceType}/${name} to be ${condition} in namespace ${namespace}...`);

  while (Date.now() - startTime < timeout) {
    try {
      const status = kubectl(`get ${resourceType} ${name} -n ${namespace} -o jsonpath='{.status.conditions[?(@.type=="${condition}")].status}'`, { allowFailure: true });
      if (status === 'True') {
        console.log(`✅ ${resourceType}/${name} is ${condition}`);
        return true;
      }

      // Also check for alternative status paths
      if (condition === 'Ready') {
        const phase = kubectl(`get ${resourceType} ${name} -n ${namespace} -o jsonpath='{.status.phase}'`, { allowFailure: true });
        if (phase === 'Active' || phase === 'Succeeded') {
          console.log(`✅ ${resourceType}/${name} is ${phase}`);
          return true;
        }
      }
    } catch (error) {
      // Resource might not exist yet
    }

    await new Promise(resolve => setTimeout(resolve, pollInterval));
  }

  throw new Error(`Timeout waiting for ${resourceType}/${name} to be ${condition}`);
};

// Wait for workflow completion
export const waitForWorkflowCompletion = async (workflowName, namespace, timeout = 300000) => {
  const startTime = Date.now();
  const pollInterval = 5000;

  console.log(`Waiting for workflow ${workflowName} to complete in namespace ${namespace}...`);

  while (Date.now() - startTime < timeout) {
    try {
      const phase = kubectl(`get workflow ${workflowName} -n ${namespace} -o jsonpath='{.status.phase}'`, { allowFailure: true });

      if (phase === 'Succeeded') {
        console.log(`✅ Workflow ${workflowName} succeeded`);
        return true;
      }

      if (phase === 'Failed' || phase === 'Error') {
        const message = kubectl(`get workflow ${workflowName} -n ${namespace} -o jsonpath='{.status.message}'`, { allowFailure: true });
        throw new Error(`Workflow failed: ${message}`);
      }

      // Log progress
      if (phase && phase !== 'Pending') {
        console.log(`Workflow ${workflowName} status: ${phase}`);
      }

    } catch (error) {
      if (!error.message.includes('Workflow failed')) {
        // Workflow might not exist yet
      } else {
        throw error;
      }
    }

    await new Promise(resolve => setTimeout(resolve, pollInterval));
  }

  throw new Error(`Timeout waiting for workflow ${workflowName} to complete`);
};

// Create test workflow from template
export const createTestWorkflow = (templateName, namespace, parameters = {}) => {
  const timestamp = Date.now();
  const workflowName = `test-${templateName}-${timestamp}`;

  const parameterList = Object.entries(parameters).map(([name, value]) =>
    `    - name: ${name}\n      value: "${value}"`
  ).join('\n');

  const workflowYaml = `
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: ${workflowName}
  namespace: ${namespace}
spec:
  serviceAccountName: test-workflow-cicd-sa
  workflowTemplateRef:
    name: ${templateName}
  arguments:
    parameters:
${parameterList}
`;

  return { workflowName, workflowYaml };
};

// Get workflow logs
export const getWorkflowLogs = (workflowName, namespace) => {
  try {
    return kubectl(`logs -l workflows.argoproj.io/workflow=${workflowName} -n ${namespace} --tail=100`, { allowFailure: true });
  } catch (error) {
    return `Failed to get logs: ${error.message}`;
  }
};

// Check if resource exists
export const resourceExists = (resourceType, name, namespace) => {
  const result = kubectl(`get ${resourceType} ${name} -n ${namespace}`, { allowFailure: true });
  return result !== null;
};

// Get resource status
export const getResourceStatus = (resourceType, name, namespace) => {
  try {
    const resource = kubectl(`get ${resourceType} ${name} -n ${namespace} -o json`);
    return JSON.parse(resource);
  } catch (error) {
    return null;
  }
};

// Validate ECR repository configuration
export const validateECRConfig = (configMap) => {
  const requiredFields = [
    'ECR_MAIN_REPOSITORY',
    'ECR_CACHE_REPOSITORY',
    'AWS_REGION',
    'APPLICATION_NAME'
  ];

  for (const field of requiredFields) {
    if (!configMap.data[field]) {
      throw new Error(`Missing required field in ConfigMap: ${field}`);
    }
  }

  // Validate repository naming convention
  const mainRepo = configMap.data.ECR_MAIN_REPOSITORY;
  const cacheRepo = configMap.data.ECR_CACHE_REPOSITORY;

  if (!mainRepo.includes('modengg/')) {
    throw new Error(`Main repository does not follow naming convention: ${mainRepo}`);
  }

  if (!cacheRepo.includes('/cache')) {
    throw new Error(`Cache repository does not follow naming convention: ${cacheRepo}`);
  }

  return true;
};

// Validate workflow template structure
export const validateWorkflowTemplate = (workflowTemplate, expectedTemplates = []) => {
  if (!workflowTemplate.spec || !workflowTemplate.spec.templates) {
    throw new Error('WorkflowTemplate missing spec.templates');
  }

  const templates = workflowTemplate.spec.templates;
  const templateNames = templates.map(t => t.name);

  for (const expectedTemplate of expectedTemplates) {
    if (!templateNames.includes(expectedTemplate)) {
      throw new Error(`WorkflowTemplate missing expected template: ${expectedTemplate}`);
    }
  }

  return true;
};

// Validate RBAC permissions
export const validateRBACPermissions = (roleBinding, expectedPermissions = []) => {
  if (!roleBinding.roleRef) {
    throw new Error('RoleBinding missing roleRef');
  }

  if (!roleBinding.subjects || roleBinding.subjects.length === 0) {
    throw new Error('RoleBinding missing subjects');
  }

  return true;
};

// Clean up test resources
export const cleanupTestResources = async (namespace, resourceTypes = ['workflow', 'job', 'pod']) => {
  console.log(`Cleaning up test resources in namespace ${namespace}...`);

  for (const resourceType of resourceTypes) {
    try {
      const resources = kubectl(`get ${resourceType} -n ${namespace} -o name`, { allowFailure: true });
      if (resources) {
        const resourceList = resources.split('\n').filter(Boolean);
        for (const resource of resourceList) {
          if (resource.includes('test-')) {
            console.log(`Deleting ${resource}...`);
            kubectl(`delete ${resource} -n ${namespace} --timeout=60s`, { allowFailure: true });
          }
        }
      }
    } catch (error) {
      console.warn(`Failed to cleanup ${resourceType}: ${error.message}`);
    }
  }

  console.log('✅ Test resource cleanup completed');
};

// Generate test parameters
export const generateTestParameters = (appName = 'test-app', namespace = 'test-namespace') => {
  const timestamp = Date.now();

  return {
    'application-name': appName,
    'namespace': namespace,
    'git-url': 'https://gitlab.example.com/test/test-repo.git',
    'git-revision': 'main',
    'image-tag': `test-${timestamp}`,
    'dockerfile-path': '.',
    'deployment-path': './deployment'
  };
};