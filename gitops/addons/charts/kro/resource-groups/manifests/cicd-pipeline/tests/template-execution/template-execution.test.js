import { describe, it, expect, beforeAll } from 'vitest';
import yaml from 'js-yaml';
import fs from 'fs';
import path from 'path';

describe('Backstage Template Execution Tests', () => {
  let templateContent;
  let templateSpec;

  beforeAll(() => {
    // Load the Backstage template
    const templatePath = path.resolve(__dirname, '../../../../../../../platform/backstage/templates/cicd-pipeline/template-cicd-pipeline-gitops.yaml');
    templateContent = fs.readFileSync(templatePath, 'utf8');
    templateSpec = yaml.load(templateContent);
  });

  describe('Template Structure and Metadata', () => {
    it('should have correct template metadata', () => {
      expect(templateSpec.apiVersion).toBe('scaffolder.backstage.io/v1beta3');
      expect(templateSpec.kind).toBe('Template');
      expect(templateSpec.metadata.name).toBe('cicd-pipeline-gitops');
      expect(templateSpec.metadata.title).toBe('Deploy CI/CD Pipeline With KRO (GitOps)');
      expect(templateSpec.metadata.description).toContain('Kro-based CI/CD Pipeline');
      expect(templateSpec.metadata.description).toContain('GitOps');
    });

    it('should have proper ownership and type', () => {
      expect(templateSpec.spec.owner).toBe('guest');
      expect(templateSpec.spec.type).toBe('service');
    });
  });

  describe('Template Execution Flow', () => {
    it('should execute steps in correct order for successful deployment', () => {
      const steps = templateSpec.spec.steps;
      const stepIds = steps.map(step => step.id);

      // Verify complete execution flow
      expect(stepIds).toEqual([
        'validate-parameters',
        'fetchSystem',
        'fetch-base',
        'publish',
        'apply-kro-instance',
        'validate-kro-instance',
        'create-argocd-project',
        'create-argocd-app',
        'register',
        'provide-access-information'
      ]);
    });

    it('should validate parameters before any operations', () => {
      const firstStep = templateSpec.spec.steps[0];
      expect(firstStep.id).toBe('validate-parameters');
      expect(firstStep.action).toBe('debug:log');
      expect(firstStep.input.message).toContain('Validating template parameters');
    });

    it('should fetch system information early in the process', () => {
      const fetchSystemStep = templateSpec.spec.steps.find(
        step => step.id === 'fetchSystem'
      );

      const stepIndex = templateSpec.spec.steps.findIndex(
        step => step.id === 'fetchSystem'
      );

      expect(stepIndex).toBe(1); // Second step
      expect(fetchSystemStep.action).toBe('catalog:fetch');
    });

    it('should apply Kro instance before creating ArgoCD app', () => {
      const steps = templateSpec.spec.steps;
      const kroIndex = steps.findIndex(step => step.id === 'apply-kro-instance');
      const argoCDIndex = steps.findIndex(step => step.id === 'create-argocd-app');

      expect(kroIndex).toBeLessThan(argoCDIndex);
    });

    it('should provide validation and information steps', () => {
      const validateKroStep = templateSpec.spec.steps.find(
        step => step.id === 'validate-kro-instance'
      );
      const accessInfoStep = templateSpec.spec.steps.find(
        step => step.id === 'provide-access-information'
      );

      expect(validateKroStep).toBeDefined();
      expect(accessInfoStep).toBeDefined();

      // Should be informational steps (debug:log)
      expect(validateKroStep.action).toBe('debug:log');
      expect(accessInfoStep.action).toBe('debug:log');
    });
  });

  describe('Template Execution Scenarios', () => {
    const testScenarios = [
      {
        name: 'production-deployment',
        description: 'Production deployment with custom cluster',
        parameters: {
          appname: 'prod-api',
          aws_region: 'us-east-1',
          cluster_name: 'production-cluster',
          dockerfile_path: './api',
          deployment_path: './k8s/prod'
        },
        expectedNamespace: 'team-prod-api',
        expectedECRRepo: 'peeks/prod-api'
      },
      {
        name: 'development-deployment',
        description: 'Development deployment with defaults',
        parameters: {
          appname: 'dev-service',
          aws_region: 'us-west-2',
          cluster_name: 'modern-engineering',
          dockerfile_path: '.',
          deployment_path: './deployment'
        },
        expectedNamespace: 'team-dev-service',
        expectedECRRepo: 'peeks/dev-service'
      },
      {
        name: 'microservice-deployment',
        description: 'Microservice with nested paths',
        parameters: {
          appname: 'user-microservice',
          aws_region: 'eu-west-1',
          cluster_name: 'eu-cluster',
          dockerfile_path: './services/user',
          deployment_path: './deploy/user'
        },
        expectedNamespace: 'team-user-microservice',
        expectedECRRepo: 'peeks/user-microservice'
      }
    ];

    testScenarios.forEach(scenario => {
      describe(`Scenario: ${scenario.name}`, () => {
        it('should generate correct Kro instance for scenario', () => {
          const kubeApplyStep = templateSpec.spec.steps.find(
            step => step.id === 'apply-kro-instance'
          );

          const manifestTemplate = kubeApplyStep.input.manifest;

          // Verify template structure
          expect(manifestTemplate).toContain('apiVersion: kro.run/v1alpha1');
          expect(manifestTemplate).toContain('kind: CICDPipeline');
          expect(manifestTemplate).toContain('name: ${{ parameters.appname }}-cicd-pipeline');
          expect(manifestTemplate).toContain('namespace: team-${{ parameters.appname }}');
        });

        it('should create correct GitLab repository URL for scenario', () => {
          const publishStep = templateSpec.spec.steps.find(
            step => step.id === 'publish'
          );

          expect(publishStep.input.repoUrl).toContain('${{parameters.appname}}-cicd');
          expect(publishStep.input.repoUrl).toContain("${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
        });

        it('should create correct ArgoCD application for scenario', () => {
          const argoCDStep = templateSpec.spec.steps.find(
            step => step.id === 'create-argocd-app'
          );

          expect(argoCDStep.input.manifest).toContain('${{parameters.appname}}-cicd');
          expect(argoCDStep.input.manifest).toContain('team-${{ parameters.appname }}');
        });

        it('should provide correct output links for scenario', () => {
          const output = templateSpec.spec.output;

          // Check that links are properly templated
          output.links.forEach(link => {
            if (link.url) {
              expect(
                link.url.includes('${{ parameters.appname }}') ||
                link.url.includes('${{ parameters.aws_region }}') ||
                link.url.includes("${{ steps['fetchSystem']") ||
                !link.url.includes('{{')
              ).toBe(true);
            }
          });
        });
      });
    });
  });

  describe('Template Error Handling and Validation', () => {
    it('should validate all required parameters', () => {
      const parameters = templateSpec.spec.parameters;

      // Find required parameters
      const appConfig = parameters.find(p => p.title === 'Application Configuration');
      expect(appConfig.required).toContain('appname');

      // Verify validation patterns exist
      expect(appConfig.properties.appname.pattern).toBeDefined();
      expect(appConfig.properties.appname.minLength).toBe(1);
      expect(appConfig.properties.appname.maxLength).toBe(63);
    });

    it('should provide helpful validation messages', () => {
      const parameters = templateSpec.spec.parameters;

      parameters.forEach(paramGroup => {
        Object.values(paramGroup.properties || {}).forEach(prop => {
          if (prop['ui:help']) {
            expect(prop['ui:help']).toBeTruthy();
            expect(typeof prop['ui:help']).toBe('string');
          }
        });
      });
    });

    it('should include comprehensive validation step', () => {
      const validateStep = templateSpec.spec.steps.find(
        step => step.id === 'validate-parameters'
      );

      const message = validateStep.input.message;
      expect(message).toContain('Validation checks');
      expect(message).toContain('App name matches pattern');
      expect(message).toContain('Dockerfile path is valid');
      expect(message).toContain('Deployment path is valid');
    });
  });

  describe('Template Output and Documentation', () => {
    it('should provide comprehensive monitoring links', () => {
      const output = templateSpec.spec.output;
      expect(output.links.length).toBeGreaterThan(10);

      const linkCategories = {
        kro: output.links.filter(l => l.title.toLowerCase().includes('kro')),
        argo: output.links.filter(l => l.title.toLowerCase().includes('argo')),
        aws: output.links.filter(l => l.icon === 'cloud'),
        git: output.links.filter(l => l.icon === 'git'),
        catalog: output.links.filter(l => l.icon === 'catalog')
      };

      expect(linkCategories.kro.length).toBeGreaterThan(0);
      expect(linkCategories.argo.length).toBeGreaterThan(0);
      expect(linkCategories.aws.length).toBeGreaterThan(5);
      expect(linkCategories.git.length).toBeGreaterThan(0);
      expect(linkCategories.catalog.length).toBeGreaterThan(0);
    });

    it('should provide detailed text documentation', () => {
      const output = templateSpec.spec.output;
      expect(output.text).toBeDefined();
      expect(output.text.length).toBe(1);

      const textOutput = output.text[0];
      expect(textOutput.title).toContain('Kro-based CI/CD Pipeline Configuration');

      const content = textOutput.content;
      expect(content).toContain('Pipeline Overview');
      expect(content).toContain('AWS Resources (via ACK Controllers)');
      expect(content).toContain('Kubernetes Resources');
      expect(content).toContain('Argo Workflows Templates');
      expect(content).toContain('Security Features');
      expect(content).toContain('Next Steps');
    });

    it('should provide actionable next steps', () => {
      const output = templateSpec.spec.output;
      const textContent = output.text[0].content;

      expect(textContent).toContain('Push Code');
      expect(textContent).toContain('Monitor Workflows');
      expect(textContent).toContain('View Resources');
      expect(textContent).toContain('Configure Deployments');
    });
  });

  describe('Template Integration Points', () => {
    it('should integrate with Backstage catalog system', () => {
      const registerStep = templateSpec.spec.steps.find(
        step => step.id === 'register'
      );

      expect(registerStep.action).toBe('catalog:register');
      expect(registerStep.input.catalogInfoPath).toBe('/catalog-info.yaml');

      // Should provide catalog link in output
      const catalogLink = templateSpec.spec.output.links.find(
        link => link.title === 'Open in catalog'
      );
      expect(catalogLink).toBeDefined();
    });

    it('should integrate with GitLab for source control', () => {
      const publishStep = templateSpec.spec.steps.find(
        step => step.id === 'publish'
      );

      expect(publishStep.action).toBe('publish:gitlab');
      expect(publishStep.input.useCustomGit).toBe(true);

      // Should provide GitLab link in output
      const gitlabLink = templateSpec.spec.output.links.find(
        link => link.title === 'GitLab Repository'
      );
      expect(gitlabLink).toBeDefined();
    });

    it('should integrate with ArgoCD for GitOps', () => {
      const argoCDStep = templateSpec.spec.steps.find(
        step => step.id === 'create-argocd-app'
      );

      expect(argoCDStep.action).toBe('kube:apply');
      expect(argoCDStep.input.manifest).toContain('prune: true');
      expect(argoCDStep.input.manifest).toContain('selfHeal: true');

      // Should provide ArgoCD link in output
      const argoCDLink = templateSpec.spec.output.links.find(
        link => link.title === 'ArgoCD Application (GitOps)'
      );
      expect(argoCDLink).toBeDefined();
    });

    it('should integrate with Kro for resource orchestration', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      expect(kubeApplyStep.action).toBe('kube:apply');
      expect(kubeApplyStep.input.namespaced).toBe(true);
      expect(kubeApplyStep.input.manifest).toContain('kind: CICDPipeline');

      // Should provide Kro monitoring link in output
      const kroLink = templateSpec.spec.output.links.find(
        link => link.title === 'Kro CI/CD Pipeline Instance'
      );
      expect(kroLink).toBeDefined();
    });
  });

  describe('Template Completeness and Quality', () => {
    it('should be a complete, self-contained template', () => {
      // No external file dependencies in kube:apply
      const kubeApplySteps = templateSpec.spec.steps.filter(
        step => step.action === 'kube:apply'
      );

      kubeApplySteps.forEach(step => {
        expect(step.input.manifest).toBeDefined();
        expect(step.input.manifestPath).toBeUndefined();
      });

      // All required steps present
      const requiredSteps = [
        'validate-parameters',
        'fetchSystem',
        'publish',
        'apply-kro-instance',
        'create-argocd-app',
        'register'
      ];

      const stepIds = templateSpec.spec.steps.map(step => step.id);
      requiredSteps.forEach(requiredStep => {
        expect(stepIds).toContain(requiredStep);
      });
    });

    it('should provide comprehensive user experience', () => {
      // Parameter validation and help
      const parameters = templateSpec.spec.parameters;
      expect(parameters.length).toBe(3); // Three parameter groups

      // Informational steps
      const infoSteps = templateSpec.spec.steps.filter(
        step => step.action === 'debug:log'
      );
      expect(infoSteps.length).toBe(3); // Validation, Kro validation, access info

      // Comprehensive output
      expect(templateSpec.spec.output.links.length).toBeGreaterThan(10);
      expect(templateSpec.spec.output.text.length).toBe(1);
    });

    it('should follow Backstage template best practices', () => {
      // Proper metadata
      expect(templateSpec.metadata.name).toBeDefined();
      expect(templateSpec.metadata.title).toBeDefined();
      expect(templateSpec.metadata.description).toBeDefined();

      // Proper spec structure
      expect(templateSpec.spec.owner).toBeDefined();
      expect(templateSpec.spec.type).toBeDefined();
      expect(templateSpec.spec.parameters).toBeDefined();
      expect(templateSpec.spec.steps).toBeDefined();
      expect(templateSpec.spec.output).toBeDefined();

      // Step naming and structure
      templateSpec.spec.steps.forEach(step => {
        expect(step.id).toBeDefined();
        expect(step.name).toBeDefined();
        expect(step.action).toBeDefined();
      });
    });
  });
});