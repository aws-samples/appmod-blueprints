import React from 'react';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  Box,
  Typography
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';

const useStyles = makeStyles((theme) => ({
  formControl: {
    margin: theme.spacing(1),
    minWidth: 200,
  },
  chips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: theme.spacing(0.5),
  },
  chip: {
    margin: theme.spacing(0.25),
  },
  kroChip: {
    backgroundColor: theme.palette.primary.light,
    color: theme.palette.primary.contrastText,
  },
}));

interface KroResourceFilterProps {
  selectedResourceTypes: string[];
  onResourceTypeChange: (resourceTypes: string[]) => void;
  availableResourceTypes: string[];
}

/**
 * Enhanced resource filter that includes Kro ResourceGroups
 * alongside standard Kubernetes resources
 */
export const KroResourceFilter: React.FC<KroResourceFilterProps> = ({
  selectedResourceTypes,
  onResourceTypeChange,
  availableResourceTypes,
}) => {
  const classes = useStyles();

  // Categorize resource types
  const kroResourceTypes = availableResourceTypes.filter(type =>
    type.includes('kro.run') || type.includes('ResourceGroup')
  );

  const standardResourceTypes = availableResourceTypes.filter(type =>
    !type.includes('kro.run') && !type.includes('ResourceGroup')
  );

  const handleChange = (event: React.ChangeEvent<{ value: unknown }>) => {
    const value = event.target.value as string[];
    onResourceTypeChange(value);
  };

  const handleChipDelete = (resourceType: string) => {
    onResourceTypeChange(selectedResourceTypes.filter(type => type !== resourceType));
  };

  const isKroResource = (resourceType: string): boolean => {
    return resourceType.includes('kro.run') || resourceType.includes('ResourceGroup');
  };

  return (
    <Box>
      <FormControl className={classes.formControl}>
        <InputLabel id="resource-type-select-label">Resource Types</InputLabel>
        <Select
          labelId="resource-type-select-label"
          id="resource-type-select"
          multiple
          value={selectedResourceTypes}
          onChange={handleChange}
          renderValue={(selected) => (
            <Box className={classes.chips}>
              {(selected as string[]).map((value) => (
                <Chip
                  key={value}
                  label={value}
                  onDelete={() => handleChipDelete(value)}
                  className={`${classes.chip} ${isKroResource(value) ? classes.kroChip : ''}`}
                  size="small"
                />
              ))}
            </Box>
          )}
        >
          {/* Kro Resources Section */}
          {kroResourceTypes.length > 0 && (
            <>
              <MenuItem disabled>
                <Typography variant="subtitle2" color="primary">
                  Kro Resources
                </Typography>
              </MenuItem>
              {kroResourceTypes.map((resourceType) => (
                <MenuItem key={resourceType} value={resourceType}>
                  <Box display="flex" alignItems="center">
                    <Chip
                      label="Kro"
                      size="small"
                      color="primary"
                      variant="outlined"
                      style={{ marginRight: 8, fontSize: '0.7rem' }}
                    />
                    {resourceType}
                  </Box>
                </MenuItem>
              ))}
            </>
          )}

          {/* Standard Kubernetes Resources Section */}
          {standardResourceTypes.length > 0 && kroResourceTypes.length > 0 && (
            <MenuItem disabled>
              <Typography variant="subtitle2">
                Standard Resources
              </Typography>
            </MenuItem>
          )}
          {standardResourceTypes.map((resourceType) => (
            <MenuItem key={resourceType} value={resourceType}>
              {resourceType}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
};

/**
 * Default resource types that should be included for Kro integration
 */
export const DEFAULT_KRO_RESOURCE_TYPES = [
  'kro.run/v1alpha1/ResourceGraphDefinition',
  'kro.run/v1alpha1/CICDPipeline',
  'kro.run/v1alpha1/EksCluster',
  'kro.run/v1alpha1/EksclusterWithVpc',
  'kro.run/v1alpha1/Vpc',
];

/**
 * Helper function to get all available resource types including Kro resources
 */
export const getAllResourceTypesWithKro = (standardTypes: string[]): string[] => {
  return [...DEFAULT_KRO_RESOURCE_TYPES, ...standardTypes];
};