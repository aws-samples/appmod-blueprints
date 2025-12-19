import { beforeAll, afterAll } from 'vitest';
import { KubernetesTestClient } from '../utils/kubernetes-client.js';
import { AWSTestClient } from '../utils/aws-client.js';

let kubernetesClient;
let awsClient;

beforeAll(async () => {
  console.log('🚀 Setting up integration test environment...');

  // Initialize test clients
  kubernetesClient = new KubernetesTestClient();
  awsClient = new AWSTestClient();

  // Verify cluster connectivity
  try {
    await kubernetesClient.verifyConnection();
    console.log('✅ Kubernetes cluster connection verified');
  } catch (error) {
    console.warn('⚠️  Kubernetes cluster not available, running in mock mode');
    kubernetesClient.mockMode = true;
  }

  // Verify AWS connectivity
  try {
    await awsClient.verifyConnection();
    console.log('✅ AWS connection verified');
  } catch (error) {
    console.warn('⚠️  AWS not available, running in mock mode');
    awsClient.mockMode = true;
  }

  // Make clients available globally
  globalThis.kubernetesClient = kubernetesClient;
  globalThis.awsClient = awsClient;

  console.log('✅ Integration test environment setup complete');
});

afterAll(async () => {
  console.log('🧹 Cleaning up integration test environment...');

  // Cleanup any test resources
  if (kubernetesClient) {
    await kubernetesClient.cleanup();
  }
  if (awsClient) {
    await awsClient.cleanup();
  }

  console.log('✅ Integration test environment cleanup complete');
});