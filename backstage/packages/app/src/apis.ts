import {
  ScmIntegrationsApi,
  scmIntegrationsApiRef,
  ScmAuth,
} from '@backstage/integration-react';
import {
  AnyApiFactory, ApiRef, BackstageIdentityApi,
  configApiRef,
  createApiFactory, createApiRef, discoveryApiRef, oauthRequestApiRef, OpenIdConnectApi, ProfileInfoApi, SessionApi,
} from '@backstage/core-plugin-api';
import {OAuth2} from "@backstage/core-app-api";

export const keycloakOIDCAuthApiRef: ApiRef<
  OpenIdConnectApi & ProfileInfoApi & BackstageIdentityApi & SessionApi
> = createApiRef({
  id: 'auth.keycloak-oidc',
});
export const apis: AnyApiFactory[] = [
  createApiFactory({
    api: scmIntegrationsApiRef,
    deps: {configApi: configApiRef},
    factory: ({configApi}) => ScmIntegrationsApi.fromConfig(configApi),
  }),
  ScmAuth.createDefaultApiFactory(),
  createApiFactory({
    api: keycloakOIDCAuthApiRef,
    deps: {
      discoveryApi: discoveryApiRef,
      oauthRequestApi: oauthRequestApiRef,
      configApi: configApiRef,
    },
    factory: ({ discoveryApi, oauthRequestApi, configApi }) =>
      OAuth2.create({
        discoveryApi,
        oauthRequestApi,
        provider: {
          id: 'keycloak-oidc',
          title: 'Keycloak OIDC',
          icon: () => null,
        },
        environment: configApi.getOptionalString('auth.environment'),
        defaultScopes: ['openid', 'profile', 'email', 'groups'],
      }),
  }),
];
