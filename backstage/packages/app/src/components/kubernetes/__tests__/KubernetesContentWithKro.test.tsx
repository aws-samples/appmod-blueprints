import React from 'react';
import { render, screen } from '@testing-library/react';
import { EntityProvider } from '@backstage/plugin-catalog-react';
import { TestApiProvider } from '@backstage/test-utils';
import { Entity } from '@backstage/catalog-model';
import { KubernetesContentWithKro, hasKroIntegration } from '../KubernetesContentWithKro';

// Mock the Kro plugin components
jest.mock('@terasky/backstage-plugin-kro-resources-frontend', () => ({
  IfKroResourceGraphAvailable: ({ children }: { children: React.ReactNode }) => <div data-testid="kro-resource-graph">{children}</div>,
  KroResourceGraph: () => <div data-testid="kro-resource-graph-content">Kro Resource Graph</div>,
  KroOverviewCard: () => <div data-testid="kro-overview-card">Kro Overview</div>,
  IfKroOverviewAvailable: ({ children }: { children: React.ReactNode }) => <div data-testid="kro-overview">{children}</div>,
}));

// Mock the Kubernetes plugin
jest.mock('@backstage/plugin-kubernetes', () => ({
  EntityKubernetesContent: () => <div data-testid="kubernetes-content">Kubernetes Content</div>,
}));

const mockKroResourceGroupEntity: Entity = {
  apiVersion: 'backstage.io/v1alpha1',
  kind: 'Component',
  metadata: {
    name: 'test-resource-group',
    namespace: 'default',
    annotations: {
      'backstage.io/kubernetes-id': 'test-resource-group',
      'kro.run/resource-group': 'test-resource-group',
    },
  },
  spec: {
    type: 'kro-resource-group',
    lifecycle: 'production',
    owner: 'team-a',
  },
};

const mockManagedResourceEntity: Entity = {
  apiVersion: 'backstage.io/v1alpha1',
  kind: 'Component',
  metadata: {
    name: 'managed-service',
    namespace: 'default',
    annotations: {
      'backstage.io/kubernetes-id': 'managed-service',
      'kro.run/resource-group': 'test-resource-group',
      'kro.run/managed-by': 'test-resource-group',
    },
  },
  spec: {
    type: 'service',
    lifecycle: 'production',
    owner: 'team-a',
  },
};

const mockStandardEntity: Entity = {
  apiVersion: 'backstage.io/v1alpha1',
  kind: 'Component',
  metadata: {
    name: 'standard-service',
    namespace: 'default',
  },
  spec: {
    type: 'service',
    lifecycle: 'production',
    owner: 'team-a',
  },
};

describe('KubernetesContentWithKro', () => {
  const renderWithEntity = (entity: Entity) => {
    return render(
      <TestApiProvider apis={[]}>
        <EntityProvider entity={entity}>
          <KubernetesContentWithKro />
        </EntityProvider>
      </TestApiProvider>
    );
  };

  it('should render Kro integration for ResourceGroup entities', () => {
    renderWithEntity(mockKroResourceGroupEntity);

    expect(screen.getByText('Kro Integration')).toBeInTheDocument();
    expect(screen.getByText('Kro ResourceGroup')).toBeInTheDocument();
    expect(screen.getByTestId('kro-overview')).toBeInTheDocument();
    expect(screen.getByTestId('kro-resource-graph')).toBeInTheDocument();
    expect(screen.getByTestId('kubernetes-content')).toBeInTheDocument();
  });

  it('should render Kro integration for managed resources', () => {
    renderWithEntity(mockManagedResourceEntity);

    expect(screen.getByText('Kro Integration')).toBeInTheDocument();
    expect(screen.getByText('Managed by Kro')).toBeInTheDocument();
    expect(screen.getByText('ResourceGroup: test-resource-group')).toBeInTheDocument();
    expect(screen.getByTestId('kubernetes-content')).toBeInTheDocument();

    // Should not show ResourceGroup-specific components for managed resources
    expect(screen.queryByTestId('kro-overview')).not.toBeInTheDocument();
    expect(screen.queryByTestId('kro-resource-graph')).not.toBeInTheDocument();
  });

  it('should render only standard Kubernetes content for standard entities', () => {
    renderWithEntity(mockStandardEntity);

    expect(screen.queryByText('Kro Integration')).not.toBeInTheDocument();
    expect(screen.getByTestId('kubernetes-content')).toBeInTheDocument();
  });
});

describe('hasKroIntegration', () => {
  it('should return true for Kro ResourceGroup entities', () => {
    expect(hasKroIntegration(mockKroResourceGroupEntity)).toBe(true);
  });

  it('should return true for entities managed by Kro', () => {
    expect(hasKroIntegration(mockManagedResourceEntity)).toBe(true);
  });

  it('should return false for standard entities', () => {
    expect(hasKroIntegration(mockStandardEntity)).toBe(false);
  });

  it('should return true for entities with kro.run/managed-by annotation', () => {
    const entityWithManagedBy: Entity = {
      ...mockStandardEntity,
      metadata: {
        ...mockStandardEntity.metadata,
        annotations: {
          'kro.run/managed-by': 'some-resource-group',
        },
      },
    };

    expect(hasKroIntegration(entityWithManagedBy)).toBe(true);
  });
});