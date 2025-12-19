# Kubernetes-Kro Integration Test Plan

## Test Scenarios

### 1. ResourceGroup Entity Display
**Test**: Navigate to a Kro ResourceGroup entity
**Expected**: 
- Kubernetes tab shows Kro integration section
- ResourceGroup chip is displayed
- Kro Overview Card is visible
- Kro Resource Graph is visible
- Navigation helper shows "View Kro Details" and "View Managed Resources" buttons

### 2. Managed Resource Display
**Test**: Navigate to a resource managed by a ResourceGroup
**Expected**:
- Kubernetes tab shows Kro integration section
- "Managed by Kro" chip is displayed
- ResourceGroup reference is shown
- Navigation helper shows "View ResourceGroup" button

### 3. Standard Resource Display
**Test**: Navigate to a standard Kubernetes resource (not Kro-related)
**Expected**:
- Standard Kubernetes content is displayed
- No Kro integration section is shown
- No navigation helper is displayed

### 4. Resource Filtering
**Test**: Use resource type filters in Kubernetes views
**Expected**:
- Kro resource types appear in filter dropdown
- Kro resources are marked with "Kro" chips
- Filtering works correctly for both Kro and standard resources

### 5. Navigation Between Views
**Test**: Navigate between Kubernetes and Kro tabs
**Expected**:
- Seamless navigation between tabs
- Context is preserved
- Related resources are properly linked

## Manual Testing Steps

1. **Setup Test Data**:
   - Ensure Kro ResourceGroups are deployed in the cluster
   - Verify ResourceGroups are ingested into Backstage catalog
   - Check that managed resources have proper annotations

2. **Test ResourceGroup View**:
   ```bash
   # Navigate to: /catalog/default/component/{resource-group-name}/kubernetes
   # Verify Kro integration components are displayed
   ```

3. **Test Managed Resource View**:
   ```bash
   # Navigate to: /catalog/default/component/{managed-resource-name}/kubernetes
   # Verify "Managed by Kro" indicators are shown
   ```

4. **Test Navigation**:
   - Click "View Kro Details" button
   - Click "View ResourceGroup" button
   - Verify URLs and content load correctly

5. **Test Filtering**:
   - Open resource type filter dropdown
   - Verify Kro resources are listed with proper labels
   - Test filtering functionality

## Verification Checklist

- [ ] Kro ResourceGroups appear in Kubernetes plugin views
- [ ] Resource relationships are properly displayed
- [ ] Filtering includes ResourceGroups with proper categorization
- [ ] Navigation between Kubernetes and Kro views is seamless
- [ ] Error handling works for missing or invalid ResourceGroups
- [ ] Performance is acceptable with large numbers of resources

## Configuration Verification

Ensure the following configuration is present in `app-config.yaml`:

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

## Expected Behavior Summary

The integration should provide:
1. **Unified View**: ResourceGroups appear alongside standard Kubernetes resources
2. **Clear Identification**: Kro resources are clearly marked and distinguishable
3. **Relationship Mapping**: Connections between ResourceGroups and managed resources are visible
4. **Seamless Navigation**: Easy movement between different views and related resources
5. **Proper Filtering**: Resource type filters include and properly categorize Kro resources