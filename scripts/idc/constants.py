"""Shared file-path constants for the IDC configuration package.

These temp-file locations are used across several modules (credentials refresh,
browser automation, SCIM export) and the CLI entrypoint, so they live in one
place instead of being duplicated per module.
"""

STORAGE_STATE_FILE = "/tmp/aws_console_state.json"
AWS_METADATA_FILE = "/tmp/aws-id.xml"
KEYCLOAK_SAML_FILE = "/tmp/keycloak-saml.xml"
SCIM_DATA_FILE = "/tmp/scim-data.json"
ASSUME_ROLE_CREDENTIALS_FILE = "/tmp/keycloak-idc-integration-credentials.json"
# Written on a failure of the console automation, with or without --debug (unless the
# SCIM token dialog was open, see idc.evidence). Distinct from other scripts' error.png.
ERROR_SCREENSHOT = "/tmp/idc-error.png"

# Keycloak realm that fronts AWS IAM Identity Center federation.
KEYCLOAK_REALM = "platform"
