import {
  createUnifiedTheme,
  genPageTheme,
  palettes,
  shapes
} from '@backstage/theme';

export const customTheme = createUnifiedTheme({
  palette: {
    ...palettes.light,
    primary: {
      main: '#35abe2',
    },
    secondary: {
      main: '#565a6e',
    },
    error: {
      main: '#8c4351',
    },
    warning: {
      main: '#8f5e15',
    },
    info: {
      main: '#35abe2',
    },
    success: {
      main: '#35abe2',
    },
    background: {
      default: '#ffffff',
      paper: '#f4f4f4',
    },
    banner: {
      info: '#35abe2',
      error: '#8c4351',
      text: '#343b58',
      link: '#565a6e',
    },
    errorBackground: '#8c4351',
    warningBackground: '#8f5e15',
    infoBackground: '#343b58',
    navigation: {
      submenu: {
        background: '#35abe2'
      },
      background: '#f4f4f4',
      indicator: '#9d599f',
      selectedColor: '#9d599f',
      color: '#0d456b',
      navItem: {
        hoverBackground: '#35abe2',
      },
    },
  },
  pageTheme: {
    home: genPageTheme({ colors: ['#0d456b', '#9d599f'], shape: shapes.wave }),
    documentation: genPageTheme({
      colors: ['#0d456b', '#9d599f'],
      shape: shapes.wave,
    }),
    project: genPageTheme({
      colors: ['#0d456b', '#0d456b'],
      shape: shapes.wave,
    }),
    tool: genPageTheme({
      colors: ['#9d599f', '#9d599f'],
      shape: shapes.round }),
    library: genPageTheme({
      colors: ['#9d599f', '#9d599f'],
      shape: shapes.round,
    }),
    technique: genPageTheme({ colors: ['#9d599f', '#9d599f'], shape: shapes.round }),
    other: genPageTheme({ colors: ['#0d456b', '#9d599f'], shape: shapes.wave }),
    apis: genPageTheme({ colors: ['#0d456b', '#9d599f'], shape: shapes.wave }),
  },
  components: {
    BackstageInfoCard: {
      styleOverrides: {
      }
    },
    BackstageSidebarItem: {
      styleOverrides: {
        root: {
          textDecorationLine: 'none'
        }
      }
    },
    MuiButton: {
      styleOverrides: {
        containedPrimary: {
          '&:hover': {
            backgroundColor: '#35abe2',
          },
          color: '#FFFFFF',
        },
        containedSecondary: {
          '&:hover': {
            backgroundColor: '#35abe2',
          },
          color: '#FFFFFF',
        },
      },
    },
  }
});