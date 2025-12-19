import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Button,
  Grid,
  Box,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemIcon
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';
import {
  Launch as LaunchIcon,
  AccountTree as ResourceGroupIcon,
  Storage as ResourceIcon,
  Link as LinkIcon
} from '@material-ui/icons';
import { useEntity } from '@backstage/plugin-catalog-react';
import { useRouteRef } from '@backstage/core-plugin-api';
import { entityRouteRef } from '@backstage/plugin-catalog-react';
import { Entity } from '@backstage/catalog-model';

const useStyles = makeStyles((theme) => ({
  card: {
    marginBottom: theme.spacing(2),
  },
  navigationButton: {
    margin: theme.spacing(0.5),
  },
  relationshipChip: {
    margin: theme.spacing(0.25),
  },
  kroChip: {
    backgroundColor: theme.palette.primary.light,
    color: theme.palette.primary.contrastText,
  },
  relatedResourcesList: {
    maxHeight: 200,
    overflow: 'auto',
  },
}));

interface RelatedResource {
  name: string;
  kind: string;
  namespace?: string;
  entityRef?: string;
  isKroResource: boolean;
}

/**
 * Navigation helper component that provides seamless navigation
 * between Kubernetes and Kro views
 */
export const KroNavigationHelper: React.FC = () => {
  const classes = useStyles();
  const { entity } = useEntity();
  const catalogEntityRoute = useRouteRef(entityRouteRef);

  // Extract related resources from entity annotations and relations
  const getRelatedResources = (): RelatedResource[] => {
    const resources: RelatedResource[] = [];

    // Get ResourceGroup relationships
    const resourceGroupRef = entity.metadata.annotations?.['kro.run/resource-group'];
    if (resourceGroupRef) {
      resources.push({
        name: resourceGroupRef,
        kind: 'ResourceGroup',
        entityRef: resourceGroupRef,
        isKroResource: true,
      });
    }

    // Get managed resources from Kro annotations
    const managedResources = entity.metadata.annotations?.['kro.run/managed-resources'];
    if (managedResources) {
      try {
        const parsed = JSON.parse(managedResources);
        if (Array.isArray(parsed)) {
          parsed.forEach((resource: any) => {
            resources.push({
              name: resource.name || 'Unknown',
              kind: resource.kind || 'Unknown',
              namespace: resource.namespace,
              isKroResource: false,
            });
          });
        }
      } catch (error) {
        console.warn('Failed to parse managed resources annotation:', error);
      }
    }

    // Get related entities from catalog relations
    if (entity.relations) {
      entity.relations.forEach(relation => {
        if (relation.type === 'dependsOn' || relation.type === 'partOf') {
          const targetRef = relation.targetRef;
          const isKroResource = targetRef.includes('kro-resource-group');

          resources.push({
            name: targetRef.split('/').pop() || targetRef,
            kind: targetRef.split('/')[0] || 'Component',
            entityRef: targetRef,
            isKroResource,
          });
        }
      });
    }

    return resources;
  };

  const relatedResources = getRelatedResources();
  const isKroResourceGroup = entity.spec?.type === 'kro-resource-group';
  const hasManagedResources = relatedResources.some(r => !r.isKroResource);
  const hasKroRelations = relatedResources.some(r => r.isKroResource);

  const navigateToEntity = (entityRef: string) => {
    const [kind, namespace, name] = entityRef.split('/');
    return catalogEntityRoute({
      kind: kind.toLowerCase(),
      namespace: namespace || 'default',
      name,
    });
  };

  if (relatedResources.length === 0 && !isKroResourceGroup) {
    return null;
  }

  return (
    <Card className={classes.card}>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Resource Relationships
        </Typography>

        {/* Entity Type Indicators */}
        <Box mb={2}>
          <Grid container spacing={1} alignItems="center">
            {isKroResourceGroup && (
              <Grid item>
                <Chip
                  icon={<ResourceGroupIcon />}
                  label="Kro ResourceGroup"
                  className={classes.kroChip}
                  size="small"
                />
              </Grid>
            )}
            {hasManagedResources && (
              <Grid item>
                <Chip
                  icon={<ResourceIcon />}
                  label={`Manages ${relatedResources.filter(r => !r.isKroResource).length} Resources`}
                  color="secondary"
                  variant="outlined"
                  size="small"
                />
              </Grid>
            )}
            {hasKroRelations && !isKroResourceGroup && (
              <Grid item>
                <Chip
                  icon={<LinkIcon />}
                  label="Kro Managed"
                  className={classes.kroChip}
                  variant="outlined"
                  size="small"
                />
              </Grid>
            )}
          </Grid>
        </Box>

        {/* Related Resources List */}
        {relatedResources.length > 0 && (
          <Box>
            <Typography variant="subtitle2" gutterBottom>
              Related Resources
            </Typography>
            <List dense className={classes.relatedResourcesList}>
              {relatedResources.map((resource, index) => (
                <ListItem key={index} divider>
                  <ListItemIcon>
                    {resource.isKroResource ? <ResourceGroupIcon color="primary" /> : <ResourceIcon />}
                  </ListItemIcon>
                  <ListItemText
                    primary={
                      <Box display="flex" alignItems="center" style={{ gap: 8 }}>
                        <Typography variant="body2">
                          {resource.name}
                        </Typography>
                        <Chip
                          label={resource.kind}
                          size="small"
                          variant="outlined"
                          className={resource.isKroResource ? classes.kroChip : ''}
                        />
                        {resource.namespace && (
                          <Chip
                            label={resource.namespace}
                            size="small"
                            variant="outlined"
                            color="default"
                          />
                        )}
                      </Box>
                    }
                    secondary={resource.isKroResource ? 'Kro ResourceGroup' : 'Kubernetes Resource'}
                  />
                  {resource.entityRef && (
                    <Button
                      size="small"
                      startIcon={<LaunchIcon />}
                      onClick={() => window.open(navigateToEntity(resource.entityRef!), '_blank')}
                      className={classes.navigationButton}
                    >
                      View
                    </Button>
                  )}
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        {/* Navigation Actions */}
        <Box mt={2}>
          <Grid container spacing={1}>
            {isKroResourceGroup && (
              <>
                <Grid item>
                  <Button
                    variant="outlined"
                    color="primary"
                    size="small"
                    startIcon={<ResourceGroupIcon />}
                    className={classes.navigationButton}
                    onClick={() => {
                      // Navigate to Kro details tab
                      const currentUrl = window.location.href;
                      const baseUrl = currentUrl.split('/kubernetes')[0];
                      window.location.href = `${baseUrl}/kro`;
                    }}
                  >
                    View Kro Details
                  </Button>
                </Grid>
                <Grid item>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={<ResourceIcon />}
                    className={classes.navigationButton}
                    onClick={() => {
                      // Stay on current Kubernetes tab but scroll to managed resources
                      const managedResourcesSection = document.querySelector('[data-testid="managed-resources"]');
                      if (managedResourcesSection) {
                        managedResourcesSection.scrollIntoView({ behavior: 'smooth' });
                      }
                    }}
                  >
                    View Managed Resources
                  </Button>
                </Grid>
              </>
            )}
            {hasKroRelations && !isKroResourceGroup && (
              <Grid item>
                <Button
                  variant="outlined"
                  color="primary"
                  size="small"
                  startIcon={<ResourceGroupIcon />}
                  className={classes.navigationButton}
                  onClick={() => {
                    const resourceGroupResource = relatedResources.find(r => r.isKroResource);
                    if (resourceGroupResource?.entityRef) {
                      window.open(navigateToEntity(resourceGroupResource.entityRef), '_blank');
                    }
                  }}
                >
                  View ResourceGroup
                </Button>
              </Grid>
            )}
          </Grid>
        </Box>
      </CardContent>
    </Card>
  );
};

/**
 * Helper function to determine if navigation helper should be shown
 */
export const shouldShowKroNavigation = (entity: Entity): boolean => {
  return (
    entity.spec?.type === 'kro-resource-group' ||
    Boolean(entity.metadata.annotations?.['kro.run/resource-group']) ||
    Boolean(entity.metadata.annotations?.['kro.run/managed-resources']) ||
    Boolean(entity.relations?.some(r =>
      (r.type === 'dependsOn' || r.type === 'partOf') &&
      r.targetRef.includes('kro-resource-group')
    ))
  );
};