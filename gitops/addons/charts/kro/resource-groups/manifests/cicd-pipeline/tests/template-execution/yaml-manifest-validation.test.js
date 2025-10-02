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
    const templatePath = path.resolve(__dirname, '../../../../../../platform/backstage/templates/cicd-pipeline/template-cicd-pipeline-gitops.yaml');
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
      // In GitOps template, the Kro resource is created through skeleton files
      // Check that the fetch-base step is configured correctly
      const fetchBaseStep = templateSpec.spec.steps.find(
        step => step.id === 'fetch-base'
      );

      expect(fetchBaseStep.input.values.appname).toBe('${{ parameters.appname }}');
      expect(fetchBaseStep.input.values.namespace).toBe('team-${{ parameters.appname }}');
      expect(fetchBaseStep.input.values.aws_region).toBe('${{ parameters.aws_region }}');
      expect(fetchBaseStep.input.values.cluster_name).toBe('${{ parameters.cluster_name }}');
      expect(fetchBaseStep.input.values.dockerfile_path).toBe('${{parameters.dockerfile_path}}');
      expect(fetchBaseStep.input.values.deployment_path).toBe('${{parameters.deployment_path}}');
    });

    it('should handle default values correctly', () => {
      // In GitOps template, check the fetch-base step values
      const fetchBaseStep = templateSpec.spec.steps.find(
        step => step.id === 'fetch-base'
      );

      // Check default value handling in template values
      expect(fetchBaseStep.input.values.dockerfile_path).toBe('${{parameters.dockerfile_path}}');
      expect(fetchBaseStep.input.values.deployment_path).toBe('${{parameters.deployment_path}}');
      expect(fetchBaseStep.input.values.aws_resource_prefix).toBe('peeks');
    });

    it('should reference system information correctly', () => {
      // In GitOps template, check the fetch-base step values
      const fetchBaseStep = templateSpec.spec.steps.find(
        step => step.id === 'fetch-base'
      );

      // Check system information templating
      expect(fetchBaseStep.input.values.gitlab_hostname).toBe("${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
      expect(fetchBaseStep.input.values.git_username).toBe("${{ steps['fetchSystem'].output.entity.spec.gituser }}");
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
      expect(argoCDStep.action).toBe('kube:apply');
      expect(argoCDStep.input.manifest).toContain('${{parameters.appname}}-cicd');
      expect(argoCDStep.input.manifest).toContain('team-${{ parameters.appname }}');
      expect(argoCDStep.input.manifest).toContain('prune: true');
      expect(argoCDStep.input.manifest).toContain('selfHeal: true');
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