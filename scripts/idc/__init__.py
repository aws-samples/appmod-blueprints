"""IDC ↔ Keycloak configuration package.

Split by concern from the former single-file ``configure_identity_center.py``:

* ``resilience``  — centralized tenacity retry policies + transient-error
  classification (import-light: tenacity + stdlib only, unit-testable).
* ``constants``   — shared temp-file paths / realm name.
* ``credentials`` — AWS credential load/refresh + console sign-in URL.
* ``keycloak``    — Keycloak admin API + SAML client creation.
* ``scim``        — SCIM user/group export + federation verification.
* ``browser``     — Playwright/Chromium console-navigation helpers.
* ``orchestrator``— the end-to-end ``configure_identity_center`` flow.

This module intentionally performs no eager imports of the heavier submodules
(``browser``/``orchestrator`` bootstrap Playwright at import time), so that
``import idc.resilience`` in unit tests stays free of boto3/playwright.
"""
