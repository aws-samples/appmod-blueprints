---
inclusion: fileMatch
fileMatchPattern: "backstage/**/*"
---

# Backstage Development Guidelines

## Project Structure

### Key Directories
```
backstage/
├── packages/
│   ├── app/              # Frontend application
│   │   └── src/
│   │       ├── components/   # React components
│   │       └── App.tsx       # Main app component
│   └── backend/          # Backend services
│       └── src/
│           ├── plugins/      # Backend plugins
│           └── index.ts      # Backend entry point
├── plugins/              # Custom plugins
├── docs/                 # Documentation
├── examples/             # Example configurations
└── app-config.yaml       # Main configuration
```

## Configuration Management

### Configuration Files
- `app-config.yaml`: Base configuration (committed)
- `app-config.local.yaml`: Local overrides (gitignored)
- `app-config.production.yaml`: Production settings

### Environment Variables
Use environment variable substitution in config:
```yaml
backend:
  database:
    client: pg
    connection:
      host: ${POSTGRES_HOST}
      port: ${POSTGRES_PORT}
      user: ${POSTGRES_USER}
      password: ${POSTGRES_PASSWORD}
```

## Custom Plugin Development

### Kro Plugin Integration
The repository includes a custom Kro plugin for managing Kubernetes Resource Orchestrator resources:

**Backend Plugin** (`packages/backend/src/plugins/kro.ts`):
- Discovers ResourceGraphDefinitions (RGDs) from the cluster
- Manages ResourceGroup instances
- Integrates with Backstage catalog
- Implements RBAC for resource access

**Frontend Components** (`packages/app/src/components/`):
- ResourceGroup listing and filtering
- ResourceGroup detail views
- Create forms for new instances
- Status monitoring

### Plugin Development Workflow
1. Create plugin structure in `plugins/` or `packages/backend/src/plugins/`
2. Implement plugin interface
3. Register plugin in backend (`packages/backend/src/index.ts`)
4. Add frontend components in `packages/app/src/components/`
5. Register routes in `packages/app/src/App.tsx`
6. Add tests in `__tests__/` directories

## Software Templates

### Template Location
- Platform templates: `platform/backstage/templates/`
- Custom templates: `platform/backstage/customtemplates/`

### Template Structure
```yaml
apiVersion: scaffolder.backstage.io/v1beta3
kind: Template
metadata:
  name: template-name
  title: Human Readable Title
  description: Template description
spec:
  owner: platform-team
  type: service
  parameters:
    - title: Basic Information
      required:
        - name
        - owner
      properties:
        name:
          title: Name
          type: string
  steps:
    - id: fetch
      name: Fetch Template
      action: fetch:template
    - id: publish
      name: Publish to GitLab
      action: publish:gitlab
```

### Template Actions
Common actions used in templates:
- `fetch:template`: Fetch and render template files
- `publish:gitlab`: Publish to GitLab repository
- `catalog:register`: Register entity in catalog
- `kro:create`: Create Kro ResourceGroup instance

## Catalog Integration

### Entity Definitions
Entities are defined in `catalog-info.yaml` files:
```yaml
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: my-service
  annotations:
    backstage.io/kubernetes-id: my-service
    argocd/app-name: my-service
spec:
  type: service
  lifecycle: production
  owner: team-name
  system: platform
```

### Catalog Providers
- **Kubernetes**: Discovers resources from EKS clusters
- **GitLab**: Discovers repositories and projects
- **Kro**: Discovers ResourceGraphDefinitions

## Authentication & Authorization

### Keycloak Integration
- SSO configured via `app-config.yaml`
- Users and groups synced from Keycloak
- RBAC policies based on Keycloak roles

### Permission Framework
Implement permissions for custom plugins:
```typescript
import { createPermission } from '@backstage/plugin-permission-common';

export const kroResourceCreatePermission = createPermission({
  name: 'kro.resource.create',
  attributes: { action: 'create' },
});
```

## Development Commands

### Local Development
```bash
# Install dependencies
yarn install

# Start development server (frontend + backend)
yarn dev

# Start only backend
yarn start-backend

# Start only frontend
yarn start
```

### Testing
```bash
# Run all tests
yarn test

# Run Kro plugin tests
yarn test:kro

# Run frontend tests
yarn test --testPathPattern="KroIntegration.test.tsx"

# Run backend tests
yarn test --testPathPattern="kro.*test\.ts"

# TypeScript compilation check
yarn tsc
```

### Building
```bash
# Build for production
yarn build

# Build backend only
yarn build:backend

# Build Docker image
docker build -t backstage:latest .
```

## Kro Plugin Specifics

### ResourceGraphDefinition Discovery
The plugin automatically discovers RGDs from:
1. Kubernetes cluster (via kubeconfig)
2. Git repository (from `gitops/addons/charts/kro/resource-groups/`)

### Creating ResourceGroups
Users can create ResourceGroup instances through:
1. Backstage UI (Kro plugin pages)
2. Software templates (using `kro:create` action)
3. Direct kubectl apply

### Catalog Integration
- RGDs are registered as Backstage entities
- ResourceGroups link to their RGD definitions
- Status updates reflected in catalog

## Testing Strategy

### Unit Tests
- Test individual functions and components
- Mock external dependencies (Kubernetes API, GitLab API)
- Located in `__tests__/` directories

### Integration Tests
- Test plugin initialization and configuration
- Test catalog integration
- Test permission validation
- Run with `task test-backstage-kro`

### Frontend Tests
- Test React component rendering
- Test user interactions
- Test API integration
- Use React Testing Library

### Backend Tests
- Test API endpoints
- Test Kubernetes client integration
- Test catalog provider functionality
- Mock Kubernetes API responses

## Common Development Tasks

### Adding a New Software Template
1. Create template YAML in `platform/backstage/templates/`
2. Define parameters and steps
3. Test locally by registering in Backstage
4. Commit and push to Git
5. Backstage auto-discovers and loads template

### Updating Kro Plugin
1. Modify plugin code in `packages/backend/src/plugins/kro.ts`
2. Update frontend components if needed
3. Add/update tests
4. Run `yarn test:kro` to validate
5. Run `yarn tsc` to check compilation
6. Test locally with `yarn dev`

### Customizing UI Theme
1. Edit `packages/app/src/theme.ts`
2. Update colors, fonts, and spacing
3. Test in development mode
4. Build and deploy

### Adding External Integrations
1. Install required packages: `yarn add <package>`
2. Configure in `app-config.yaml`
3. Implement integration in backend plugin
4. Add frontend components if needed
5. Update documentation

## Troubleshooting

### Common Issues

**Plugin not loading:**
- Check plugin registration in `packages/backend/src/index.ts`
- Verify plugin dependencies are installed
- Check backend logs for errors

**Catalog entities not appearing:**
- Verify catalog provider configuration
- Check entity processor registration
- Review catalog logs for processing errors

**Authentication failures:**
- Verify Keycloak configuration in `app-config.yaml`
- Check Keycloak realm and client settings
- Ensure redirect URIs are configured correctly

**Kro plugin issues:**
- Verify kubeconfig is accessible
- Check Kro CRDs are installed in cluster
- Review plugin logs for API errors

## Best Practices

### Code Organization
- Keep plugins modular and focused
- Separate business logic from UI components
- Use TypeScript for type safety
- Follow Backstage plugin conventions

### Configuration
- Use environment variables for sensitive data
- Keep production config separate from development
- Document all configuration options
- Use schema validation for config

### Testing
- Write tests for all new features
- Maintain high test coverage
- Use integration tests for critical paths
- Mock external dependencies appropriately

### Documentation
- Document all custom plugins
- Provide examples for software templates
- Keep README files up to date
- Document API endpoints and schemas
