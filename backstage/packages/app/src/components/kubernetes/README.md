# Kubernetes-Kro Integration

This directory contains components that integrate Kro ResourceGroups with the existing Backstage Kubernetes plugin, providing a unified view of both standard Kubernetes resources and Kro composite resources.

## Components

### KubernetesContentWithKro
Enhanced Kubernetes content component that:
- Detects Kro ResourceGroups and managed resources
- Shows Kro integration indicators and chips
- Displays Kro Overview Card and Resource Graph for ResourceGroups
- Integrates seamlessly with standard Kubernetes content

### KroNavigationHelper
Navigation component that:
- Shows resource relationships between ResourceGroups and managed resources
- Provides navigation buttons between Kubernetes and Kro views
- Displays related resources with proper categorization
- Handles seamless navigation between different entity views

### KroResourceFilter
Enhanced resource filter that:
- Includes Kro resource types in filtering options
- Categorizes Kro resources separately from standard resources
- Provides visual indicators for Kro resources
- Supports filtering by resource type including ResourceGroups

## Backend Integration

### kubernetes-kro-integration.ts
Backend module that:
- Enhances Kubernetes plugin with Kro resource types
- Provides resource relationship mapping
- Implements resource filtering for Kro resources
- Validates configuration and provides error handling

## Features Implemented

### ✅ ResourceGroups in Kubernetes Views
- ResourceGroups appear in existing Kubernetes plugin views
- Proper identification with Kro-specific chips and indicators
- Integration with standard Kubernetes resource listings

### ✅ Resource Relationships and Filtering
- Relationship mapping between ResourceGroups and managed resources
- Enhanced filtering that includes Kro resource types
- Visual categorization of Kro vs standard resources

### ✅ Seamless Navigation
- Navigation helpers for moving between Kubernetes and Kro views
- Context-aware navigation based on entity type
- Related resource discovery and linking

### ✅ Configuration Integration
- Backend configuration for Kro resource types
- Integration settings for showing ResourceGroups in Kubernetes views
- Error handling and validation for missing configurations

## Usage

The integration is automatically enabled when:
1. Kro plugin is installed and configured
2. Kubernetes plugin is available
3. Entities have appropriate Kro annotations or are ResourceGroups

### Entity Types Supported

1. **Kro ResourceGroups** (`spec.type: 'kro-resource-group'`)
   - Full Kro integration with overview and resource graph
   - Navigation to managed resources
   - Relationship mapping

2. **Managed Resources** (with `kro.run/resource-group` annotation)
   - "Managed by Kro" indicators
   - Navigation to parent ResourceGroup
   - Relationship context

3. **Standard Resources**
   - Normal Kubernetes plugin behavior
   - No Kro integration unless related to ResourceGroups

### Configuration

Ensure the following is configured in `app-config.yaml`:

```yaml
kubernetes:
  customResources:
    - group: 'kro.run'
      apiVersion: 'v1alpha1'
      plural: 'resourcegraphdefinitions'
    # ... other Kro resource types

kro:
  integration:
    showInKubernetesViews: true
    enableRelationshipMapping: true
```

## Testing

Run the integration tests:
```bash
yarn workspace app test --testNamePattern="KubernetesContentWithKro"
```

See `integration-test.md` for manual testing procedures.

## Requirements Satisfied

This implementation satisfies the following requirements from the specification:

- **6.1**: ResourceGroups appear in existing Kubernetes plugin views ✅
- **6.2**: Resource relationships and filtering for ResourceGroups ✅  
- **6.3**: Seamless navigation between Kubernetes and Kro views ✅
- **6.4**: Integration with existing Kubernetes plugin functionality ✅

## Architecture

```
Frontend:
├── KubernetesContentWithKro (Enhanced Kubernetes content)
├── KroNavigationHelper (Navigation between views)
└── KroResourceFilter (Enhanced filtering)

Backend:
├── kubernetes-kro-integration (Resource discovery)
├── KroResourceRelationshipMapper (Relationship mapping)
└── KroResourceFilter (Backend filtering)

Integration Points:
├── EntityPage.tsx (Updated to use enhanced components)
├── app-config.yaml (Configuration)
└── Backend index.ts (Module registration)
```