import { describe, it, expect, beforeAll } from 'vitest';
import yaml from 'js-yaml';
import fs from 'fs';
import path from 'path';
import Mustache from 'mustache';

describe('Backstage Template Parameter Combinations', () => {
  let templateContent;
  let templateSpec;

  beforeAll(() => {
    // Load the Backstage template
    const templatePath = path.resolve(__dirname, '../../../../../../../platform/backstage/templates/cicd-pipeline/template-cicd-pipeline-gitops.yaml');
    templateContent = fs.readFileSync(templatePath, 'utf8');
    templateSpec = yaml.load(templateContent);
  });

  describe('Parameter Validation', () => {
    it('should have all required parameters defined', () => {
      const parameters = templateSpec.spec.parameters;

      // Check Application Configuration section
      const appConfig = parameters.find(p => p.title === 'Application Configuration');
      expect(appConfig).toBeDefined();
      expect(appConfig.properties.appname).toBeDefined();
      expect(appConfig.required).toContain('appname');

      // Check AWS Configuration section
      const awsConfig = parameters.find(p => p.title === 'AWS Configuration');
      expect(awsConfig).toBeDefined();
      expect(awsConfig.properties.aws_region).toBeDefined();
      expect(awsConfig.properties.cluster_name).toBeDefined();

      // Check Application Paths section
      const pathsConfig = parameters.find(p => p.title === 'Application Paths');
      expect(pathsConfig).toBeDefined();
      expect(pathsConfig.properties.dockerfile_path).toBeDefined();
      expect(pathsConfig.properties.deployment_path).toBeDefined();
    });

    it('should validate appname pattern constraints', () => {
      const appConfig = templateSpec.spec.parameters.find(p => p.title === 'Application Configuration');
      const appnamePattern = appConfig.properties.appname.pattern;

      // Valid app names
      const validNames = ['myapp', 'my-app', 'app123', 'a', 'test-app-123'];
      validNames.forEach(name => {
        expect(new RegExp(appnamePattern).test(name)).toBe(true);
      });

      // Invalid app names
      const invalidNames = ['MyApp', 'my_app', '-myapp', 'myapp-', 'my..app', ''];
      invalidNames.forEach(name => {
        expect(new RegExp(appnamePattern).test(name)).toBe(false);
      });
    });

    it('should validate AWS region enum values', () => {
      const awsConfig = templateSpec.spec.parameters.find(p => p.title === 'AWS Configuration');
      const validRegions = awsConfig.properties.aws_region.enum;

      expect(validRegions).toContain('us-west-2');
      expect(validRegions).toContain('us-east-1');
      expect(validRegions).toContain('eu-west-1');
      expect(validRegions.length).toBeGreaterThan(5);
    });

    it('should validate path patterns', () => {
      const pathsConfig = templateSpec.spec.parameters.find(p => p.title === 'Application Paths');
      const dockerfilePattern = pathsConfig.properties.dockerfile_path.pattern;
      const deploymentPattern = pathsConfig.properties.deployment_path.pattern;

      // Valid dockerfile paths
      const validDockerPaths = ['.', './backend', './services/api', './app'];
      validDockerPaths.forEach(path => {
        expect(new RegExp(dockerfilePattern).test(path)).toBe(true);
      });

      // Valid deployment paths
      const validDeployPaths = ['./deployment', './k8s', './manifests', './deploy/prod'];
      validDeployPaths.forEach(path => {
        expect(new RegExp(deploymentPattern).test(path)).toBe(true);
      });
    });
  });

  describe('Parameter Combinations Testing', () => {
    const testCombinations = [
      {
        name: 'minimal-config',
        description: 'Minimal configuration with defaults',
        parameters: {
          appname: 'testapp',
          aws_region: 'us-west-2',
          cluster_name: 'modern-engineering',
          dockerfile_path: '.',
          deployment_path: './deployment'
        }
      },
      {
        name: 'custom-paths',
        description: 'Custom dockerfile and deployment paths',
        parameters: {
          appname: 'my-service',
          aws_region: 'us-east-1',
          cluster_name: 'prod-cluster',
          dockerfile_path: './backend',
          deployment_path: './k8s/manifests'
        }
      },
      {
        name: 'eu-region',
        description: 'European region deployment',
        parameters: {
          appname: 'euro-app',
          aws_region: 'eu-west-1',
          cluster_name: 'eu-cluster',
          dockerfile_path: './services/api',
          deployment_path: './deploy/prod'
        }
      },
      {
        name: 'complex-app',
        description: 'Complex application with nested paths',
        parameters: {
          appname: 'complex-microservice',
          aws_region: 'ap-southeast-1',
          cluster_name: 'asia-cluster',
          dockerfile_path: './microservices/user-service',
          deployment_path: './deployment/user-service'
        }
      },
      {
        name: 'single-char-app',
        description: 'Single character app name (edge case)',
        parameters: {
          appname: 'a',
          aws_region: 'us-west-1',
          cluster_name: 'test-cluster',
          dockerfile_path: '.',
          deployment_path: './deployment'
        }
      }
    ];

    testCombinations.forEach(combination => {
      it(`should handle ${combination.name} parameter combination`, () => {
        const params = combination.parameters;

        // Validate all required parameters are present
        expect(params.appname).toBeDefined();
        expect(params.aws_region).toBeDefined();
        expect(params.cluster_name).toBeDefined();

        // Validate parameter formats
        expect(params.appname).toMatch(/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/);
        // prettier-ignore
        expect(params.dockerfile_path).toMatch(new RegExp('^\\\.(/[a-zA-Z0-9_-]+)*/?$|^\\.$'));
        // prettier-ignore
        expect(params.deployment_path).toMatch(new RegExp('^\\\.(/[a-zA-Z0-9_-]+)+/?$'));


        // Validate AWS region is in allowed list
        const awsConfig = templateSpec.spec.parameters.find(p => p.title === 'AWS Configuration');
        expect(awsConfig.properties.aws_region.enum).toContain(params.aws_region);

        // Validate cluster name format
        expect(params.cluster_name).toMatch(/^[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]$/);
      });
    });
  });

  describe('Default Value Handling', () => {
    it('should provide correct default values', () => {
      const awsConfig = templateSpec.spec.parameters.find(p => p.title === 'AWS Configuration');
      const pathsConfig = templateSpec.spec.parameters.find(p => p.title === 'Application Paths');

      expect(awsConfig.properties.aws_region.default).toBe('us-west-2');
      expect(awsConfig.properties.cluster_name.default).toBe('peeks-hub-cluster');
      expect(pathsConfig.properties.dockerfile_path.default).toBe('.');
      expect(pathsConfig.properties.deployment_path.default).toBe('./deployment');
    });

    it('should handle missing optional parameters with defaults', () => {
      const minimalParams = {
        appname: 'testapp'
      };

      // Template should work with just required parameters
      // Defaults should be applied by the template engine
      expect(minimalParams.appname).toBeDefined();

      // Verify default values would be used
      const awsConfig = templateSpec.spec.parameters.find(p => p.title === 'AWS Configuration');
      const pathsConfig = templateSpec.spec.parameters.find(p => p.title === 'Application Paths');

      expect(awsConfig.properties.aws_region.default).toBe('us-west-2');
      expect(pathsConfig.properties.dockerfile_path.default).toBe('.');
    });
  });

  describe('Parameter Constraints Validation', () => {
    it('should enforce appname length constraints', () => {
      const appConfig = templateSpec.spec.parameters.find(p => p.title === 'Application Configuration');
      const constraints = appConfig.properties.appname;

      expect(constraints.minLength).toBe(1);
      expect(constraints.maxLength).toBe(63);

      // Test edge cases
      const validLengths = ['a', 'a'.repeat(63)];
      const invalidLengths = ['', 'a'.repeat(64)];

      validLengths.forEach(name => {
        expect(name.length).toBeGreaterThanOrEqual(constraints.minLength);
        expect(name.length).toBeLessThanOrEqual(constraints.maxLength);
      });

      invalidLengths.forEach(name => {
        expect(
          name.length < constraints.minLength || name.length > constraints.maxLength
        ).toBe(true);
      });
    });

    it('should enforce cluster name length constraints', () => {
      const awsConfig = templateSpec.spec.parameters.find(p => p.title === 'AWS Configuration');
      const constraints = awsConfig.properties.cluster_name;

      expect(constraints.minLength).toBe(1);
      expect(constraints.maxLength).toBe(100);
    });
  });
});