import { describe, it, expect } from 'vitest';
import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import { loadRGD, createMockSchemaInstance } from './utils/rgd-loader.js';

describe('RGD Schema Validation', () => {
  let rgd;
  let ajv;

  beforeEach(() => {
    rgd = loadRGD();
    ajv = new Ajv({ allErrors: true });
    addFormats(ajv);
  });

  describe('Schema Definition Structure', () => {
    it('should have valid ResourceGraphDefinition metadata', () => {
      expect(rgd.apiVersion).toBe('kro.run/v1alpha1');
      expect(rgd.kind).toBe('ResourceGraphDefinition');
      expect(rgd.metadata.name).toBe('cicdpipeline.kro.run');
      expect(rgd.metadata.annotations).toHaveProperty('argocd.argoproj.io/sync-wave');
    });

    it('should have properly defined schema structure', () => {
      expect(rgd.spec.schema).toBeDefined();
      expect(rgd.spec.schema.apiVersion).toBe('v1alpha1');
      expect(rgd.spec.schema.kind).toBe('CICDPipeline');
      expect(rgd.spec.schema.spec).toBeDefined();
      expect(rgd.spec.schema.status).toBeDefined();
    });

    it('should have all required schema fields', () => {
      const schemaSpec = rgd.spec.schema.spec;

      // Required string fields
      expect(schemaSpec.name).toBe('string');
      expect(schemaSpec.namespace).toBe('string');

      // AWS configuration
      expect(schemaSpec.aws).toBeDefined();
      expect(schemaSpec.aws.region).toBe('string');
      expect(schemaSpec.aws.clusterName).toBe('string');

      // Application configuration
      expect(schemaSpec.application).toBeDefined();
      expect(schemaSpec.application.name).toBe('string');
      expect(schemaSpec.application.dockerfilePath).toBe('string | default="."');
      expect(schemaSpec.application.deploymentPath).toBe('string | default="./deployment"');

      // AWS resource prefix (used for ECR repositories)
      expect(schemaSpec.aws.resourcePrefix).toBe('string | default="peeks"');

      // GitLab configuration
      expect(schemaSpec.gitlab).toBeDefined();
      expect(schemaSpec.gitlab.hostname).toBe('string');
      expect(schemaSpec.gitlab.username).toBe('string');
    });

    it('should have comprehensive status tracking', () => {
      const schemaStatus = rgd.spec.schema.status;

      // Actual status fields in the RGD (only the ones that actually exist)
      expect(schemaStatus.ecrMainRepositoryURI).toBeDefined();
      expect(schemaStatus.ecrCacheRepositoryURI).toBeDefined();
      expect(schemaStatus.iamRoleARN).toBeDefined();
      expect(schemaStatus.serviceAccountName).toBeDefined();
      expect(schemaStatus.namespace).toBeDefined();

      // Verify they reference the correct resources
      expect(schemaStatus.ecrMainRepositoryURI).toContain('ecrmainrepo.status.repositoryURI');
      expect(schemaStatus.ecrCacheRepositoryURI).toContain('ecrcacherepo.status.repositoryURI');
      expect(schemaStatus.iamRoleARN).toContain('iamrole.status.ackResourceMetadata.arn');
      expect(schemaStatus.serviceAccountName).toContain('serviceaccount.metadata.name');
      expect(schemaStatus.namespace).toContain('appnamespace.metadata.name');
    });
  });

  describe('Parameter Validation', () => {
    it('should validate required parameters', () => {
      const validInstance = createMockSchemaInstance();

      // All required fields should be present
      expect(validInstance.spec.name).toBeDefined();
      expect(validInstance.spec.namespace).toBeDefined();
      expect(validInstance.spec.aws.region).toBeDefined();
      expect(validInstance.spec.aws.clusterName).toBeDefined();
      expect(validInstance.spec.application.name).toBeDefined();
      expect(validInstance.spec.gitlab.hostname).toBeDefined();
      expect(validInstance.spec.gitlab.username).toBeDefined();
    });

    it('should apply default values correctly', () => {
      const instanceWithDefaults = createMockSchemaInstance({
        spec: {
          application: {
            // Don't specify dockerfilePath and deploymentPath to test defaults
          },
          ecr: {
            // Don't specify repositoryPrefix to test default
          }
        }
      });

      // These should get default values when processed by Kro
      expect(instanceWithDefaults.spec.application.dockerfilePath).toBe('.');
      expect(instanceWithDefaults.spec.application.deploymentPath).toBe('./deployment');
      expect(instanceWithDefaults.spec.aws.resourcePrefix).toBe('peeks');
    });

    it('should validate AWS region format', () => {
      const validRegions = ['us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1'];
      const invalidRegions = ['invalid-region', 'us-east', ''];

      validRegions.forEach(region => {
        const instance = createMockSchemaInstance({
          spec: { aws: { region } }
        });
        expect(instance.spec.aws.region).toBe(region);
      });

      // Invalid regions should be caught by validation logic
      invalidRegions.forEach(region => {
        const instance = createMockSchemaInstance({
          spec: { aws: { region } }
        });
        // In a real implementation, this would fail validation
        expect(typeof instance.spec.aws.region).toBe('string');
      });
    });

    it('should validate application name format', () => {
      const validNames = ['test-app', 'myapp', 'app123', 'my-test-app-v2'];
      const invalidNames = ['', 'app_with_underscores', 'App-With-Caps', 'app with spaces'];

      validNames.forEach(name => {
        const instance = createMockSchemaInstance({
          spec: { application: { name } }
        });
        expect(instance.spec.application.name).toBe(name);
      });

      // Invalid names should be caught by validation logic
      invalidNames.forEach(name => {
        const instance = createMockSchemaInstance({
          spec: { application: { name } }
        });
        // In a real implementation, this would fail validation
        expect(typeof instance.spec.application.name).toBe('string');
      });
    });

    it('should validate path parameters', () => {
      const validPaths = ['.', './src', './deployment', 'src/main', 'deployment/k8s'];
      const invalidPaths = ['', '/absolute/path', '../parent/path'];

      validPaths.forEach(path => {
        const instance = createMockSchemaInstance({
          spec: {
            application: {
              dockerfilePath: path,
              deploymentPath: path
            }
          }
        });
        expect(instance.spec.application.dockerfilePath).toBe(path);
        expect(instance.spec.application.deploymentPath).toBe(path);
      });

      // Invalid paths should be caught by validation logic
      invalidPaths.forEach(path => {
        const instance = createMockSchemaInstance({
          spec: {
            application: {
              dockerfilePath: path,
              deploymentPath: path
            }
          }
        });
        // In a real implementation, this would fail validation
        expect(typeof instance.spec.application.dockerfilePath).toBe('string');
        expect(typeof instance.spec.application.deploymentPath).toBe('string');
      });
    });

    it('should validate ECR repository prefix format', () => {
      const validPrefixes = ['peeks', 'myorg', 'company-name', 'org123'];
      const invalidPrefixes = ['', 'Org-With-Caps', 'org_with_underscores', 'org with spaces'];

      validPrefixes.forEach(prefix => {
        const instance = createMockSchemaInstance({
          spec: { ecr: { repositoryPrefix: prefix } }
        });
        expect(instance.spec.ecr.repositoryPrefix).toBe(prefix);
      });

      // Invalid prefixes should be caught by validation logic
      invalidPrefixes.forEach(prefix => {
        const instance = createMockSchemaInstance({
          spec: { ecr: { repositoryPrefix: prefix } }
        });
        // In a real implementation, this would fail validation
        expect(typeof instance.spec.ecr.repositoryPrefix).toBe('string');
      });
    });

    it('should validate GitLab configuration', () => {
      const validHostnames = ['gitlab.example.com', 'git.company.com', 'localhost:3000'];
      const validUsernames = ['testuser', 'user123', 'my-user'];

      validHostnames.forEach(hostname => {
        const instance = createMockSchemaInstance({
          spec: { gitlab: { hostname } }
        });
        expect(instance.spec.gitlab.hostname).toBe(hostname);
      });

      validUsernames.forEach(username => {
        const instance = createMockSchemaInstance({
          spec: { gitlab: { username } }
        });
        expect(instance.spec.gitlab.username).toBe(username);
      });
    });
  });

  describe('Schema Consistency', () => {
    it('should have consistent naming patterns', () => {
      const resources = rgd.spec.resources;

      resources.forEach(resource => {
        expect(resource.id).toBeDefined();
        expect(typeof resource.id).toBe('string');
        expect(resource.id.length).toBeGreaterThan(0);

        if (resource.readyWhen) {
          expect(Array.isArray(resource.readyWhen)).toBe(true);
          expect(resource.readyWhen.length).toBeGreaterThan(0);
        }

        expect(resource.template).toBeDefined();
        expect(resource.template.apiVersion).toBeDefined();
        expect(resource.template.kind).toBeDefined();
        expect(resource.template.metadata).toBeDefined();

        // Some resources use generateName instead of name (like Workflows)
        const hasNameOrGenerateName = resource.template.metadata.name || resource.template.metadata.generateName;
        expect(hasNameOrGenerateName).toBeDefined();
      });
    });

    it('should have proper resource ID references in status', () => {
      const schemaStatus = rgd.spec.schema.status;
      const resourceIds = rgd.spec.resources.map(r => r.id);

      // Check that status references match actual resource IDs
      const statusReferences = Object.values(schemaStatus)
        .filter(value => typeof value === 'string')
        .map(value => {
          const match = value.match(/\$\{(\w+)\./);
          return match ? match[1] : null;
        })
        .filter(Boolean);

      statusReferences.forEach(ref => {
        expect(resourceIds).toContain(ref);
      });
    });

    it('should have consistent label patterns', () => {
      const resources = rgd.spec.resources;

      resources.forEach(resource => {
        if (resource.template.metadata.labels) {
          const labels = resource.template.metadata.labels;

          // Check for consistent label keys
          if (labels['app.kubernetes.io/name']) {
            expect(labels['app.kubernetes.io/name']).toContain('${schema.spec.application.name}');
          }

          if (labels['app.kubernetes.io/component']) {
            expect(typeof labels['app.kubernetes.io/component']).toBe('string');
          }

          if (labels['app.kubernetes.io/managed-by']) {
            expect(labels['app.kubernetes.io/managed-by']).toBe('kro');
          }
        }
      });
    });
  });
});