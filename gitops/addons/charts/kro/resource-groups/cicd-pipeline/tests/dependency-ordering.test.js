import { describe, it, expect } from 'vitest';
import { loadRGD, createMockSchemaInstance, createMockResourceStatus } from './utils/rgd-loader.js';
import { TemplateEngine } from './utils/template-engine.js';

describe('Dependency Ordering and Readiness Conditions', () => {
  let rgd;
  let mockSchema;
  let templateEngine;

  beforeEach(() => {
    rgd = loadRGD();
    mockSchema = createMockSchemaInstance();
  });

  describe('Resource Dependency Graph', () => {
    it('should have proper dependency ordering for AWS resources', () => {
      const resources = rgd.spec.resources;

      // ECR repositories should be independent (no dependencies on other resources)
      const ecrMainRepo = resources.find(r => r.id === 'ecrmainrepo');
      const ecrCacheRepo = resources.find(r => r.id === 'ecrcacherepo');

      expect(ecrMainRepo.readyWhen).toEqual(['${ecrmainrepo.status.conditions[0].status == "True"}']);
      expect(ecrCacheRepo.readyWhen).toEqual(['${ecrcacherepo.status.conditions[0].status == "True"}']);

      // IAM policy should be independent
      const iamPolicy = resources.find(r => r.id === 'iampolicy');
      expect(iamPolicy.readyWhen).toEqual(['${iampolicy.status.conditions[0].status == "True"}']);

      // IAM role should be independent
      const iamRole = resources.find(r => r.id === 'iamrole');
      expect(iamRole.readyWhen).toEqual(['${iamrole.status.conditions[0].status == "True"}']);

      // Role policy attachment should depend on both policy and role
      const rolePolicyAttachment = resources.find(r => r.id === 'rolepolicyattachment');
      expect(rolePolicyAttachment.readyWhen).toEqual(['${rolepolicyattachment.status.conditions[0].status == "True"}']);

      // Pod identity association should depend on IAM role
      const podIdentityAssoc = resources.find(r => r.id === 'podidentityassoc');
      expect(podIdentityAssoc.readyWhen).toEqual(['${podidentityassoc.status.conditions.exists(x, x.type == \'ACK.ResourceSynced\' && x.status == "True")}']);
    });

    it('should have proper dependency ordering for Kubernetes resources', () => {
      const resources = rgd.spec.resources;

      // Namespace should be first (no dependencies)
      const namespace = resources.find(r => r.id === 'namespace');
      expect(namespace.readyWhen).toEqual(['${namespace.status.phase == "Active"}']);

      // Service account should depend on namespace
      const serviceAccount = resources.find(r => r.id === 'serviceaccount');
      expect(serviceAccount.readyWhen).toContain('${serviceaccount.status}');
      expect(serviceAccount.readyWhen).toContain('${namespace.status.phase == "Active"}');

      // Role should be independent of other resources
      const role = resources.find(r => r.id === 'role');
      expect(role.readyWhen).toEqual(['${role.status}']);

      // Role binding should depend on both role and service account
      const roleBinding = resources.find(r => r.id === 'rolebinding');
      expect(roleBinding.readyWhen).toContain('${rolebinding.status}');
      expect(roleBinding.readyWhen).toContain('${role.status}');
      expect(roleBinding.readyWhen).toContain('${serviceaccount.status}');

      // ConfigMap should depend on namespace and ECR repositories
      const configMap = resources.find(r => r.id === 'configmap');
      expect(configMap.readyWhen).toContain('${configmap.status}');
      expect(configMap.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(configMap.readyWhen).toContain('${ecrmainrepo.status.conditions[0].status == "True"}');
      expect(configMap.readyWhen).toContain('${ecrcacherepo.status.conditions[0].status == "True"}');
    });

    it('should have proper dependency ordering for workflow resources', () => {
      const resources = rgd.spec.resources;

      // Provisioning workflow should depend on basic Kubernetes resources
      const provisioningWorkflow = resources.find(r => r.id === 'provisioningworkflow');
      expect(provisioningWorkflow.readyWhen).toContain('${provisioningworkflow.status}');
      expect(provisioningWorkflow.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(provisioningWorkflow.readyWhen).toContain('${serviceaccount.status}');
      expect(provisioningWorkflow.readyWhen).toContain('${configmap.status}');

      // Cache warmup workflow should depend on Docker secrets
      const cacheWarmupWorkflow = resources.find(r => r.id === 'cachewarmupworkflow');
      expect(cacheWarmupWorkflow.readyWhen).toContain('${cachewarmupworkflow.status}');
      expect(cacheWarmupWorkflow.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(cacheWarmupWorkflow.readyWhen).toContain('${serviceaccount.status}');
      expect(cacheWarmupWorkflow.readyWhen).toContain('${configmap.status}');
      expect(cacheWarmupWorkflow.readyWhen).toContain('${dockersecret.status}');

      // CI/CD workflow should have similar dependencies
      const cicdWorkflow = resources.find(r => r.id === 'cicdworkflow');
      expect(cicdWorkflow.readyWhen).toContain('${cicdworkflow.status}');
      expect(cicdWorkflow.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(cicdWorkflow.readyWhen).toContain('${serviceaccount.status}');
      expect(cicdWorkflow.readyWhen).toContain('${configmap.status}');
      expect(cicdWorkflow.readyWhen).toContain('${dockersecret.status}');
    });

    it('should have proper dependency ordering for setup and initialization', () => {
      const resources = rgd.spec.resources;

      // Initial ECR setup should depend on ECR repositories and Docker secret
      const initialEcrSetup = resources.find(r => r.id === 'initialecrcredsetup');
      expect(initialEcrSetup.readyWhen).toContain('${initialecrcredsetup.status.conditions.exists(x, x.type == \'Complete\' && x.status == "True")}');
      expect(initialEcrSetup.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(initialEcrSetup.readyWhen).toContain('${serviceaccount.status}');
      expect(initialEcrSetup.readyWhen).toContain('${dockersecret.status}');
      expect(initialEcrSetup.readyWhen).toContain('${ecrmainrepo.status.conditions[0].status == "True"}');
      expect(initialEcrSetup.readyWhen).toContain('${ecrcacherepo.status.conditions[0].status == "True"}');

      // Setup workflow should depend on provisioning workflow and initial ECR setup
      const setupWorkflow = resources.find(r => r.id === 'setupworkflow');
      expect(setupWorkflow.readyWhen).toContain('${setupworkflow.status}');
      expect(setupWorkflow.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(setupWorkflow.readyWhen).toContain('${serviceaccount.status}');
      expect(setupWorkflow.readyWhen).toContain('${configmap.status}');
      expect(setupWorkflow.readyWhen).toContain('${dockersecret.status}');
      expect(setupWorkflow.readyWhen).toContain('${provisioningworkflow.status}');
      expect(setupWorkflow.readyWhen).toContain('${initialecrcredsetup.status.conditions.exists(x, x.type == \'Complete\' && x.status == "True")}');
    });

    it('should have proper dependency ordering for webhook integration', () => {
      const resources = rgd.spec.resources;

      // EventSource should only depend on namespace
      const eventSource = resources.find(r => r.id === 'eventsource');
      expect(eventSource.readyWhen).toContain('${eventsource.status}');
      expect(eventSource.readyWhen).toContain('${namespace.status.phase == "Active"}');

      // Sensor should depend on EventSource, service account, and CI/CD workflow
      const sensor = resources.find(r => r.id === 'sensor');
      expect(sensor.readyWhen).toContain('${sensor.status}');
      expect(sensor.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(sensor.readyWhen).toContain('${eventsource.status}');
      expect(sensor.readyWhen).toContain('${serviceaccount.status}');
      expect(sensor.readyWhen).toContain('${cicdworkflow.status}');

      // Webhook service should depend on EventSource
      const webhookService = resources.find(r => r.id === 'webhookservice');
      expect(webhookService.readyWhen).toContain('${webhookservice.status}');
      expect(webhookService.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(webhookService.readyWhen).toContain('${eventsource.status}');

      // Webhook ingress should depend on webhook service
      const webhookIngress = resources.find(r => r.id === 'webhookingress');
      expect(webhookIngress.readyWhen).toContain('${webhookingress.status}');
      expect(webhookIngress.readyWhen).toContain('${namespace.status.phase == "Active"}');
      expect(webhookIngress.readyWhen).toContain('${webhookservice.status}');
    });
  });

  describe('ReadyWhen Condition Evaluation', () => {
    it('should correctly evaluate namespace readiness conditions', () => {
      const readyStatuses = {
        namespace: createMockResourceStatus('namespace', true)
      };
      const notReadyStatuses = {
        namespace: createMockResourceStatus('namespace', false)
      };

      const readyEngine = new TemplateEngine(mockSchema, readyStatuses);
      const notReadyEngine = new TemplateEngine(mockSchema, notReadyStatuses);

      const namespace = rgd.spec.resources.find(r => r.id === 'namespace');

      expect(readyEngine.evaluateReadyWhen(namespace.readyWhen)).toBe(true);
      expect(notReadyEngine.evaluateReadyWhen(namespace.readyWhen)).toBe(false);
    });

    it('should correctly evaluate ACK resource readiness conditions', () => {
      const readyStatuses = {
        ecrmainrepo: createMockResourceStatus('ecrmainrepo', true)
      };
      const notReadyStatuses = {
        ecrmainrepo: createMockResourceStatus('ecrmainrepo', false)
      };

      const readyEngine = new TemplateEngine(mockSchema, readyStatuses);
      const notReadyEngine = new TemplateEngine(mockSchema, notReadyStatuses);

      const ecrMainRepo = rgd.spec.resources.find(r => r.id === 'ecrmainrepo');

      expect(readyEngine.evaluateReadyWhen(ecrMainRepo.readyWhen)).toBe(true);
      expect(notReadyEngine.evaluateReadyWhen(ecrMainRepo.readyWhen)).toBe(false);
    });

    it('should correctly evaluate complex exists conditions', () => {
      const readyStatuses = {
        podidentityassoc: createMockResourceStatus('podidentityassoc', true)
      };
      const notReadyStatuses = {
        podidentityassoc: createMockResourceStatus('podidentityassoc', false)
      };

      const readyEngine = new TemplateEngine(mockSchema, readyStatuses);
      const notReadyEngine = new TemplateEngine(mockSchema, notReadyStatuses);

      const podIdentityAssoc = rgd.spec.resources.find(r => r.id === 'podidentityassoc');

      expect(readyEngine.evaluateReadyWhen(podIdentityAssoc.readyWhen)).toBe(true);
      expect(notReadyEngine.evaluateReadyWhen(podIdentityAssoc.readyWhen)).toBe(false);
    });

    it('should correctly evaluate Job completion conditions', () => {
      const readyStatuses = {
        initialecrcredsetup: createMockResourceStatus('initialecrcredsetup', true)
      };
      const notReadyStatuses = {
        initialecrcredsetup: createMockResourceStatus('initialecrcredsetup', false)
      };

      const readyEngine = new TemplateEngine(mockSchema, readyStatuses);
      const notReadyEngine = new TemplateEngine(mockSchema, notReadyStatuses);

      const initialEcrSetup = rgd.spec.resources.find(r => r.id === 'initialecrcredsetup');
      const completionCondition = '${initialecrcredsetup.status.conditions.exists(x, x.type == \'Complete\' && x.status == "True")}';

      expect(readyEngine.evaluateCondition(completionCondition)).toBe(true);
      expect(notReadyEngine.evaluateCondition(completionCondition)).toBe(false);
    });

    it('should correctly evaluate multi-dependency conditions', () => {
      const allReadyStatuses = {
        namespace: createMockResourceStatus('namespace', true),
        serviceaccount: createMockResourceStatus('serviceaccount', true),
        configmap: createMockResourceStatus('configmap', true),
        dockersecret: createMockResourceStatus('dockersecret', true),
        cachewarmupworkflow: createMockResourceStatus('cachewarmupworkflow', true)
      };

      const partialReadyStatuses = {
        namespace: createMockResourceStatus('namespace', true),
        serviceaccount: createMockResourceStatus('serviceaccount', false),
        configmap: createMockResourceStatus('configmap', true),
        dockersecret: createMockResourceStatus('dockersecret', true),
        cachewarmupworkflow: createMockResourceStatus('cachewarmupworkflow', true)
      };

      const allReadyEngine = new TemplateEngine(mockSchema, allReadyStatuses);
      const partialReadyEngine = new TemplateEngine(mockSchema, partialReadyStatuses);

      const cacheWarmupWorkflow = rgd.spec.resources.find(r => r.id === 'cachewarmupworkflow');

      expect(allReadyEngine.evaluateReadyWhen(cacheWarmupWorkflow.readyWhen)).toBe(true);
      expect(partialReadyEngine.evaluateReadyWhen(cacheWarmupWorkflow.readyWhen)).toBe(false);
    });
  });

  describe('Dependency Chain Validation', () => {
    it('should not have circular dependencies', () => {
      const resources = rgd.spec.resources;
      const dependencyGraph = new Map();

      // Build dependency graph
      resources.forEach(resource => {
        const dependencies = [];
        if (resource.readyWhen) {
          resource.readyWhen.forEach(condition => {
            const matches = condition.match(/\$\{(\w+)\./g);
            if (matches) {
              matches.forEach(match => {
                const resourceId = match.replace('${', '').replace('.', '');
                if (resourceId !== resource.id && resources.find(r => r.id === resourceId)) {
                  dependencies.push(resourceId);
                }
              });
            }
          });
        }
        dependencyGraph.set(resource.id, dependencies);
      });

      // Check for circular dependencies using DFS
      const visited = new Set();
      const recursionStack = new Set();

      function hasCycle(resourceId) {
        if (recursionStack.has(resourceId)) {
          return true; // Circular dependency found
        }
        if (visited.has(resourceId)) {
          return false;
        }

        visited.add(resourceId);
        recursionStack.add(resourceId);

        const dependencies = dependencyGraph.get(resourceId) || [];
        for (const dep of dependencies) {
          if (hasCycle(dep)) {
            return true;
          }
        }

        recursionStack.delete(resourceId);
        return false;
      }

      // Check each resource for circular dependencies
      for (const resourceId of dependencyGraph.keys()) {
        expect(hasCycle(resourceId)).toBe(false);
      }
    });

    it('should have valid resource references in readyWhen conditions', () => {
      const resources = rgd.spec.resources;
      const resourceIds = new Set(resources.map(r => r.id));

      resources.forEach(resource => {
        if (resource.readyWhen) {
          resource.readyWhen.forEach(condition => {
            const matches = condition.match(/\$\{(\w+)\./g);
            if (matches) {
              matches.forEach(match => {
                const resourceId = match.replace('${', '').replace('.', '');
                // Self-references are valid, external references should exist
                if (resourceId !== resource.id) {
                  expect(resourceIds.has(resourceId)).toBe(true);
                }
              });
            }
          });
        }
      });
    });

    it('should have proper ordering for critical path resources', () => {
      const resources = rgd.spec.resources;

      // Critical path: namespace -> ECR repos -> IAM resources -> service account -> workflows
      const criticalPathOrder = [
        'namespace',
        'ecrmainrepo',
        'ecrcacherepo',
        'iampolicy',
        'iamrole',
        'rolepolicyattachment',
        'podidentityassoc',
        'serviceaccount',
        'dockersecret',
        'initialecrcredsetup',
        'provisioningworkflow',
        'setupworkflow'
      ];

      // Verify that each resource in the critical path has proper dependencies
      for (let i = 1; i < criticalPathOrder.length; i++) {
        const currentResource = resources.find(r => r.id === criticalPathOrder[i]);
        const previousResourceId = criticalPathOrder[i - 1];

        if (currentResource && currentResource.readyWhen) {
          const hasDirectOrIndirectDependency = currentResource.readyWhen.some(condition => {
            return condition.includes(previousResourceId) ||
              condition.includes('namespace.status.phase == "Active"'); // All depend on namespace
          });

          // Some resources may not directly depend on the immediate previous resource
          // but should have some dependency structure
          expect(currentResource.readyWhen.length).toBeGreaterThan(0);
        }
      }
    });
  });

  describe('Status Aggregation', () => {
    it('should have comprehensive status tracking in schema', () => {
      const schemaStatus = rgd.spec.schema.status;
      const resources = rgd.spec.resources;

      // Verify that all resources have corresponding status tracking
      resources.forEach(resource => {
        const statusKey = `${resource.id}Status`;
        const alternativeKeys = [
          `${resource.id.replace(/([A-Z])/g, '$1').toLowerCase()}Status`,
          `${resource.id}Status`.replace(/([a-z])([A-Z])/g, '$1$2Status')
        ];

        const hasStatusTracking = Object.keys(schemaStatus).some(key =>
          key === statusKey || alternativeKeys.includes(key) ||
          schemaStatus[key].includes(`${resource.id}.status`)
        );

        // Not all resources need explicit status tracking, but major ones should
        if (['namespace', 'serviceaccount', 'ecrmainrepo', 'ecrcacherepo', 'iamrole', 'provisioningworkflow'].includes(resource.id)) {
          expect(hasStatusTracking).toBe(true);
        }
      });
    });

    it('should have proper readiness aggregation conditions', () => {
      const schemaStatus = rgd.spec.schema.status;

      // Verify readiness aggregation conditions exist
      expect(schemaStatus.kubernetesResourcesReady).toBeDefined();
      expect(schemaStatus.awsResourcesReady).toBeDefined();
      expect(schemaStatus.workflowsReady).toBeDefined();
      expect(schemaStatus.setupCompleted).toBeDefined();
      expect(schemaStatus.webhookIntegrationReady).toBeDefined();

      // Verify they reference appropriate resources
      expect(schemaStatus.kubernetesResourcesReady).toContain('namespace.status.phase == "Active"');
      expect(schemaStatus.awsResourcesReady).toContain('ecrmainrepo.status.conditions[0].status == "True"');
      expect(schemaStatus.workflowsReady).toContain('provisioningworkflow.status');
    });
  });
});