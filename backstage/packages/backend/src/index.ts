import { createBackend } from '@backstage/backend-defaults';
import { authModuleKeycloakOIDCProvider } from './plugins/auth';
import { kroBackendModule } from './plugins/kro';
import { catalogKroModule } from './plugins/catalog-kro-module';
import { kubernetesIngestorKroModule } from './plugins/kubernetes-ingestor-kro-module';
import { kroSecurityModule } from './plugins/kro-security';
import { kroPermissionsModule } from './plugins/kro-permissions';
import { kroAuditModule } from './plugins/kro-audit';

const backend = createBackend();

backend.add(import('@backstage/plugin-app-backend'));
backend.add(import('@backstage/plugin-proxy-backend'));
backend.add(import('@backstage/plugin-scaffolder-backend'));
backend.add(import('@backstage/plugin-scaffolder-backend-module-github'));
backend.add(import('@internal/plugin-scaffolder-backend-module-gitlab'));
backend.add(import('@devangelista/backstage-scaffolder-kubernetes'));
backend.add(import('@backstage/plugin-techdocs-backend'));

// roadiehq plugins
backend.add(import('@roadiehq/scaffolder-backend-module-utils'));
backend.add(import('@roadiehq/scaffolder-backend-module-http-request'));
backend.add(import('@roadiehq/scaffolder-backend-argocd'));

// auth plugin
backend.add(import('@backstage/plugin-auth-backend'));
// See https://backstage.io/docs/backend-system/building-backends/migrating#the-auth-plugin
backend.add(import('@backstage/plugin-auth-backend-module-guest-provider'));
// See https://backstage.io/docs/auth/guest/provider

// catalog plugin
backend.add(import('@backstage/plugin-catalog-backend'));
backend.add(
  import('@backstage/plugin-catalog-backend-module-scaffolder-entity-model'),
);

// See https://backstage.io/docs/features/software-catalog/configuration#subscribing-to-catalog-errors
backend.add(import('@backstage/plugin-catalog-backend-module-logs'));

// permission plugin
backend.add(import('@backstage/plugin-permission-backend'));
// See https://backstage.io/docs/permissions/getting-started for how to create your own permission policy
backend.add(
  import('@backstage/plugin-permission-backend-module-allow-all-policy'),
);

// search plugin
backend.add(import('@backstage/plugin-search-backend'));

// search engine
// See https://backstage.io/docs/features/search/search-engines
backend.add(import('@backstage/plugin-search-backend-module-pg'));

// search collators
backend.add(import('@backstage/plugin-search-backend-module-catalog'));
backend.add(import('@backstage/plugin-search-backend-module-techdocs'));

// kubernetes
backend.add(import('@backstage/plugin-kubernetes-backend'));

// kubernetes ingestor plugin
backend.add(import('@terasky/backstage-plugin-kubernetes-ingestor'));

// kro plugin
backend.add(import('@terasky/backstage-plugin-kro-resources-backend'));

// Internal Developer Platform custom plugins
backend.add(authModuleKeycloakOIDCProvider);

// Enhanced Kro plugin configuration with error handling
backend.add(kroBackendModule);

// Kro catalog integration module
backend.add(catalogKroModule);

// Kubernetes Ingestor Kro integration module
backend.add(kubernetesIngestorKroModule);

// Kro security and permissions modules
backend.add(kroSecurityModule);
backend.add(kroPermissionsModule);
backend.add(kroAuditModule);

// Kubernetes Kro integration module
backend.add(import('./plugins/kubernetes-kro-integration').then(m => m.kubernetesKroIntegrationModule));

backend.start();
