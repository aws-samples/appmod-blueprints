import { describe, it, expect, beforeAll } from 'vitest';
import yaml from 'js-yaml';
import fs from 'fs';
import path from 'path';

describe('GitLab Integration and ArgoCD App Creation', () => {
  let templateContent;
  let templateSpec;

  beforeAll(() => {
    // Load the Backstage template
    const templatePath = path.resolve(__dirname, '../../../../../../platform/backstage/templates/cicd-pipeline/template-cicd-pipeline-gitops.yaml');
    templateContent = fs.readFileSync(templatePath, 'utf8');
    templateSpec = yaml.load(templateContent);
  });

  describe('GitLab Integration', () => {
    it('should configure GitLab repository creation correctly', () => {
      const publishStep = templateSpec.spec.steps.find(
        step => step.id === 'publish'
      );

      expect(publishStep).toBeDefined();
      expect(publishStep.name).toBe('Publishing to GitLab repository');
      expect(publishStep.action).toBe('publish:gitlab');

      const input = publishStep.input;
      expect(input.repoUrl).toContain('${{parameters.appname}}-cicd');
      expect(input.repoUrl).toContain("${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
      expect(input.repoUrl).toContain("${{ steps['fetchSystem'].output.entity.spec.gituser }}");
      expect(input.defaultBranch).toBe('main');
      expect(input.useCustomGit).toBe(true);
    });

    it('should fetch system information before GitLab operations', () => {
      const fetchSystemStep = templateSpec.spec.steps.find(
        step => step.id === 'fetchSystem'
      );

      expect(fetchSystemStep).toBeDefined();
      expect(fetchSystemStep.action).toBe('catalog:fetch');
      expect(fetchSystemStep.input.entityRef).toBe('system:default/system-info');

      // Verify it comes before publish step
      const steps = templateSpec.spec.steps;
      const fetchIndex = steps.findIndex(step => step.id === 'fetchSystem');
      const publishIndex = steps.findIndex(step => step.id === 'publish');
      expect(fetchIndex).toBeLessThan(publishIndex);
    });

    it('should use system information in Kro instance', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Check GitLab configuration in Kro instance
      expect(manifestTemplate).toContain('gitlab:');
      expect(manifestTemplate).toContain("hostname: ${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
      expect(manifestTemplate).toContain("username: ${{ steps['fetchSystem'].output.entity.spec.gituser }}");
    });

    it('should provide GitLab repository link in output', () => {
      const output = templateSpec.spec.output;
      const gitlabLink = output.links.find(link => link.title === 'GitLab Repository (GitOps Source)');

      expect(gitlabLink).toBeDefined();
      expect(gitlabLink.icon).toBe('git');
      expect(gitlabLink.url).toContain("${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
      expect(gitlabLink.url).toContain("${{ steps['fetchSystem'].output.entity.spec.gituser }}");
      expect(gitlabLink.url).toContain('${{ parameters.appname }}-cicd');
    });
  });

  describe('ArgoCD Application Creation', () => {
    it('should create ArgoCD application with correct configuration', () => {
      const argoCDStep = templateSpec.spec.steps.find(
        step => step.id === 'create-argocd-app'
      );

      expect(argoCDStep).toBeDefined();
      expect(argoCDStep.name).toBe('Create ArgoCD Application (GitOps)');
      expect(argoCDStep.action).toBe('argocd:create-resources');

      const input = argoCDStep.input;
      expect(input.appName).toBe('${{parameters.appname}}-cicd');
      expect(input.namespace).toBe('team-${{ parameters.appname }}');
      expect(input.argoInstance).toBe('in-cluster');
      expect(input.projectName).toBe('default');
    });

    it('should configure repository URL correctly for ArgoCD', () => {
      const argoCDStep = templateSpec.spec.steps.find(
        step => step.id === 'create-argocd-app'
      );

      const input = argoCDStep.input;
      expect(input.repoUrl).toContain("${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
      expect(input.repoUrl).toContain("${{ steps['fetchSystem'].output.entity.spec.gituser }}");
      expect(input.repoUrl).toContain('${{parameters.appname}}-cicd');
      expect(input.path).toBe('manifests');
    });

    it('should configure automated sync policy', () => {
      const argoCDStep = templateSpec.spec.steps.find(
        step => step.id === 'create-argocd-app'
      );

      const syncPolicy = argoCDStep.input.syncPolicy;
      expect(syncPolicy).toBeDefined();
      expect(syncPolicy.automated).toBeDefined();
      expect(syncPolicy.automated.prune).toBe(true);
      expect(syncPolicy.automated.selfHeal).toBe(true);

      expect(syncPolicy.syncOptions).toBeDefined();
      expect(syncPolicy.syncOptions).toContain('CreateNamespace=true');
      expect(syncPolicy.syncOptions).toContain('ApplyOutOfSyncOnly=true');
    });

    it('should execute ArgoCD creation after Kro instance', () => {
      const steps = templateSpec.spec.steps;
      const kroIndex = steps.findIndex(step => step.id === 'apply-kro-instance');
      const argoCDIndex = steps.findIndex(step => step.id === 'create-argocd-app');

      expect(kroIndex).toBeLessThan(argoCDIndex);
    });

    it('should provide ArgoCD application link in output', () => {
      const output = templateSpec.spec.output;
      const argoCDLink = output.links.find(link => link.title === 'ArgoCD CI/CD Pipeline Application');

      expect(argoCDLink).toBeDefined();
      expect(argoCDLink.icon).toBe('web');
      expect(argoCDLink.url).toContain('/argocd/applications/argocd/');
      expect(argoCDLink.url).toContain('${{ parameters.appname }}-cicd');
    });
  });

  describe('Catalog Registration', () => {
    it('should register component in Backstage catalog', () => {
      const registerStep = templateSpec.spec.steps.find(
        step => step.id === 'register'
      );

      expect(registerStep).toBeDefined();
      expect(registerStep.action).toBe('catalog:register');
      expect(registerStep.input.repoContentsUrl).toBe("${{ steps['publish'].output.repoContentsUrl }}");
      expect(registerStep.input.catalogInfoPath).toBe('/catalog-info.yaml');
    });

    it('should execute registration after GitLab publish', () => {
      const steps = templateSpec.spec.steps;
      const publishIndex = steps.findIndex(step => step.id === 'publish');
      const registerIndex = steps.findIndex(step => step.id === 'register');

      expect(publishIndex).toBeLessThan(registerIndex);
    });

    it('should provide catalog link in output', () => {
      const output = templateSpec.spec.output;
      const catalogLink = output.links.find(link => link.title === 'Open in catalog');

      expect(catalogLink).toBeDefined();
      expect(catalogLink.icon).toBe('catalog');
      expect(catalogLink.entityRef).toBe("${{ steps['register'].output.entityRef }}");
    });
  });

  describe('Integration Workflow Validation', () => {
    it('should have proper step dependencies', () => {
      const steps = templateSpec.spec.steps;
      const stepIds = steps.map(step => step.id);

      // Verify critical dependency order
      const fetchSystemIndex = stepIds.indexOf('fetchSystem');
      const publishIndex = stepIds.indexOf('publish');
      const applyKroIndex = stepIds.indexOf('apply-kro-instance');
      const createArgoCDIndex = stepIds.indexOf('create-argocd-app');
      const registerIndex = stepIds.indexOf('register');

      // fetchSystem must come first (provides system info)
      expect(fetchSystemIndex).toBeLessThan(publishIndex);
      expect(fetchSystemIndex).toBeLessThan(applyKroIndex);

      // publish must come before register (creates repo first)
      expect(publishIndex).toBeLessThan(registerIndex);

      // Kro instance should be applied before ArgoCD app
      expect(applyKroIndex).toBeLessThan(createArgoCDIndex);
    });

    it('should validate template fetching configuration', () => {
      const fetchBaseStep = templateSpec.spec.steps.find(
        step => step.id === 'fetch-base'
      );

      expect(fetchBaseStep).toBeDefined();
      expect(fetchBaseStep.action).toBe('fetch:template');
      expect(fetchBaseStep.input.url).toBe('./skeleton/');

      const values = fetchBaseStep.input.values;
      expect(values.appname).toBe('${{ parameters.appname }}');
      expect(values.namespace).toBe('team-${{ parameters.appname }}');
      expect(values.aws_region).toBe('${{ parameters.aws_region }}');
      expect(values.gitlab_hostname).toBe("${{ steps['fetchSystem'].output.entity.spec.gitlab_hostname }}");
    });
  });

  describe('Error Handling and Validation', () => {
    it('should include parameter validation step', () => {
      const validateStep = templateSpec.spec.steps.find(
        step => step.id === 'validate-parameters'
      );

      expect(validateStep).toBeDefined();
      expect(validateStep.action).toBe('debug:log');

      const message = validateStep.input.message;
      expect(message).toContain('Validating template parameters');
      expect(message).toContain('${{ parameters.appname }}');
      expect(message).toContain('${{ parameters.aws_region }}');
      expect(message).toContain('Validation checks');
    });

    it('should include Kro instance validation step', () => {
      const validateKroStep = templateSpec.spec.steps.find(
        step => step.id === 'validate-kro-instance'
      );

      expect(validateKroStep).toBeDefined();
      expect(validateKroStep.action).toBe('debug:log');

      const message = validateKroStep.input.message;
      expect(message).toContain('Kro CI/CD Pipeline instance created successfully');
      expect(message).toContain('Resource Provisioning');
      expect(message).toContain('Expected Timeline');
    });

    it('should provide comprehensive access information', () => {
      const accessInfoStep = templateSpec.spec.steps.find(
        step => step.id === 'provide-access-information'
      );

      expect(accessInfoStep).toBeDefined();
      expect(accessInfoStep.action).toBe('debug:log');

      const message = accessInfoStep.input.message;
      expect(message).toContain('CI/CD Pipeline Successfully Deployed');
      expect(message).toContain('Monitoring & Management');
      expect(message).toContain('Quick Access Links');
      expect(message).toContain('Getting Started');
    });
  });

  describe('Output Completeness', () => {
    it('should provide all necessary monitoring links', () => {
      const output = templateSpec.spec.output;
      const linkTitles = output.links.map(link => link.title);

      // Kro and Kubernetes links
      expect(linkTitles).toContain('Kro CI/CD Pipeline Instance');
      expect(linkTitles).toContain('Kubernetes Namespace');

      // Argo Workflows links
      expect(linkTitles.some(title => title.includes('Argo Workflows'))).toBe(true);

      // AWS resource links
      expect(linkTitles).toContain('ECR Main Repository');
      expect(linkTitles).toContain('ECR Cache Repository');
      expect(linkTitles).toContain('IAM Role');
      expect(linkTitles).toContain('IAM Policy');
      expect(linkTitles).toContain('EKS Pod Identity Association');
      expect(linkTitles).toContain('EKS Cluster');

      // GitOps links
      expect(linkTitles).toContain('ArgoCD CI/CD Pipeline Application');
      expect(linkTitles).toContain('GitLab Repository');
    });

    it('should provide comprehensive text documentation', () => {
      const output = templateSpec.spec.output;
      const textContent = output.text[0].content;

      expect(textContent).toContain('Pipeline Overview');
      expect(textContent).toContain('AWS Resources (via ACK Controllers)');
      expect(textContent).toContain('Kubernetes Resources');
      expect(textContent).toContain('Argo Workflows Templates');
      expect(textContent).toContain('Build & Deployment Configuration');
      expect(textContent).toContain('GitLab Integration');
      expect(textContent).toContain('ArgoCD Applications');
      expect(textContent).toContain('Security Features');
      expect(textContent).toContain('Monitoring & Observability');
      expect(textContent).toContain('Next Steps');
    });
  });
});