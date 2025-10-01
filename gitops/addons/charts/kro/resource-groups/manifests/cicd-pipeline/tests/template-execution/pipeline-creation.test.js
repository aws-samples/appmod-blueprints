import { describe, it, expect, beforeAll } from 'vitest';
import yaml from 'js-yaml';
import fs from 'fs';
import path from 'path';

describe('Complete CI/CD Pipeline Creation', () => {
  let templateContent;
  let templateSpec;
  let rgdContent;
  let rgdSpec;

  beforeAll(() => {
    // Load the Backstage template
    const templatePath = path.resolve(__dirname, '../../../../../../../../platform/backstage/templates/cicd-pipeline/template-cicd-pipeline.yaml');
    templateContent = fs.readFileSync(templatePath, 'utf8');
    templateSpec = yaml.load(templateContent);

    // Load the Kro RGD
    const rgdPath = path.resolve(__dirname, '../../cicd-pipeline.yaml');
    rgdContent = fs.readFileSync(rgdPath, 'utf8');
    rgdSpec = yaml.load(rgdContent);
  });

  describe('Kro RGD Completeness', () => {
    it('should define comprehensive resource templates', () => {
      expect(rgdSpec.spec.resources).toBeDefined();
      expect(rgdSpec.spec.resources.length).toBeGreaterThan(15);

      // Check for key resource types
      const resourceKinds = rgdSpec.spec.resources.map(r => r.template.kind);

      // AWS resources via ACK
      expect(resourceKinds).toContain('Repository'); // ECR
      expect(resourceKinds).toContain('Policy'); // IAM Policy
      expect(resourceKinds).toContain('Role'); // IAM Role
      expect(resourceKinds).toContain('PodIdentityAssociation'); // EKS

      // Kubernetes native resources
      expect(resourceKinds).toContain('Namespace');
      expect(resourceKinds).toContain('ServiceAccount');
      expect(resourceKinds).toContain('Role');
      expect(resourceKinds).toContain('RoleBinding');
      expect(resourceKinds).toContain('ConfigMap');
      expect(resourceKinds).toContain('Secret');
      expect(resourceKinds).toContain('CronJob');
      expect(resourceKinds).toContain('Job');

      // Argo resources
      expect(resourceKinds).toContain('WorkflowTemplate');
      expect(resourceKinds).toContain('Workflow');
      expect(resourceKinds).toContain('EventSource');
      expect(resourceKinds).toContain('Sensor');

      // Networking
      expect(resourceKinds).toContain('Service');
      expect(resourceKinds).toContain('Ingress');
    });

    it('should have readiness conditions for resources', () => {
      const resources = rgdSpec.spec.resources;

      // Check that most resources have readiness conditions
      const resourcesWithReadiness = resources.filter(r => r.readyWhen && r.readyWhen.length > 0);
      expect(resourcesWithReadiness.length).toBeGreaterThan(10);

      // Check specific readiness examples
      const ecrRepo = resources.find(r =>
        r.template.kind === 'Repository' && r.template.apiVersion.includes('ecr')
      );
      expect(ecrRepo.readyWhen).toBeDefined();
      expect(ecrRepo.readyWhen.length).toBeGreaterThan(0);
    });

    it('should have proper resource organization', () => {
      const resources = rgdSpec.spec.resources;

      // All resources should have IDs
      resources.forEach(resource => {
        expect(resource.id).toBeDefined();
        expect(typeof resource.id).toBe('string');
        expect(resource.id.length).toBeGreaterThan(0);
      });

      // All resources should have templates
      resources.forEach(resource => {
        expect(resource.template).toBeDefined();
        expect(resource.template.apiVersion).toBeDefined();
        expect(resource.template.kind).toBeDefined();
      });
    });
  });

  describe('Template to RGD Integration', () => {
    it('should create Kro instance that matches RGD schema', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;

      // Verify the template creates the correct CRD
      expect(manifestTemplate).toContain('apiVersion: kro.run/v1alpha1');
      expect(manifestTemplate).toContain('kind: CICDPipeline');

      // Check that the RGD defines this CRD
      expect(rgdSpec.spec.schema.kind).toBe('CICDPipeline');
      expect(rgdSpec.spec.schema.apiVersion).toBe('v1alpha1');
    });

    it('should provide all required parameters for RGD', () => {
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );

      const manifestTemplate = kubeApplyStep.input.manifest;
      const rgdSchema = rgdSpec.spec.schema.spec;

      // Check required fields are provided
      expect(manifestTemplate).toContain('name:');
      expect(manifestTemplate).toContain('namespace:');
      expect(manifestTemplate).toContain('aws:');
      expect(manifestTemplate).toContain('application:');
      expect(manifestTemplate).toContain('gitlab:');

      // Verify schema defines these fields
      expect(rgdSchema.name).toBeDefined();
      expect(rgdSchema.namespace).toBeDefined();
      expect(rgdSchema.aws).toBeDefined();
      expect(rgdSchema.application).toBeDefined();
      expect(rgdSchema.gitlab).toBeDefined();
    });

    it('should handle default values in schema', () => {
      const rgdSchema = rgdSpec.spec.schema.spec;

      // Check that schema has default values defined
      expect(rgdSchema.aws.resourcePrefix).toContain('default=');
      expect(rgdSchema.application.dockerfilePath).toContain('default=');
      expect(rgdSchema.application.deploymentPath).toContain('default=');
    });
  });

  describe('Complete Pipeline Infrastructure', () => {
    it('should create ECR repositories for application and cache', () => {
      const resources = rgdSpec.spec.resources;

      const ecrRepos = resources.filter(r =>
        r.template.kind === 'Repository' && r.template.apiVersion.includes('ecr')
      );

      expect(ecrRepos.length).toBe(2);

      const mainRepo = ecrRepos.find(r => r.id === 'ecrmainrepo');
      const cacheRepo = ecrRepos.find(r => r.id === 'ecrcacherepo');

      expect(mainRepo).toBeDefined();
      expect(cacheRepo).toBeDefined();
    });

    it('should create IAM resources for ECR access', () => {
      const resources = rgdSpec.spec.resources;

      const iamPolicy = resources.find(r =>
        r.template.kind === 'Policy' && r.template.apiVersion.includes('iam')
      );
      const iamRole = resources.find(r =>
        r.template.kind === 'Role' && r.template.apiVersion.includes('iam')
      );

      expect(iamPolicy).toBeDefined();
      expect(iamRole).toBeDefined();
      expect(iamPolicy.id).toBe('iampolicy');
      expect(iamRole.id).toBe('iamrole');
    });

    it('should create Pod Identity Association for secure AWS access', () => {
      const resources = rgdSpec.spec.resources;

      const podIdentityAssoc = resources.find(r =>
        r.template.kind === 'PodIdentityAssociation'
      );

      expect(podIdentityAssoc).toBeDefined();
      expect(podIdentityAssoc.id).toBe('podidentityassoc');
    });

    it('should create Kubernetes RBAC and service accounts', () => {
      const resources = rgdSpec.spec.resources;

      const namespace = resources.find(r => r.template.kind === 'Namespace');
      const serviceAccount = resources.find(r => r.template.kind === 'ServiceAccount');
      const role = resources.find(r =>
        r.template.kind === 'Role' && !r.template.apiVersion.includes('iam')
      );
      const roleBinding = resources.find(r => r.template.kind === 'RoleBinding');

      expect(namespace).toBeDefined();
      expect(serviceAccount).toBeDefined();
      expect(role).toBeDefined();
      expect(roleBinding).toBeDefined();

      expect(namespace.id).toBe('appnamespace');
      expect(serviceAccount.id).toBe('serviceaccount');
      expect(role.id).toBe('role');
      expect(roleBinding.id).toBe('rolebinding');
    });

    it('should create ConfigMaps and Secrets for pipeline configuration', () => {
      const resources = rgdSpec.spec.resources;

      const configMaps = resources.filter(r => r.template.kind === 'ConfigMap');
      const secrets = resources.filter(r => r.template.kind === 'Secret');

      expect(configMaps.length).toBeGreaterThanOrEqual(1);
      expect(secrets.length).toBeGreaterThanOrEqual(1);

      const mainConfigMap = configMaps.find(r => r.id === 'configmap');
      expect(mainConfigMap).toBeDefined();
    });

    it('should create Argo Workflow templates for CI/CD operations', () => {
      const resources = rgdSpec.spec.resources;

      const workflowTemplates = resources.filter(r =>
        r.template.kind === 'WorkflowTemplate'
      );

      expect(workflowTemplates.length).toBeGreaterThanOrEqual(3);

      const templateIds = workflowTemplates.map(wt => wt.id);
      expect(templateIds).toContain('provisioningworkflow');
      expect(templateIds).toContain('cicdworkflow');
      expect(templateIds).toContain('cachewarmupworkflow');
    });

    it('should create ECR credential refresh mechanism', () => {
      const resources = rgdSpec.spec.resources;

      const cronJob = resources.find(r => r.template.kind === 'CronJob');

      expect(cronJob).toBeDefined();
      expect(cronJob.id).toBe('ecrrefreshcronjob');
    });
  });

  describe('End-to-End Pipeline Validation', () => {
    it('should create a complete CI/CD pipeline from single Kro instance', () => {
      // Verify that the template creates exactly one Kro instance
      const kubeApplySteps = templateSpec.spec.steps.filter(
        step => step.action === 'kube:apply'
      );

      const kroSteps = kubeApplySteps.filter(step =>
        step.input.manifest && step.input.manifest.includes('kind: CICDPipeline')
      );

      expect(kroSteps.length).toBe(1);

      // Verify the RGD creates all necessary resources
      const totalResources = rgdSpec.spec.resources.length;
      expect(totalResources).toBeGreaterThan(15);

      // Count resource types
      const resourceTypes = new Set(rgdSpec.spec.resources.map(r => r.template.kind));
      expect(resourceTypes.size).toBeGreaterThan(8); // Diverse resource types
    });

    it('should provide monitoring and access capabilities', () => {
      const output = templateSpec.spec.output;

      // Should provide links to monitor all aspects of the pipeline
      const linkTitles = output.links.map(link => link.title);

      // Kro instance monitoring
      expect(linkTitles.some(title => title.includes('Kro'))).toBe(true);

      // Workflow monitoring
      expect(linkTitles.some(title => title.includes('Argo Workflows'))).toBe(true);

      // AWS resource monitoring
      expect(linkTitles.some(title => title.includes('ECR'))).toBe(true);
      expect(linkTitles.some(title => title.includes('IAM'))).toBe(true);
      expect(linkTitles.some(title => title.includes('EKS'))).toBe(true);

      // GitOps monitoring
      expect(linkTitles.some(title => title.includes('ArgoCD'))).toBe(true);
      expect(linkTitles.some(title => title.includes('GitLab'))).toBe(true);
    });

    it('should support the complete CI/CD workflow', () => {
      const resources = rgdSpec.spec.resources;

      // Should have resources for each stage of CI/CD

      // Source code management (GitLab integration in template)
      const kubeApplyStep = templateSpec.spec.steps.find(
        step => step.id === 'apply-kro-instance'
      );
      expect(kubeApplyStep.input.manifest).toContain('gitlab:');

      // Build infrastructure (ECR repositories)
      const ecrRepos = resources.filter(r =>
        r.template.kind === 'Repository' && r.template.apiVersion.includes('ecr')
      );
      expect(ecrRepos.length).toBe(2); // Main and cache

      // CI/CD execution (Argo Workflows)
      const workflows = resources.filter(r => r.template.kind === 'WorkflowTemplate');
      expect(workflows.length).toBeGreaterThanOrEqual(3);

      // Deployment management (ArgoCD integration in template)
      const argoCDStep = templateSpec.spec.steps.find(
        step => step.id === 'create-argocd-app'
      );
      expect(argoCDStep).toBeDefined();

      // Security and access (IAM, Pod Identity, RBAC)
      const securityResources = resources.filter(r =>
        r.template.kind === 'Role' ||
        r.template.kind === 'Policy' ||
        r.template.kind === 'PodIdentityAssociation' ||
        r.template.kind === 'RoleBinding'
      );
      expect(securityResources.length).toBeGreaterThanOrEqual(3);
    });
  });
});