import { describe, it, expect, beforeAll } from 'vitest';
import yaml from 'js-yaml';
import fs from 'fs';
import path from 'path';
import Mustache from 'mustache';

describe('Inline YAML Manifest Validation', () => {
  let templateContent;
  let templateSpec;

  beforeAll(() => {
    // Load the Backstage template
    const templatePath = path.resolve(__dirname, '../../../../../../../../platform/backstage/templates/cicd-pipeline/template-cicd-pipeline.yaml');
    templateContent = fs.readFileSync(templatePath, 'utf8');
    templateSpec = yaml.load(templateContent);
  });

  describe('Kro Instance Manifest Generation', () => {
    const testParameters = {
      appname: 'testapp',
      aws_region: 'us-west-2',
      cluster_name: 'modern-engineering',
      dockerfile_path: './backend',
      deployment_path: './k8s'
    };

    const mockSteps = {
      fetchSystem: {
        output: {
          entity: {
            spec: {
              hostname: 'gitlab.example.com',
              gituser: 'testuser'
            }
          }
        }
      }
    };

    const mockUser = {
      entity: {
        metadata: {
          name: 'test-user'
        }
      }
    };

    it('should generate valid Kro CICDPipeline manifest', () => {
      // Find the kube:apply step for Kro instance
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      expect(kubeApplyStep).toBeDefined();
      expect(kubeApplyStep.action).toBe('kube:apply');
      expect(kubeApplyStep.input.manifest).toBeDefined();

      // Parse the inline manifest template
      const manifestTemplate = kubeApplyStep.input.manifest;
      expect(manifestTemplate).toContain('apiVersion: kro.run/v1alpha1');
      expect(manifestTemplate).toContain('kind: CICDPipeline');
    });

    it('should properly template parameters in manifest', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Check parameter templating
      expect(manifestTemplate).toContain('${{ parameters.appname }}');
      expect(manifestTemplate).toContain('${{ parameters.aws_region }}');
      expect(manifestTemplate).toContain('${{ parameters.cluster_name }}');
      expect(manifestTemplate).toContain('${{ parameters.dockerfile_path');
      expect(manifestTemplate).toContain('${{ parameters.deployment_path');
    });

    it('should generate manifest with correct metadata structure', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Parse as YAML to validate structure
      // Note: We can't fully parse due to templating, but we can check key elements
      expect(manifestTemplate).toContain('metadata:');
      expect(manifestTemplate).toContain('name: ${{ parameters.appname }}-cicd-pipeline');
      expect(manifestTemplate).toContain('namespace: team-${{ parameters.appname }}');
      expect(manifestTemplate).toContain('labels:');
      expect(manifestTemplate).toContain('annotations:');
    });

    it('should include required labels and annotations', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Check for required labels
      expect(manifestTemplate).toContain('app.kubernetes.io/name');
      expect(manifestTemplate).toContain('app.kubernetes.io/component: cicd-pipeline');
      expect(manifestTemplate).toContain('app.kubernetes.io/managed-by: backstage');
      expect(manifestTemplate).toContain('backstage.io/template-name: cicd-pipeline');

      // Check for required annotations
      expect(manifestTemplate).toContain('backstage.io/template-version');
      expect(manifestTemplate).toContain('backstage.io/created-by');
      expect(manifestTemplate).toContain('cicd.kro.run/application-name');
      expect(manifestTemplate).toContain('cicd.kro.run/aws-region');
      expect(manifestTemplate).toContain('cicd.kro.run/cluster-name');
    });

    it('should have correct spec structure', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Check spec structure
      expect(manifestTemplate).toContain('spec:');
      expect(manifestTemplate).toContain('name: ${{ parameters.appname }}-cicd');
      expect(manifestTemplate).toContain('namespace: team-${{ parameters.appname }}');
      expect(manifestTemplate).toContain('aws:');
      expect(manifestTemplate).toContain('region: ${{ parameters.aws_region }}');
      expect(manifestTemplate).toContain('clusterName: ${{ parameters.cluster_name }}');
      expect(manifestTemplate).toContain('application:');
      expect(manifestTemplate).toContain('ecr:');
      expect(manifestTemplate).toContain('gitlab:');
    });

    it('should handle default values correctly', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Check default value handling
      expect(manifestTemplate).toContain('dockerfilePath: ${{ parameters.dockerfile_path | default(".") }}');
      expect(manifestTemplate).toContain('deploymentPath: ${{ parameters.deployment_path | default("./deployment") }}');
      expect(manifestTemplate).toContain('repositoryPrefix: "peeks"');
    });

    it('should reference system information correctly', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Check system information templating
      expect(manifestTemplate).toContain("hostname: ${{ steps['fetchSystem'].output.entity.spec.hostname }}");
      expect(manifestTemplate).toContain("username: ${{ steps['fetchSystem'].output.entity.spec.gituser }}");
    });
  });

  describe('Manifest Validation Properties', () => {
    it('should have namespaced deployment configuration', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      expect(kubeApplyStep.input.namespaced).toBe(true);
      expect(kubeApplyStep.input.clusterName).toBe('local');
    });

    it('should not reference external files', () => {
      const kubeApplySteps = templateSpec.spec.steps.filter(
        step => step.action === 'kube:apply'
      );

      kubeApplySteps.forEach(step => {
        // Ensure no file references in kube:apply actions
        expect(step.input.manifestPath).toBeUndefined();
        expect(step.input.manifest).toBeDefined();

        // Ensure manifest is inline (contains YAML content)
        expect(step.input.manifest).toContain('apiVersion:');
        expect(step.input.manifest).toContain('kind:');
      });
    });
  });

  describe('Template Step Validation', () => {
    it('should have all required steps in correct order', () => {
      const steps = templateSpec.spec.steps;
      const stepIds = steps.map(step => step.id);

      // Check for required steps
      expect(stepIds).toContain('validate-parameters');
      expect(stepIds).toContain('fetchSystem');
      expect(stepIds).toContain('fetch-base');
      expect(stepIds).toContain('publish');
      expect(stepIds).toContain('apply-kro-instance');
      expect(stepIds).toContain('create-argocd-app');
      expect(stepIds).toContain('register');

      // Check step order (fetchSystem should come before apply-kro-instance)
      const fetchSystemIndex = stepIds.indexOf('fetchSystem');
      const applyKroIndex = stepIds.indexOf('apply-kro-instance');
      expect(fetchSystemIndex).toBeLessThan(applyKroIndex);
    });

    it('should validate parameter validation step', () => {
      const validateStep = templateSpec.spec.steps.find(
        step => step.id === 'validate-parameters'
      );

      expect(validateStep).toBeDefined();
      expect(validateStep.action).toBe('debug:log');
      expect(validateStep.input.message).toContain('Validating template parameters');
    });

    it('should validate GitLab publish step', () => {
      const publishStep = templateSpec.spec.steps.find(
        step => step.id === 'publish'
      );

      expect(publishStep).toBeDefined();
      expect(publishStep.action).toBe('publish:gitlab');
      expect(publishStep.input.repoUrl).toContain('${{parameters.appname}}-cicd');
      expect(publishStep.input.defaultBranch).toBe('main');
      expect(publishStep.input.useCustomGit).toBe(true);
    });

    it('should validate ArgoCD app creation step', () => {
      const argoCDStep = templateSpec.spec.steps.find(
        step => step.id === 'create-argocd-app'
      );

      expect(argoCDStep).toBeDefined();
      expect(argoCDStep.action).toBe('argocd:create-resources');
      expect(argoCDStep.input.appName).toContain('${{parameters.appname}}-cicd');
      expect(argoCDStep.input.namespace).toContain('team-${{ parameters.appname }}');
      expect(argoCDStep.input.syncPolicy.automated).toBeDefined();
    });
  });

  describe('Output Links Validation', () => {
    it('should provide comprehensive output links', () => {
      const output = templateSpec.spec.output;

      expect(output.links).toBeDefined();
      expect(output.links.length).toBeGreaterThan(10);

      // Check for key links
      const linkTitles = output.links.map(link => link.title);
      expect(linkTitles).toContain('Open in catalog');
      expect(linkTitles).toContain('Kro CI/CD Pipeline Instance');
      expect(linkTitles).toContain('ECR Main Repository');
      expect(linkTitles).toContain('GitLab Repository');
      expect(linkTitles).toContain('ArgoCD CI/CD Pipeline Application');
    });

    it('should template URLs correctly in output links', () => {
      const output = templateSpec.spec.output;

      output.links.forEach(link => {
        if (link.url) {
          // URLs should contain parameter templating
          expect(
            link.url.includes('${{ parameters.') ||
            link.url.includes("${{ steps['fetchSystem']") ||
            link.url.includes('${{ steps[')
          ).toBe(true);
        }
      });
    });

    it('should provide informative text output', () => {
      const output = templateSpec.spec.output;

      expect(output.text).toBeDefined();
      expect(output.text.length).toBeGreaterThan(0);

      const textOutput = output.text[0];
      expect(textOutput.title).toContain('Kro-based CI/CD Pipeline Configuration');
      expect(textOutput.content).toContain('AWS Resources');
      expect(textOutput.content).toContain('Kubernetes Resources');
      expect(textOutput.content).toContain('Next Steps');
    });
  });
});