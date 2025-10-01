import { describe, it, expect, beforeAll } from 'vitest';

describe('Integration Test Setup Verification', () => {
  let kubernetesClient;
  let awsClient;

  beforeAll(async () => {
    kubernetesClient = globalThis.kubernetesClient;
    awsClient = globalThis.awsClient;

    console.log('kubernetesClient:', kubernetesClient ? 'defined' : 'undefined');
    console.log('awsClient:', awsClient ? 'defined' : 'undefined');
  });

  it('should have kubernetesClient available', () => {
    expect(kubernetesClient).toBeDefined();
    expect(kubernetesClient.mockMode).toBeDefined();
  });

  it('should have awsClient available', () => {
    expect(awsClient).toBeDefined();
    expect(awsClient.mockMode).toBeDefined();
  });

  it('should be running in mock mode', () => {
    expect(kubernetesClient.mockMode).toBe(true);
    expect(awsClient.mockMode).toBe(true);
  });
});