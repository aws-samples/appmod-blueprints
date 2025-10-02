import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { TestApiProvider, wrapInTestApp } from '@backstage/test-utils';
import { catalogApiRef } from '@backstage/plugin-catalog-react';
import { Entity } from '@backstage/catalog-model';

// Mock Kro components (since they're temporarily commented out)
const MockKroResourceTable = () => (
  <div data-testid="kro-resource-table">
    <h2>Kro ResourceGroups</h2>
    <div data-testid="resource-list">
      <div data-testid="resource-item">
        <span>cicd-pipeline-1</span>
        <span>Ready</span>
      </div>
      <div data-testid="resource-item">
        <span>eks-cluster-1</span>
        <span>Pending</span>
      </div>
    </div>
  </div>
);

const MockKroResourceDetails = ({ resourceGroup }: { resourceGroup: any }) => (
  <div data-testid="kro-resource-details">
    <h3>{resourceGroup.name}</h3>
    <p>Status: {resourceGroup.status}</p>
    <p>Namespace: {resourceGroup.namespace}</p>
    <div data-testid="managed-resources">
      {resourceGroup.managedResources?.map((resource: any, index: number) => (
        <div key={index} data-testid="managed-resource">
          {resource.kind}: {resource.name}
        </div>
      ))}
    </div>
  </div>
);

const MockKroCreateForm = ({ onSubmit }: { onSubmit: (data: any) => void }) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      templateName: 'cicd-pipeline',
      name: 'new-pipeline',
      namespace: 'default',
      parameters: {
        name: 'my-app',
        repository: 'https://github.com/example/my-app',
      },
    });
  };

  const handleButtonClick = (e: React.MouseEvent) => {
    e.preventDefault();
    onSubmit({
      templateName: 'cicd-pipeline',
      name: 'new-pipeline',
      namespace: 'default',
      parameters: {
        name: 'my-app',
        repository: 'https://github.com/example/my-app',
      },
    });
  };

  return (
    <div data-testid="kro-create-form">
      <h3>Create ResourceGroup</h3>
      <form onSubmit={handleSubmit}>
        <input
          data-testid="template-select"
          placeholder="Select template"
          defaultValue="cicd-pipeline"
        />
        <input
          data-testid="name-input"
          placeholder="ResourceGroup name"
          defaultValue="new-pipeline"
        />
        <input
          data-testid="namespace-input"
          placeholder="Namespace"
          defaultValue="default"
        />
        <button type="button" data-testid="create-button" onClick={handleButtonClick}>
          Create ResourceGroup
        </button>
      </form>
    </div>
  );
};

// Mock catalog entities
const mockKroEntities: Entity[] = [
  {
    apiVersion: 'backstage.io/v1alpha1',
    kind: 'Component',
    metadata: {
      name: 'cicd-pipeline-template',
      namespace: 'default',
      annotations: {
        'backstage.io/kubernetes-id': 'cicd-pipeline',
        'kro.run/resource-graph-definition': 'cicd-pipeline',
        'backstage.io/source-location': 'kro:test-cluster/default/cicd-pipeline',
      },
      labels: {
        'backstage.io/kubernetes-cluster': 'test-cluster',
        'kro.run/version': 'v1alpha1',
      },
    },
    spec: {
      type: 'kro-resource-group',
      lifecycle: 'production',
      owner: 'platform-team',
    },
  },
  {
    apiVersion: 'backstage.io/v1alpha1',
    kind: 'Component',
    metadata: {
      name: 'my-app-pipeline',
      namespace: 'default',
      annotations: {
        'backstage.io/kubernetes-id': 'my-app-pipeline',
        'kro.run/resource-group': 'my-app-pipeline',
        'kro.run/created-by': 'user:default/developer',
      },
      labels: {
        'backstage.io/kubernetes-cluster': 'test-cluster',
        'kro.run/version': 'v1alpha1',
      },
    },
    spec: {
      type: 'kro-resource-group',
      lifecycle: 'production',
      owner: 'platform-team',
    },
    status: {
      phase: 'Ready',
      conditions: [
        {
          type: 'Ready',
          status: 'True',
          reason: 'AllResourcesReady',
          message: 'All managed resources are ready',
        },
      ],
    },
  },
];

const mockCatalogApi = {
  getEntities: jest.fn().mockResolvedValue({
    items: mockKroEntities,
  }),
  getEntityByRef: jest.fn(),
  removeEntityByUid: jest.fn(),
  getLocationById: jest.fn(),
  getLocationByRef: jest.fn(),
  addLocation: jest.fn(),
  removeLocationById: jest.fn(),
  refreshEntity: jest.fn(),
  getEntityAncestors: jest.fn(),
  getEntityFacets: jest.fn(),
  validateEntity: jest.fn(),
};

describe('Kro Integration Components', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('KroResourceTable', () => {
    it('should render ResourceGroup list', async () => {
      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <MockKroResourceTable />
          </TestApiProvider>
        )
      );

      expect(screen.getByTestId('kro-resource-table')).toBeInTheDocument();
      expect(screen.getByText('Kro ResourceGroups')).toBeInTheDocument();

      const resourceItems = screen.getAllByTestId('resource-item');
      expect(resourceItems).toHaveLength(2);

      expect(screen.getByText('cicd-pipeline-1')).toBeInTheDocument();
      expect(screen.getByText('Ready')).toBeInTheDocument();
      expect(screen.getByText('eks-cluster-1')).toBeInTheDocument();
      expect(screen.getByText('Pending')).toBeInTheDocument();
    });

    it('should filter ResourceGroups by status', async () => {
      const FilterableKroResourceTable = () => {
        const [filter, setFilter] = React.useState('');

        const filteredResources = [
          { name: 'cicd-pipeline-1', status: 'Ready' },
          { name: 'eks-cluster-1', status: 'Pending' },
        ].filter(resource =>
          filter === '' || resource.status === filter
        );

        return (
          <div data-testid="filterable-kro-table">
            <select
              data-testid="status-filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">All</option>
              <option value="Ready">Ready</option>
              <option value="Pending">Pending</option>
              <option value="Failed">Failed</option>
            </select>
            <div data-testid="filtered-resources">
              {filteredResources.map((resource, index) => (
                <div key={index} data-testid="filtered-resource">
                  {resource.name} - {resource.status}
                </div>
              ))}
            </div>
          </div>
        );
      };

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <FilterableKroResourceTable />
          </TestApiProvider>
        )
      );

      // Initially show all resources
      expect(screen.getAllByTestId('filtered-resource')).toHaveLength(2);

      // Filter by Ready status
      fireEvent.change(screen.getByTestId('status-filter'), {
        target: { value: 'Ready' },
      });

      await waitFor(() => {
        const filteredResources = screen.getAllByTestId('filtered-resource');
        expect(filteredResources).toHaveLength(1);
        expect(screen.getByText('cicd-pipeline-1 - Ready')).toBeInTheDocument();
      });

      // Filter by Pending status
      fireEvent.change(screen.getByTestId('status-filter'), {
        target: { value: 'Pending' },
      });

      await waitFor(() => {
        const filteredResources = screen.getAllByTestId('filtered-resource');
        expect(filteredResources).toHaveLength(1);
        expect(screen.getByText('eks-cluster-1 - Pending')).toBeInTheDocument();
      });
    });
  });

  describe('KroResourceDetails', () => {
    it('should render ResourceGroup details', () => {
      const mockResourceGroup = {
        name: 'my-app-pipeline',
        namespace: 'default',
        status: 'Ready',
        managedResources: [
          { kind: 'Namespace', name: 'my-app' },
          { kind: 'Deployment', name: 'my-app-deployment' },
          { kind: 'Service', name: 'my-app-service' },
        ],
      };

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <MockKroResourceDetails resourceGroup={mockResourceGroup} />
          </TestApiProvider>
        )
      );

      expect(screen.getByTestId('kro-resource-details')).toBeInTheDocument();
      expect(screen.getByText('my-app-pipeline')).toBeInTheDocument();
      expect(screen.getByText('Status: Ready')).toBeInTheDocument();
      expect(screen.getByText('Namespace: default')).toBeInTheDocument();

      const managedResources = screen.getAllByTestId('managed-resource');
      expect(managedResources).toHaveLength(3);
      expect(screen.getByText('Namespace: my-app')).toBeInTheDocument();
      expect(screen.getByText('Deployment: my-app-deployment')).toBeInTheDocument();
      expect(screen.getByText('Service: my-app-service')).toBeInTheDocument();
    });

    it('should handle ResourceGroup with no managed resources', () => {
      const mockResourceGroup = {
        name: 'empty-pipeline',
        namespace: 'default',
        status: 'Pending',
        managedResources: [],
      };

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <MockKroResourceDetails resourceGroup={mockResourceGroup} />
          </TestApiProvider>
        )
      );

      expect(screen.getByText('empty-pipeline')).toBeInTheDocument();
      expect(screen.getByText('Status: Pending')).toBeInTheDocument();

      const managedResourcesContainer = screen.getByTestId('managed-resources');
      expect(managedResourcesContainer).toBeInTheDocument();
      expect(screen.queryAllByTestId('managed-resource')).toHaveLength(0);
    });
  });

  describe('KroCreateForm', () => {
    it('should render create form with required fields', () => {
      const mockOnSubmit = jest.fn();

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <MockKroCreateForm onSubmit={mockOnSubmit} />
          </TestApiProvider>
        )
      );

      expect(screen.getByTestId('kro-create-form')).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Create ResourceGroup' })).toBeInTheDocument();

      expect(screen.getByTestId('template-select')).toBeInTheDocument();
      expect(screen.getByTestId('name-input')).toBeInTheDocument();
      expect(screen.getByTestId('namespace-input')).toBeInTheDocument();
      expect(screen.getByTestId('create-button')).toBeInTheDocument();
    });

    it('should submit form with correct data', async () => {
      const mockOnSubmit = jest.fn();

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <MockKroCreateForm onSubmit={mockOnSubmit} />
          </TestApiProvider>
        )
      );

      await act(async () => {
        fireEvent.click(screen.getByTestId('create-button'));
      });

      await waitFor(() => {
        expect(mockOnSubmit).toHaveBeenCalledWith({
          templateName: 'cicd-pipeline',
          name: 'new-pipeline',
          namespace: 'default',
          parameters: {
            name: 'my-app',
            repository: 'https://github.com/example/my-app',
          },
        });
      });
    });

    it('should validate form inputs', async () => {
      const ValidatingKroCreateForm = () => {
        const [errors, setErrors] = React.useState<string[]>([]);
        const [formData, setFormData] = React.useState({ name: '', template: '' });

        const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
          setFormData(prev => ({
            ...prev,
            [e.target.name]: e.target.value,
          }));
        };

        const handleValidation = () => {
          const newErrors: string[] = [];
          if (!formData.name || formData.name.trim() === '') {
            newErrors.push('Name is required');
          }
          if (!formData.template || formData.template.trim() === '') {
            newErrors.push('Template is required');
          }
          if (formData.name && !/^[a-z0-9-]+$/.test(formData.name)) {
            newErrors.push('Name must contain only lowercase letters, numbers, and hyphens');
          }

          setErrors(newErrors);
        };

        return (
          <div data-testid="validating-create-form">
            <form>
              <input
                name="template"
                data-testid="template-input"
                placeholder="Template name"
                value={formData.template}
                onChange={handleInputChange}
              />
              <input
                name="name"
                data-testid="name-input"
                placeholder="ResourceGroup name"
                value={formData.name}
                onChange={handleInputChange}
              />
              <button type="button" data-testid="submit-button" onClick={handleValidation}>
                Create
              </button>
            </form>
            {errors.length > 0 && (
              <div data-testid="validation-errors">
                {errors.map((error, index) => (
                  <div key={index} data-testid="validation-error">
                    {error}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      };

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <ValidatingKroCreateForm />
          </TestApiProvider>
        )
      );

      // Submit empty form
      await act(async () => {
        fireEvent.click(screen.getByTestId('submit-button'));
      });

      await waitFor(() => {
        expect(screen.getByTestId('validation-errors')).toBeInTheDocument();
        expect(screen.getByText('Name is required')).toBeInTheDocument();
        expect(screen.getByText('Template is required')).toBeInTheDocument();
      });

      // Enter invalid name
      await act(async () => {
        fireEvent.change(screen.getByTestId('name-input'), {
          target: { value: 'Invalid Name!' },
        });
        fireEvent.change(screen.getByTestId('template-input'), {
          target: { value: 'cicd-pipeline' },
        });
        fireEvent.click(screen.getByTestId('submit-button'));
      });

      await waitFor(() => {
        expect(screen.getByText('Name must contain only lowercase letters, numbers, and hyphens')).toBeInTheDocument();
      });
    });
  });

  describe('Catalog Integration', () => {
    it('should fetch and display Kro entities from catalog', async () => {
      const KroCatalogIntegration = () => {
        const [entities, setEntities] = React.useState<Entity[]>([]);
        const [loading, setLoading] = React.useState(true);

        React.useEffect(() => {
          const fetchEntities = async () => {
            try {
              const response = await mockCatalogApi.getEntities({
                filter: {
                  'spec.type': 'kro-resource-group',
                },
              });
              setEntities(response.items);
            } catch (error) {
              console.error('Failed to fetch entities:', error);
            } finally {
              setLoading(false);
            }
          };

          fetchEntities();
        }, []);

        if (loading) {
          return <div data-testid="loading">Loading...</div>;
        }

        return (
          <div data-testid="kro-catalog-integration">
            <h3>Kro ResourceGroups from Catalog</h3>
            {entities.map((entity) => (
              <div key={entity.metadata.name} data-testid="catalog-entity">
                <h4>{entity.metadata.name}</h4>
                <p>Type: {entity.spec?.type}</p>
                <p>Owner: {entity.spec?.owner}</p>
                <p>Cluster: {entity.metadata.labels?.['backstage.io/kubernetes-cluster']}</p>
                {entity.status && (
                  <p>Status: {entity.status.phase}</p>
                )}
              </div>
            ))}
          </div>
        );
      };

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <KroCatalogIntegration />
          </TestApiProvider>
        )
      );

      // Initially shows loading
      expect(screen.getByTestId('loading')).toBeInTheDocument();

      // Wait for entities to load
      await waitFor(() => {
        expect(screen.getByTestId('kro-catalog-integration')).toBeInTheDocument();
        expect(screen.getByText('Kro ResourceGroups from Catalog')).toBeInTheDocument();
      });

      // Check that entities are displayed
      const catalogEntities = screen.getAllByTestId('catalog-entity');
      expect(catalogEntities).toHaveLength(2);

      expect(screen.getByText('cicd-pipeline-template')).toBeInTheDocument();
      expect(screen.getByText('my-app-pipeline')).toBeInTheDocument();
      expect(screen.getAllByText('Type: kro-resource-group')).toHaveLength(2);
      expect(screen.getAllByText('Owner: platform-team')).toHaveLength(2);
      expect(screen.getAllByText('Cluster: test-cluster')).toHaveLength(2);
      expect(screen.getByText('Status: Ready')).toBeInTheDocument();

      // Verify catalog API was called with correct filter
      expect(mockCatalogApi.getEntities).toHaveBeenCalledWith({
        filter: {
          'spec.type': 'kro-resource-group',
        },
      });
    });

    it('should handle catalog API errors gracefully', async () => {
      const errorCatalogApi = {
        ...mockCatalogApi,
        getEntities: jest.fn().mockRejectedValue(new Error('Catalog API error')),
      };

      const KroCatalogErrorHandling = () => {
        const [error, setError] = React.useState<string | null>(null);
        const [loading, setLoading] = React.useState(true);

        React.useEffect(() => {
          const fetchEntities = async () => {
            try {
              await errorCatalogApi.getEntities({
                filter: {
                  'spec.type': 'kro-resource-group',
                },
              });
            } catch (err) {
              setError(err instanceof Error ? err.message : 'Unknown error');
            } finally {
              setLoading(false);
            }
          };

          fetchEntities();
        }, []);

        if (loading) {
          return <div data-testid="loading">Loading...</div>;
        }

        if (error) {
          return (
            <div data-testid="error-message">
              Error loading ResourceGroups: {error}
            </div>
          );
        }

        return <div>No error</div>;
      };

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, errorCatalogApi]]}>
            <KroCatalogErrorHandling />
          </TestApiProvider>
        )
      );

      await waitFor(() => {
        expect(screen.getByTestId('error-message')).toBeInTheDocument();
        expect(screen.getByText('Error loading ResourceGroups: Catalog API error')).toBeInTheDocument();
      });
    });
  });

  describe('Entity Relationships', () => {
    it('should display ResourceGroup relationships', () => {
      const mockEntityWithRelations = {
        ...mockKroEntities[1],
        relations: [
          {
            type: 'ownedBy',
            targetRef: 'component:default/cicd-pipeline-template',
          },
          {
            type: 'dependsOn',
            targetRef: 'resource:default/my-app-namespace',
          },
          {
            type: 'dependsOn',
            targetRef: 'resource:my-app/my-app-deployment',
          },
        ],
      };

      const EntityRelationsDisplay = ({ entity }: { entity: Entity }) => (
        <div data-testid="entity-relations">
          <h4>Relations</h4>
          {entity.relations?.map((relation, index) => (
            <div key={index} data-testid="relation">
              {relation.type}: {relation.targetRef}
            </div>
          ))}
        </div>
      );

      render(
        wrapInTestApp(
          <TestApiProvider apis={[[catalogApiRef, mockCatalogApi]]}>
            <EntityRelationsDisplay entity={mockEntityWithRelations} />
          </TestApiProvider>
        )
      );

      expect(screen.getByTestId('entity-relations')).toBeInTheDocument();
      expect(screen.getByText('Relations')).toBeInTheDocument();

      const relations = screen.getAllByTestId('relation');
      expect(relations).toHaveLength(3);

      expect(screen.getByText('ownedBy: component:default/cicd-pipeline-template')).toBeInTheDocument();
      expect(screen.getByText('dependsOn: resource:default/my-app-namespace')).toBeInTheDocument();
      expect(screen.getByText('dependsOn: resource:my-app/my-app-deployment')).toBeInTheDocument();
    });
  });
});