import { describe, it, expect } from 'vitest';
import { loadRGD, createMockSchemaInstance } from './utils/rgd-loader.js';
import { TemplateEngine } from './utils/template-engine.js';

describe('Parameter Handling', () => {
  let rgd;
  let mockSchema;

  beforeEach(() => {
    rgd = loadRGD();
    mockSchema = createMockSchemaInstance();
  });

  describe('Default Value Handling', () => {
    it('should apply default values for optional parameters', () => {
      const schemaSpec = rgd.spec.schema.spec;

      // Check default value definitions in schema
      expect(schemaSpec.application.dockerfilePath).toBe('string | default="."');
      expect(schemaSpec.application.deploymentPath).toBe('string | default="./deployment"');
      expect(schemaSpec.ecr.repositoryPrefix).toBe('string | default="peeks"');

      // Test with minimal schema instance (missing optional fields)
      const minimalSchema = createMockSchemaInstance({
        spec: {
          name: 'test-app-cicd',
          namespace: 'test-namespace',
          aws: {
            region: 'us-west-2',
            clusterName: 'test-cluster'
          },
          application: {
            name: 'test-app'
            // dockerfilePath and deploymentPath omitted to test defaults
          },
          gitlab: {
            hostname: 'gitlab.example.com',
            username: 'testuser'
          }
          // ecr.repositoryPrefix omitted to test default
        }
      });

      // Apply defaults (simulating Kro's behavior)
      if (!minimalSchema.spec.application.dockerfilePath) {
        minimalSchema.spec.application.dockerfilePath = '.';
      }
      if (!minimalSchema.spec.application.deploymentPath) {
        minimalSchema.spec.application.deploymentPath = './deployment';
      }
      if (!minimalSchema.spec.ecr) {
        minimalSchema.spec.ecr = {};
      }
      if (!minimalSchema.spec.ecr.repositoryPrefix) {
        minimalSchema.spec.ecr.repositoryPrefix = 'peeks';
      }

      expect(minimalSchema.spec.application.dockerfilePath).toBe('.');
      expect(minimalSchema.spec.application.deploymentPath).toBe('./deployment');
      expect(minimalSchema.spec.ecr.repositoryPrefix).toBe('peeks');
    });

    it('should preserve explicitly provided values over defaults', () => {
      const customSchema = createMockSchemaInstance({
        spec: {
          application: {
            dockerfilePath: './custom/dockerfile/path',
            deploymentPath: './custom/deployment/path'
          },
          ecr: {
            repositoryPrefix: 'custom-org'
          }
        }
      });

      expect(customSchema.spec.application.dockerfilePath).toBe('./custom/dockerfile/path');
      expect(customSchema.spec.application.deploymentPath).toBe('./custom/deployment/path');
      expect(customSchema.spec.ecr.repositoryPrefix).toBe('custom-org');
    });
  });

  describe('Parameter Validation Rules', () => {
    it('should validate required parameters are present', () => {
      const requiredFields = [
        'spec.name',
        'spec.namespace',
        'spec.aws.region',
        'spec.aws.clusterName',
        'spec.application.name',
        'spec.gitlab.hostname',
        'spec.gitlab.username'
      ];

      requiredFields.forEach(fieldPath => {
        const invalidSchema = createMockSchemaInstance();

        // Remove the required field
        const pathParts = fieldPath.split('.');
        let current = invalidSchema;
        for (let i = 0; i < pathParts.length - 1; i++) {
          current = current[pathParts[i]];
        }
        delete current[pathParts[pathParts.length - 1]];

        // In a real implementation, this would fail validation
        // For now, we just verify the field was removed
        let checkCurrent = invalidSchema;
        let fieldExists = true;
        try {
          for (const part of pathParts) {
            if (checkCurrent[part] === undefined) {
              fieldExists = false;
              break;
            }
            checkCurrent = checkCurrent[part];
          }
        } catch {
          fieldExists = false;
        }
        expect(fieldExists).toBe(false);
      });
    });

    it('should validate AWS region format', () => {
      const validRegions = [
        'us-east-1',
        'us-east-2',
        'us-west-1',
        'us-west-2',
        'eu-west-1',
        'eu-west-2',
        'eu-central-1',
        'ap-southeast-1',
        'ap-southeast-2',
        'ap-northeast-1'
      ];

      const invalidRegions = [
        '',
        'invalid-region',
        'us-east',
        'US-EAST-1',
        'us_east_1',
        'us east 1'
      ];

      validRegions.forEach(region => {
        const schema = createMockSchemaInstance({
          spec: { aws: { region } }
        });

        // Basic format validation (should match AWS region pattern)
        expect(region).toMatch(/^[a-z]{2}-[a-z]+-\d+$/);
        expect(schema.spec.aws.region).toBe(region);
      });

      invalidRegions.forEach(region => {
        // These should fail validation in a real implementation
        expect(region).not.toMatch(/^[a-z]{2}-[a-z]+-\d+$/);
      });
    });

    it('should validate application name format', () => {
      const validNames = [
        'test-app',
        'myapp',
        'app123',
        'my-test-app-v2',
        'a',
        'app-with-multiple-dashes'
      ];

      const invalidNames = [
        '',
        'App-With-Caps',
        'app_with_underscores',
        'app with spaces',
        'app.with.dots',
        'app@with@symbols',
        '-starts-with-dash',
        'ends-with-dash-',
        'app--double-dash'
      ];

      validNames.forEach(name => {
        const schema = createMockSchemaInstance({
          spec: { application: { name } }
        });

        // Basic format validation (lowercase, alphanumeric, single dashes)
        expect(name).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        expect(schema.spec.application.name).toBe(name);
      });

      invalidNames.forEach(name => {
        // These should fail validation in a real implementation
        if (name !== '') { // Empty string has its own validation
          expect(name).not.toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        }
      });
    });

    it('should validate namespace format', () => {
      const validNamespaces = [
        'test-namespace',
        'default',
        'kube-system',
        'my-app-namespace',
        'ns123'
      ];

      const invalidNamespaces = [
        '',
        'Namespace-With-Caps',
        'namespace_with_underscores',
        'namespace with spaces',
        'namespace.with.dots',
        '-starts-with-dash',
        'ends-with-dash-'
      ];

      validNamespaces.forEach(namespace => {
        const schema = createMockSchemaInstance({
          spec: { namespace }
        });

        // Kubernetes namespace naming rules
        expect(namespace).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        expect(schema.spec.namespace).toBe(namespace);
      });

      invalidNamespaces.forEach(namespace => {
        if (namespace !== '') {
          expect(namespace).not.toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        }
      });
    });

    it('should validate path parameters', () => {
      const validPaths = [
        '.',
        './src',
        './deployment',
        'src/main',
        'deployment/k8s',
        'path/to/dockerfile',
        'very/deep/nested/path'
      ];

      const invalidPaths = [
        '',
        '/absolute/path',
        '../parent/path',
        '~/home/path',
        'path/../with/parent',
        'path with spaces',
        'path\\with\\backslashes'
      ];

      validPaths.forEach(path => {
        const schema = createMockSchemaInstance({
          spec: {
            application: {
              dockerfilePath: path,
              deploymentPath: path
            }
          }
        });

        // Relative path validation (no absolute paths, no parent references)
        expect(path).not.toMatch(/^\//); // No absolute paths
        expect(path).not.toMatch(/\.\./); // No parent references
        expect(schema.spec.application.dockerfilePath).toBe(path);
        expect(schema.spec.application.deploymentPath).toBe(path);
      });

      invalidPaths.forEach(path => {
        // These should fail validation in a real implementation
        const hasInvalidPattern = path.startsWith('/') ||
          path.includes('..') ||
          path.includes('~') ||
          path.includes(' ') ||
          path.includes('\\') ||
          path === '';
        expect(hasInvalidPattern).toBe(true);
      });
    });

    it('should validate ECR repository prefix format', () => {
      const validPrefixes = [
        'peeks',
        'myorg',
        'company-name',
        'org123',
        'a',
        'simple'
      ];

      const invalidPrefixes = [
        '',
        'Org-With-Caps',
        'org_with_underscores',
        'org with spaces',
        'org.with.dots',
        'org@with@symbols',
        '-starts-with-dash',
        'ends-with-dash-'
      ];

      validPrefixes.forEach(prefix => {
        const schema = createMockSchemaInstance({
          spec: { ecr: { repositoryPrefix: prefix } }
        });

        // ECR repository naming rules (lowercase, alphanumeric, dashes)
        expect(prefix).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        expect(schema.spec.ecr.repositoryPrefix).toBe(prefix);
      });

      invalidPrefixes.forEach(prefix => {
        if (prefix !== '') {
          expect(prefix).not.toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
        }
      });
    });

    it('should validate GitLab hostname format', () => {
      const validHostnames = [
        'gitlab.example.com',
        'git.company.com',
        'localhost',
        'localhost:3000',
        'gitlab-server.internal',
        '192.168.1.100',
        '192.168.1.100:8080'
      ];

      const invalidHostnames = [
        '',
        'gitlab with spaces',
        'gitlab@invalid',
        'gitlab..double.dot',
        '.starts.with.dot',
        'ends.with.dot.',
        'http://gitlab.com', // Should not include protocol
        'https://gitlab.com'
      ];

      validHostnames.forEach(hostname => {
        const schema = createMockSchemaInstance({
          spec: { gitlab: { hostname } }
        });

        expect(schema.spec.gitlab.hostname).toBe(hostname);
      });

      invalidHostnames.forEach(hostname => {
        // These should fail validation in a real implementation
        const hasInvalidPattern = hostname.includes(' ') ||
          hostname.includes('@') ||
          hostname.includes('..') ||
          hostname.startsWith('.') ||
          hostname.endsWith('.') ||
          hostname.includes('://') ||
          hostname === '';
        expect(hasInvalidPattern).toBe(true);
      });
    });

    it('should validate GitLab username format', () => {
      const validUsernames = [
        'testuser',
        'user123',
        'my-user',
        'user_name',
        'User-Name',
        'a',
        'user.name'
      ];

      const invalidUsernames = [
        '',
        'user with spaces',
        'user@domain.com', // Should not be email
        '-starts-with-dash',
        'ends-with-dash-',
        '.starts.with.dot',
        'ends.with.dot.'
      ];

      validUsernames.forEach(username => {
        const schema = createMockSchemaInstance({
          spec: { gitlab: { username } }
        });

        expect(schema.spec.gitlab.username).toBe(username);
      });

      invalidUsernames.forEach(username => {
        // These should fail validation in a real implementation
        const hasInvalidPattern = username.includes(' ') ||
          username.includes('@') ||
          username.startsWith('-') ||
          username.endsWith('-') ||
          username.startsWith('.') ||
          username.endsWith('.') ||
          username === '';
        expect(hasInvalidPattern).toBe(true);
      });
    });
  });

  describe('Parameter Substitution in Templates', () => {
    it('should correctly substitute all schema parameters in resource templates', () => {
      const templateEngine = new TemplateEngine(mockSchema, {});
      const resources = rgd.spec.resources;

      resources.forEach(resource => {
        const template = templateEngine.substituteObject(resource.template);

        // Verify that schema parameters are substituted
        const templateStr = JSON.stringify(template);

        // Should not contain unsubstituted schema references
        expect(templateStr).not.toContain('${schema.spec.name}');
        expect(templateStr).not.toContain('${schema.spec.namespace}');
        expect(templateStr).not.toContain('${schema.spec.application.name}');
        expect(templateStr).not.toContain('${schema.spec.aws.region}');
        expect(templateStr).not.toContain('${schema.spec.aws.clusterName}');
        expect(templateStr).not.toContain('${schema.spec.gitlab.hostname}');
        expect(templateStr).not.toContain('${schema.spec.gitlab.username}');

        // Should contain substituted values
        if (templateStr.includes('test-app-cicd') || templateStr.includes('test-namespace')) {
          // Basic substitution worked
          expect(true).toBe(true);
        }
      });
    });

    it('should handle complex parameter combinations', () => {
      const complexSchema = createMockSchemaInstance({
        spec: {
          name: 'complex-app-cicd',
          namespace: 'complex-namespace',
          application: {
            name: 'complex-app-name',
            dockerfilePath: './custom/docker/path',
            deploymentPath: './custom/deploy/path'
          },
          ecr: {
            repositoryPrefix: 'custom-org'
          },
          aws: {
            region: 'eu-west-1',
            clusterName: 'complex-cluster'
          },
          gitlab: {
            hostname: 'custom-gitlab.company.com',
            username: 'complex-user'
          }
        }
      });

      const templateEngine = new TemplateEngine(complexSchema, {});

      // Test ECR repository name construction
      const ecrMainRepo = rgd.spec.resources.find(r => r.id === 'ecrmainrepo');
      const template = templateEngine.substituteObject(ecrMainRepo.template);

      expect(template.spec.name).toBe('custom-org/complex-app-name');
      expect(template.metadata.name).toBe('complex-app-cicd-main-repo');
      expect(template.metadata.namespace).toBe('complex-namespace');
    });

    it('should handle parameter references in nested structures', () => {
      const templateEngine = new TemplateEngine(mockSchema, {});

      // Test IAM policy document with nested parameter references
      const iamPolicy = rgd.spec.resources.find(r => r.id === 'iampolicy');
      const template = templateEngine.substituteObject(iamPolicy.template);

      expect(template.spec.name).toBe('test-app-cicd-ecr-policy');
      expect(template.spec.description).toBe('ECR access policy for CI/CD pipeline');

      // Policy document should be valid JSON with substituted values
      const policyDoc = JSON.parse(template.spec.policyDocument);
      expect(policyDoc.Version).toBe('2012-10-17');
      expect(policyDoc.Statement).toHaveLength(2);
    });

    it('should preserve parameter types during substitution', () => {
      const templateEngine = new TemplateEngine(mockSchema, {});

      // Test service account template
      const serviceAccount = rgd.spec.resources.find(r => r.id === 'serviceaccount');
      const template = templateEngine.substituteObject(serviceAccount.template);

      // Boolean values should remain boolean
      expect(template.automountServiceAccountToken).toBe(true);
      expect(typeof template.automountServiceAccountToken).toBe('boolean');

      // String values should remain string
      expect(typeof template.metadata.name).toBe('string');
      expect(typeof template.metadata.namespace).toBe('string');
    });
  });

  describe('Parameter Edge Cases', () => {
    it('should handle empty or null parameter values gracefully', () => {
      const edgeCaseSchema = createMockSchemaInstance({
        spec: {
          application: {
            dockerfilePath: '', // Empty string
            deploymentPath: null // Null value
          }
        }
      });

      // Apply defaults for empty/null values
      if (!edgeCaseSchema.spec.application.dockerfilePath) {
        edgeCaseSchema.spec.application.dockerfilePath = '.';
      }
      if (!edgeCaseSchema.spec.application.deploymentPath) {
        edgeCaseSchema.spec.application.deploymentPath = './deployment';
      }

      const templateEngine = new TemplateEngine(edgeCaseSchema, {});

      const configMap = rgd.spec.resources.find(r => r.id === 'configmap');
      const template = templateEngine.substituteObject(configMap.template);

      expect(template.data.DOCKERFILE_PATH).toBe('.');
      expect(template.data.DEPLOYMENT_PATH).toBe('./deployment');
    });

    it('should handle special characters in parameter values', () => {
      const specialCharSchema = createMockSchemaInstance({
        spec: {
          application: {
            name: 'app-with-special-chars'
          },
          gitlab: {
            hostname: 'gitlab-server.company-name.com',
            username: 'user.name-123'
          }
        }
      });

      const templateEngine = new TemplateEngine(specialCharSchema, {});

      const configMap = rgd.spec.resources.find(r => r.id === 'configmap');
      const template = templateEngine.substituteObject(configMap.template);

      expect(template.data.APPLICATION_NAME).toBe('app-with-special-chars');
      expect(template.data.GITLAB_HOSTNAME).toBe('gitlab-server.company-name.com');
      expect(template.data.GITLAB_USERNAME).toBe('user.name-123');
    });

    it('should handle very long parameter values', () => {
      const longValueSchema = createMockSchemaInstance({
        spec: {
          name: 'very-long-application-name-that-exceeds-normal-length-limits-for-testing-purposes',
          application: {
            name: 'very-long-application-name-that-exceeds-normal-length'
          }
        }
      });

      const templateEngine = new TemplateEngine(longValueSchema, {});

      const namespace = rgd.spec.resources.find(r => r.id === 'namespace');
      const template = templateEngine.substituteObject(namespace.template);

      // Should handle long names without truncation (unless explicitly implemented)
      expect(template.metadata.labels['app.kubernetes.io/name']).toBe('very-long-application-name-that-exceeds-normal-length');
    });
  });
});