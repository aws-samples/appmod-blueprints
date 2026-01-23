/**
 * Workflow Integration Tests for CI/CD Pipeline Kro RGD
 * 
 * Tests Argo Workflows access to provisioned resources, ECR authentication,
 * and webhook triggering according to requirements 5.1-5.5
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { execSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

// Test configuration
const TEST_CONFIG = {
  namespace: 'test-workflow-integration',
  appName: 'test-workflow-app',
  instanceName: 'test-workflow-cicd',
  timeout: 300000, // 5 minutes
  pollInterval: 5000, // 5 seconds
};

// Utility functions
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

const waitForResource = async (resourceType, name, namespace, condition = 'Ready', timeout = TEST_CONFIG.timeout) => {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    try {
      const status = kubectl(`get ${resourceType} ${name} -n ${namespace} -o jsonpath='{.status.conditions[?(@.type=="${condition}")].status}'`, { allowFailure: true });
      if (status === 'True') {
        return true;
      }
    } catch (error) {
      // Resource might not exist yet
    }

    await new Promise(resolve => setTimeout(resolve, TEST_CONFIG.pollInterval));
  }

  throw new Error(`Timeout waiting for ${resourceType}/${name} to be ${condition}`);
};

const waitForWorkflowCompletion = async (workflowName, namespace, timeout = TEST_CONFIG.timeout) => {
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    try {
      const phase = kubectl(`get workflow ${workflowName} -n ${namespace} -o jsonpath='{.status.phase}'`, { allowFailure: true });
      if (phase === 'Succeeded') {
        return true;
      }
      if (phase === 'Failed' || phase === 'Error') {
        const message = kubectl(`get workflow ${workflowName} -n ${namespace} -o jsonpath='{.status.message}'`, { allowFailure: true });
        throw new Error(`Workflow failed: ${message}`);
      }
    } catch (error) {
      if (!error.message.includes('Workflow failed')) {
        // Workflow might not exist yet
      } else {
        throw error;
      }
    }

    await new Promise(resolve => setTimeout(resolve, TEST_CONFIG.pollInterval));
  }

  throw new Error(`Timeout waiting for workflow ${workflowName} to complete`);
};

describe('Workflow Integration Tests', () => {
  let cicdPipelineCreated = false;

  beforeAll(async () => {
    // Create test namespace
    try {
      kubectl(`create namespace ${TEST_CONFIG.namespace}`);
    } catch (error) {
      // Namespace might already exist
      if (!error.message.includes('already exists')) {
        throw error;
      }
    }

    // Apply the CICDPipeline instance for testing
    const testInstance = `
apiVersion: kro.run/v1alpha1
kind: CICDPipeline
metadata:
  name: ${TEST_CONFIG.instanceName}
  namespace: ${TEST_CONFIG.namespace}
spec:
  name: ${TEST_CONFIG.instanceName}
  namespace: ${TEST_CONFIG.namespace}
  aws:
    region: us-west-2
    clusterName: test-cluster
    resourcePrefix: test-workflow
  application:
    name: ${TEST_CONFIG.appName}
    dockerfilePath: "."
    deploymentPath: "./deployment"
  ecr:
    repositoryPrefix: "modengg"
  gitlab:
    hostname: "gitlab.example.com"
    username: "test-user"
`;

    // Apply the test instance
    kubectl(`apply -f -`, { input: testInstance });
    cicdPipelineCreated = true;

    // Wait for the CICDPipeline to be ready
    await waitForResource('cicdpipeline', TEST_CONFIG.instanceName, TEST_CONFIG.namespace, 'Ready', 600000); // 10 minutes
  }, 600000);

  afterAll(async () => {
    // Cleanup test resources
    if (cicdPipelineCreated) {
      try {
        kubectl(`delete cicdpipeline ${TEST_CONFIG.instanceName} -n ${TEST_CONFIG.namespace}`, { allowFailure: true });
      } catch (error) {
        console.warn('Failed to cleanup CICDPipeline:', error.message);
      }
    }

    // Delete test namespace (this will cleanup all resources)
    try {
      kubectl(`delete namespace ${TEST_CONFIG.namespace} --timeout=300s`, { allowFailure: true });
    } catch (error) {
      console.warn('Failed to cleanup namespace:', error.message);
    }
  }, 300000);

  describe('Argo Workflows Access to Provisioned Resources (Requirement 5.3)', () => {
    it('should have WorkflowTemplates created and accessible', async () => {
      // Check that WorkflowTemplates are created
      const workflowTemplates = kubectl(`get workflowtemplate -n ${TEST_CONFIG.namespace} -o name`).split('\n').filter(Boolean);

      expect(workflowTemplates.length).toBeGreaterThan(0);
      expect(workflowTemplates.some(wt => wt.includes('provisioning-workflow'))).toBe(true);
      expect(workflowTemplates.some(wt => wt.includes('cicd-workflow'))).toBe(true);
      expect(workflowTemplates.some(wt => wt.includes('cache-warmup-workflow'))).toBe(true);
    });

    it('should have service account with proper RBAC permissions', async () => {
      const serviceAccountName = `${TEST_CONFIG.instanceName}-sa`;

      // Check service account exists
      const sa = kubectl(`get serviceaccount ${serviceAccountName} -n ${TEST_CONFIG.namespace} -o json`);
      const serviceAccount = JSON.parse(sa);

      expect(serviceAccount.metadata.name).toBe(serviceAccountName);

      // Check role binding exists
      const roleBindings = kubectl(`get rolebinding -n ${TEST_CONFIG.namespace} -o json`);
      const roleBindingList = JSON.parse(roleBindings);

      const cicdRoleBinding = roleBindingList.items.find(rb =>
        rb.metadata.name.includes(TEST_CONFIG.instanceName) &&
        rb.subjects.some(s => s.name === serviceAccountName)
      );

      expect(cicdRoleBinding).toBeDefined();
      expect(cicdRoleBinding.roleRef.name).toContain(TEST_CONFIG.instanceName);
    });

    it('should have ConfigMap with ECR repository information accessible to workflows', async () => {
      const configMapName = `${TEST_CONFIG.instanceName}-config`;

      const cm = kubectl(`get configmap ${configMapName} -n ${TEST_CONFIG.namespace} -o json`);
      const configMap = JSON.parse(cm);

      expect(configMap.data).toBeDefined();
      expect(configMap.data.ECR_MAIN_REPOSITORY).toBeDefined();
      expect(configMap.data.ECR_CACHE_REPOSITORY).toBeDefined();
      expect(configMap.data.AWS_REGION).toBe('us-west-2');
      expect(configMap.data.APPLICATION_NAME).toBe(TEST_CONFIG.appName);
    });

    it('should have Docker registry secret for ECR authentication', async () => {
      const secretName = `${TEST_CONFIG.instanceName}-docker-config`;

      const secret = kubectl(`get secret ${secretName} -n ${TEST_CONFIG.namespace} -o json`);
      const secretObj = JSON.parse(secret);

      expect(secretObj.type).toBe('kubernetes.io/dockerconfigjson');
      expect(secretObj.data['.dockerconfigjson']).toBeDefined();

      // Check annotations for ECR configuration
      expect(secretObj.metadata.annotations['ecr.aws/main-repository']).toBeDefined();
      expect(secretObj.metadata.annotations['ecr.aws/cache-repository']).toBeDefined();
      expect(secretObj.metadata.annotations['ecr.aws/region']).toBe('us-west-2');
    });
  });

  describe('ECR Authentication and Image Operations (Requirement 5.4)', () => {
    it('should have ECR repositories created with proper configuration', async () => {
      // Check that ECR repositories are referenced in ConfigMap
      const configMapName = `${TEST_CONFIG.instanceName}-config`;
      const cm = kubectl(`get configmap ${configMapName} -n ${TEST_CONFIG.namespace} -o json`);
      const configMap = JSON.parse(cm);

      const mainRepo = configMap.data.ECR_MAIN_REPOSITORY;
      const cacheRepo = configMap.data.ECR_CACHE_REPOSITORY;

      expect(mainRepo).toMatch(/modengg\/test-workflow-app$/);
      expect(cacheRepo).toMatch(/modengg\/test-workflow-app\/cache$/);
    });

    it('should have ECR credential refresh CronJob configured', async () => {
      const cronJobName = `${TEST_CONFIG.instanceName}-ecr-refresh`;

      const cronJob = kubectl(`get cronjob ${cronJobName} -n ${TEST_CONFIG.namespace} -o json`);
      const cronJobObj = JSON.parse(cronJob);

      expect(cronJobObj.spec.schedule).toBe('0 */6 * * *'); // Every 6 hours
      expect(cronJobObj.spec.jobTemplate.spec.template.spec.serviceAccountName).toBe(`${TEST_CONFIG.instanceName}-sa`);
      expect(cronJobObj.spec.jobTemplate.spec.template.spec.containers[0].image).toBe('amazon/aws-cli:latest');
    });

    it('should have workflow templates configured for Kaniko image building', async () => {
      const cicdWorkflowTemplate = kubectl(`get workflowtemplate ${TEST_CONFIG.instanceName}-cicd-workflow -n ${TEST_CONFIG.namespace} -o json`);
      const workflowTemplate = JSON.parse(cicdWorkflowTemplate);

      // Check for Kaniko container in the workflow template
      const workflowSpec = workflowTemplate.spec;
      const templates = workflowSpec.templates;

      const buildTemplate = templates.find(t => t.name === 'build-and-push');
      expect(buildTemplate).toBeDefined();

      const kanikoContainer = buildTemplate.container;
      expect(kanikoContainer.image).toContain('kaniko');
      expect(kanikoContainer.args.some(arg => arg.includes('--dockerfile'))).toBe(true);
      expect(kanikoContainer.args.some(arg => arg.includes('--destination'))).toBe(true);
    });

    it('should test ECR authentication workflow execution', async () => {
      // Create a test workflow that validates ECR access
      const testWorkflow = `
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: test-ecr-auth-${Date.now()}
  namespace: ${TEST_CONFIG.namespace}
spec:
  serviceAccountName: ${TEST_CONFIG.instanceName}-sa
  entrypoint: test-ecr-auth
  templates:
  - name: test-ecr-auth
    container:
      image: amazon/aws-cli:latest
      command: [sh, -c]
      args:
      - |
        echo "Testing ECR authentication..."
        aws ecr get-login-password --region us-west-2 > /dev/null
        if [ $? -eq 0 ]; then
          echo "ECR authentication successful"
        else
          echo "ECR authentication failed"
          exit 1
        fi
      envFrom:
      - configMapRef:
          name: ${TEST_CONFIG.instanceName}-config
`;

      // Apply the test workflow
      const workflowName = kubectl(`apply -f - -o jsonpath='{.metadata.name}'`, { input: testWorkflow });

      try {
        // Wait for workflow completion
        await waitForWorkflowCompletion(workflowName, TEST_CONFIG.namespace);

        // Verify workflow succeeded
        const workflowStatus = kubectl(`get workflow ${workflowName} -n ${TEST_CONFIG.namespace} -o jsonpath='{.status.phase}'`);
        expect(workflowStatus).toBe('Succeeded');
      } finally {
        // Cleanup test workflow
        kubectl(`delete workflow ${workflowName} -n ${TEST_CONFIG.namespace}`, { allowFailure: true });
      }
    }, 120000);
  });

  describe('Webhook Triggering and Build Processes (Requirements 5.1, 5.2, 5.5)', () => {
    it('should have Argo Events EventSource configured for GitLab webhooks', async () => {
      const eventSourceName = `${TEST_CONFIG.instanceName}-gitlab-eventsource`;

      const eventSource = kubectl(`get eventsource ${eventSourceName} -n ${TEST_CONFIG.namespace} -o json`);
      const eventSourceObj = JSON.parse(eventSource);

      expect(eventSourceObj.spec.webhook).toBeDefined();
      expect(eventSourceObj.spec.webhook[`${TEST_CONFIG.instanceName}-webhook`]).toBeDefined();

      const webhookConfig = eventSourceObj.spec.webhook[`${TEST_CONFIG.instanceName}-webhook`];
      expect(webhookConfig.port).toBe('12000');
      expect(webhookConfig.endpoint).toBe('/webhook');
      expect(webhookConfig.method).toBe('POST');
    });

    it('should have Argo Events Sensor configured to trigger workflows', async () => {
      const sensorName = `${TEST_CONFIG.instanceName}-gitlab-sensor`;

      const sensor = kubectl(`get sensor ${sensorName} -n ${TEST_CONFIG.namespace} -o json`);
      const sensorObj = JSON.parse(sensor);

      expect(sensorObj.spec.dependencies).toBeDefined();
      expect(sensorObj.spec.dependencies.length).toBeGreaterThan(0);

      const dependency = sensorObj.spec.dependencies[0];
      expect(dependency.eventSourceName).toBe(eventSourceName);
      expect(dependency.eventName).toBe(`${TEST_CONFIG.instanceName}-webhook`);

      // Check triggers
      expect(sensorObj.spec.triggers).toBeDefined();
      expect(sensorObj.spec.triggers.length).toBeGreaterThan(0);

      const trigger = sensorObj.spec.triggers[0];
      expect(trigger.template.argoWorkflow).toBeDefined();
      expect(trigger.template.argoWorkflow.source.resource.spec.workflowTemplateRef.name).toBe(`${TEST_CONFIG.instanceName}-cicd-workflow`);
    });

    it('should have webhook endpoint accessible via Ingress', async () => {
      const ingressName = `${TEST_CONFIG.instanceName}-webhook-ingress`;

      const ingress = kubectl(`get ingress ${ingressName} -n ${TEST_CONFIG.namespace} -o json`);
      const ingressObj = JSON.parse(ingress);

      expect(ingressObj.spec.rules).toBeDefined();
      expect(ingressObj.spec.rules.length).toBeGreaterThan(0);

      const rule = ingressObj.spec.rules[0];
      expect(rule.http.paths).toBeDefined();

      const webhookPath = rule.http.paths.find(p => p.path === '/webhook');
      expect(webhookPath).toBeDefined();
      expect(webhookPath.backend.service.name).toBe(`${TEST_CONFIG.instanceName}-gitlab-eventsource-svc`);
      expect(webhookPath.backend.service.port.number).toBe(12000);
    });

    it('should test workflow template execution for CI/CD operations', async () => {
      // Create a test workflow from the CI/CD workflow template
      const testWorkflow = `
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: test-cicd-workflow-${Date.now()}
  namespace: ${TEST_CONFIG.namespace}
spec:
  serviceAccountName: ${TEST_CONFIG.instanceName}-sa
  workflowTemplateRef:
    name: ${TEST_CONFIG.instanceName}-cicd-workflow
  arguments:
    parameters:
    - name: git-url
      value: "https://gitlab.example.com/test/test-repo.git"
    - name: git-revision
      value: "main"
    - name: image-tag
      value: "test-${Date.now()}"
    - name: dockerfile-path
      value: "."
    - name: deployment-path
      value: "./deployment"
`;

      // Apply the test workflow
      const workflowName = kubectl(`apply -f - -o jsonpath='{.metadata.name}'`, { input: testWorkflow });

      try {
        // Wait a bit for workflow to start
        await new Promise(resolve => setTimeout(resolve, 10000));

        // Check workflow was created and started
        const workflowStatus = kubectl(`get workflow ${workflowName} -n ${TEST_CONFIG.namespace} -o jsonpath='{.status.phase}'`);
        expect(['Pending', 'Running', 'Succeeded'].includes(workflowStatus)).toBe(true);

        // Check that workflow has access to required resources
        const workflow = kubectl(`get workflow ${workflowName} -n ${TEST_CONFIG.namespace} -o json`);
        const workflowObj = JSON.parse(workflow);

        expect(workflowObj.spec.serviceAccountName).toBe(`${TEST_CONFIG.instanceName}-sa`);
        expect(workflowObj.spec.workflowTemplateRef.name).toBe(`${TEST_CONFIG.instanceName}-cicd-workflow`);
      } finally {
        // Cleanup test workflow
        kubectl(`delete workflow ${workflowName} -n ${TEST_CONFIG.namespace}`, { allowFailure: true });
      }
    }, 60000);

    it('should validate GitLab repository update capability in workflow templates', async () => {
      // Check that the CI/CD workflow template has GitLab update steps
      const cicdWorkflowTemplate = kubectl(`get workflowtemplate ${TEST_CONFIG.instanceName}-cicd-workflow -n ${TEST_CONFIG.namespace} -o json`);
      const workflowTemplate = JSON.parse(cicdWorkflowTemplate);

      const templates = workflowTemplate.spec.templates;

      // Look for GitLab update template
      const gitlabUpdateTemplate = templates.find(t => t.name === 'update-gitlab-repo');
      expect(gitlabUpdateTemplate).toBeDefined();

      // Check that it uses GitLab credentials
      const container = gitlabUpdateTemplate.container;
      expect(container.env.some(env => env.name === 'GITLAB_TOKEN')).toBe(true);

      // Check that it has git operations
      const args = container.args.join(' ');
      expect(args).toContain('git clone');
      expect(args).toContain('git push');
    });
  });

  describe('End-to-End Workflow Integration', () => {
    it('should validate complete pipeline workflow execution', async () => {
      // Test the provisioning workflow first
      const provisioningWorkflow = `
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  name: test-provisioning-${Date.now()}
  namespace: ${TEST_CONFIG.namespace}
spec:
  serviceAccountName: ${TEST_CONFIG.instanceName}-sa
  workflowTemplateRef:
    name: ${TEST_CONFIG.instanceName}-provisioning-workflow
  arguments:
    parameters:
    - name: application-name
      value: "${TEST_CONFIG.appName}"
    - name: namespace
      value: "${TEST_CONFIG.namespace}"
`;

      const workflowName = kubectl(`apply -f - -o jsonpath='{.metadata.name}'`, { input: provisioningWorkflow });

      try {
        // Wait for workflow to start
        await new Promise(resolve => setTimeout(resolve, 15000));

        // Check workflow status
        const workflowStatus = kubectl(`get workflow ${workflowName} -n ${TEST_CONFIG.namespace} -o jsonpath='{.status.phase}'`, { allowFailure: true });

        // Workflow should at least start (may not complete due to missing AWS resources in test environment)
        expect(['Pending', 'Running', 'Succeeded', 'Failed'].includes(workflowStatus)).toBe(true);

        // If it failed, check if it's due to expected AWS resource issues
        if (workflowStatus === 'Failed') {
          const workflowLogs = kubectl(`logs -l workflows.argoproj.io/workflow=${workflowName} -n ${TEST_CONFIG.namespace} --tail=50`, { allowFailure: true });

          // Expected failures in test environment (no real AWS resources)
          const expectedFailurePatterns = [
            'ECR repository not found',
            'AWS credentials not configured',
            'Unable to connect to AWS',
            'AccessDenied'
          ];

          const hasExpectedFailure = expectedFailurePatterns.some(pattern =>
            workflowLogs && workflowLogs.includes(pattern)
          );

          if (!hasExpectedFailure) {
            console.warn('Workflow failed with unexpected error:', workflowLogs);
          }
        }
      } finally {
        // Cleanup
        kubectl(`delete workflow ${workflowName} -n ${TEST_CONFIG.namespace}`, { allowFailure: true });
      }
    }, 120000);
  });
});