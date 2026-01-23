import { Content, Page, Header } from '@backstage/core-components';
import { HomePageSearchBar } from '@backstage/plugin-search';
import { SearchContextProvider } from '@backstage/plugin-search-react';
import { Grid, makeStyles, Typography } from '@material-ui/core';
import { useApi, configApiRef } from '@backstage/core-plugin-api';

import {
  HomePageToolkit,
  HomePageCompanyLogo,
  HomePageStarredEntities,
  TemplateBackstageLogoIcon,
} from '@backstage/plugin-home';

const logoUrl = '/backstage/img/backstage-icon-color.png';

// Get the domain URL dynamically from the current window location
const getDomainUrl = () => {
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.host}`;
  }
  return 'http://localhost:3000/backstage';
};

const domainUrl = getDomainUrl();

const useStyles = makeStyles(theme => ({
  searchBar: {
    display: 'flex',
    maxWidth: '60vw',
    backgroundColor: theme.palette.background.paper,
    boxShadow: theme.shadows[1],
    padding: '8px 0',
    borderRadius: '50px',
    margin: 'auto',
  },
}));

// const useLogoStyles = makeStyles(theme => ({
//   container: {
//     margin: theme.spacing(5, 0),
//   },
//   svg: {
//     width: 'auto',
//     height: 100,
//   },
//   path: {
//     fill: '#00568c',
//   },
//   customLogo: {
//     width: '120px',
//     height: 'auto',
//     maxWidth: '100%',
//     display: 'block',
//     margin: '0 auto',
//   },
//   subtitle: {
//     textAlign: 'center',
//     marginTop: theme.spacing(2),
//     color: '#ffffff',
//     fontWeight: 500,
//     fontSize: '3rem',
//     fontFamily: theme.typography.fontFamily,
//     letterSpacing: theme.typography.h4.letterSpacing,
//   },
// }));

export const CustomHomepage = () => {
  const classes = useStyles();
  // const { container, customLogo, subtitle } = useLogoStyles();
  const config = useApi(configApiRef);

  // Get GitLab URL from Backstage configuration using the correct path
  const getGitLabUrl = () => {
    try {
      // Try to access the GitLab integration baseUrl
      const gitlabIntegrations = config.getOptionalConfigArray('integrations.gitlab');
      if (gitlabIntegrations && gitlabIntegrations.length > 0) {
        const baseUrl = gitlabIntegrations[0].getOptionalString('baseUrl');
        if (baseUrl) {
          return baseUrl;
        }
      }
    } catch (e) {
      console.log('Could not read GitLab config:', e);
    }

    // Fallback
    return 'https://gitlab.com';
  };

  const gitUrl = getGitLabUrl();

  return (
    <SearchContextProvider>
      <Page themeId="home">
        <Header
          title={
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', height: '92px' }}>
              <HomePageCompanyLogo
                logo={<img src={logoUrl} alt="Company Logo" style={{ height: '64px', width: 'auto', marginRight: '16px' }} />}
              />
              <Typography variant="h5" style={{ color: 'white', fontWeight: 500, fontSize: '3rem' }}>
                Internal Developer Platform
              </Typography>
            </div>
          }
          pageTitleOverride="Internal Developer Platform"
        />
        <Content>
          <Grid container justifyContent="center" spacing={6}>
            <Grid container item xs={12} alignItems="center" direction="row">
              <HomePageSearchBar classes={{ root: classes.searchBar }} placeholder="Search" />
            </Grid>
            <Grid container item xs={12}>
              <Grid item xs={12} md={6}>
                <HomePageStarredEntities />
              </Grid>
              <Grid item xs={12} md={6}>
                <HomePageToolkit
                  title="Quick Links"
                  tools={[
                    {
                      url: '/catalog',
                      label: 'Catalog',
                      icon: <TemplateBackstageLogoIcon/>,
                    },
                    // {
                    //   url: '/docs',
                    //   label: 'Tech Docs',
                    //   icon: <TemplateBackstageLogoIcon />,
                    // },
                    {
                      url: gitUrl,
                      label: 'GitLab',
                      icon: <img src="/backstage/img/gitlab.png" alt="GitLab" style={{ width: '24px', height: '24px' }} />,
                    },
                    {
                      url: domainUrl + '/argocd',
                      label: 'ArgoCD',
                      icon: <img src="/backstage/img/argocd.png" alt="ArgoCD" style={{ width: '24px', height: '24px' }} />,
                    },
                    {
                      url: domainUrl + '/argo-workflows',
                      label: 'Argo Workflows',
                      icon: <img src="/backstage/img/argo-workflows.png" alt="Argo Workflows" style={{ width: '24px', height: '24px' }} />,
                    },
                    {
                      url: domainUrl + '/jupyterhub',
                      label: 'JupyterHub',
                      icon: <img src="/backstage/img/jupyter.png" alt="JupyterHub" style={{ width: '24px', height: '24px' }} />,
                    },
                    {
                      url: domainUrl,
                      label: 'Kargo',
                      icon: <img src="/backstage/img/kargo.png" alt="Kargo" style={{ width: '24px', height: '24px' }} />,
                    },
                    {
                      url: domainUrl + '/keycloak',
                      label: 'Keycloak',
                      icon: <img src="/backstage/img/keycloak.png" alt="Keycloak" style={{ width: '24px', height: '24px' }} />,
                    },
                    {
                      url: domainUrl + '/keycloak/realms/platform/protocol/openid-connect/logout',
                      label: 'Logout',
                      icon: <img src="/backstage/img/logout.png" alt="Logout" style={{ width: '24px', height: '24px' }} />,
                    },
                  ]}
                />
              </Grid>
            </Grid>
          </Grid>
        </Content>
      </Page>
    </SearchContextProvider>
  );
};
