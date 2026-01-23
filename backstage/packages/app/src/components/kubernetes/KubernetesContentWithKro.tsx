import { Grid, Typography, Card, CardContent, Chip } from '@material-ui/core';
import { EntityKubernetesContent } from '@backstage/plugin-kubernetes';
import { useEntity } from '@backstage/plugin-catalog-react';
import { Entity } from '@backstage/catalog-model';
import {
  IfKroResourceGraphAvailable,
  KroResourceGraph,
  KroOverviewCard,
  IfKroOverviewAvailable,
} from '@terasky/backstage-plugin-kro-resources-frontend';

/**
 * Enhanced Kubernetes content that integrates Kro ResourceGroups
 * with standard Kubernetes resources for a unified view
 */
export const KubernetesContentWithKro = () => {
  const { entity } = useEntity();

  // Check if this entity is a Kro ResourceGroup
  const isKroResourceGroup = entity.spec?.type === 'kro-resource-group';

  // Check if this entity has Kro annotations (managed by a ResourceGroup)
  const hasKroAnnotations = Boolean(
    entity.metadata.annotations?.['kro.run/resource-group'] ||
    entity.metadata.annotations?.['kro.run/managed-by']
  );

  return (
    <Grid container spacing={3}>
      {/* Show Kro information if this is a ResourceGroup or managed by one */}
      {(isKroResourceGroup || hasKroAnnotations) && (
        <>
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  Kro Integration
                </Typography>
                <Grid container spacing={2} alignItems="center">
                  {isKroResourceGroup && (
                    <Grid item>
                      <Chip
                        label="Kro ResourceGroup"
                        color="primary"
                        variant="outlined"
                        size="small"
                      />
                    </Grid>
                  )}
                  {hasKroAnnotations && !isKroResourceGroup && (
                    <Grid item>
                      <Chip
                        label="Managed by Kro"
                        color="secondary"
                        variant="outlined"
                        size="small"
                      />
                    </Grid>
                  )}
                  {entity.metadata.annotations?.['kro.run/resource-group'] && (
                    <Grid item>
                      <Typography variant="body2" color="textSecondary">
                        ResourceGroup: {entity.metadata.annotations['kro.run/resource-group']}
                      </Typography>
                    </Grid>
                  )}
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          {/* Kro Overview Card for ResourceGroups */}
          {isKroResourceGroup && (
            <Grid item xs={12}>
              <IfKroOverviewAvailable>
                <KroOverviewCard />
              </IfKroOverviewAvailable>
            </Grid>
          )}

          {/* Kro Resource Graph for ResourceGroups */}
          {isKroResourceGroup && (
            <Grid item xs={12}>
              <IfKroResourceGraphAvailable>
                <KroResourceGraph />
              </IfKroResourceGraphAvailable>
            </Grid>
          )}
        </>
      )}

      {/* Standard Kubernetes Content */}
      <Grid item xs={12}>
        <EntityKubernetesContent />
      </Grid>
    </Grid>
  );
};

/**
 * Helper function to determine if an entity should show Kro integration
 */
export const hasKroIntegration = (entity: Entity): boolean => {
  return (
    entity.spec?.type === 'kro-resource-group' ||
    Boolean(
      entity.metadata.annotations?.['kro.run/resource-group'] ||
      entity.metadata.annotations?.['kro.run/managed-by']
    )
  );
};