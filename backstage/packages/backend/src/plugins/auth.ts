import {
  DEFAULT_NAMESPACE,
  stringifyEntityRef,
} from '@backstage/catalog-model';
import { JsonArray } from '@backstage/types';
import { createBackendModule } from '@backstage/backend-plugin-api';
import {
  authProvidersExtensionPoint,
  createOAuthProviderFactory,
  OAuthAuthenticatorResult,
} from '@backstage/plugin-auth-node';
import {
  oidcAuthenticator,
  OidcAuthResult,
} from '@backstage/plugin-auth-backend-module-oidc-provider';

export const authModuleKeycloakOIDCProvider = createBackendModule({
  pluginId: 'auth',
  moduleId: 'keycloak-oidc',
  register(reg) {
    reg.registerInit({
      deps: {
        providers: authProvidersExtensionPoint,
      },
      async init({ providers }) {
        providers.registerProvider({
          providerId: 'keycloak-oidc',
          factory: createOAuthProviderFactory({
            authenticator: oidcAuthenticator,
            profileTransform: async (
              input: OAuthAuthenticatorResult<OidcAuthResult>,
            ) => ({
              profile: {
                email: input.fullProfile.userinfo.email,
                picture: input.fullProfile.userinfo.picture,
                displayName: input.fullProfile.userinfo.name,
              },
            }),
            async signInResolver(info, ctx) {
              const { profile } = info;
              if (!profile.displayName) {
                throw new Error(
                  'Login failed, user profile does not contain a valid name',
                );
              }
              // should use users from catalog
              const userRef = stringifyEntityRef({
                kind: 'User',
                name: info.profile.displayName!,
                namespace: DEFAULT_NAMESPACE,
              });

              return ctx.issueToken({
                claims: {
                  sub: userRef,
                  ent: [userRef],
                  groups:
                    (info.result.fullProfile.userinfo.groups as JsonArray) ||
                    [],
                },
              });
            },
          }),
        });
      },
    });
  },
});
