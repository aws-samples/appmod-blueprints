"""Decide how to (re)enable SCIM automatic provisioning from what the console shows.

Import-light (stdlib only) so the decision is unit-testable without Playwright.

The IAM Identity Center Settings page has changed layout over time:

* older: an "Automatic provisioning" section with an Enable button;
* current (2026-11): a "Provisioning" section with an Enable button and a
  "Provisioning method" field that reads "Manual" until SCIM is enabled, then "SCIM".

The previous code treated "no Enable button found" as "already enabled" and went to
Actions → Manage provisioning, which does not exist on a never-provisioned instance.
The "already enabled" path now needs positive proof on the page (method = SCIM).
"""

from __future__ import annotations

import re

# Section headings the Enable button may sit under (old and current console layout).
PROVISIONING_HEADINGS = ("Automatic provisioning", "Provisioning")

ENABLE = "enable"
REGENERATE = "regenerate"
ERROR = "error"


def enable_button_xpath() -> str:
    """XPath to the Enable button scoped to a provisioning section heading.

    The Settings page has other Enable buttons (Identity-enhanced sessions comes first
    in the DOM, #967): take the nearest container of the heading that has an Enable
    button, and only a button that comes after that heading.
    """
    # "Automatic provisioning" (old layout) is distinctive enough unrestricted, as before.
    # "Provisioning" alone may also be a tab/nav label, so it only counts inside a heading.
    heading = (
        f'normalize-space(text())="{PROVISIONING_HEADINGS[0]}"'
        f' or (normalize-space(text())="{PROVISIONING_HEADINGS[1]}"'
        " and ancestor-or-self::*[self::h1 or self::h2 or self::h3 or self::h4])"
    )
    return (
        f"xpath=//*[{heading}]"
        '/ancestor::*[.//button[normalize-space()="Enable"]][1]'
        '//button[normalize-space()="Enable"]'
        f"[preceding::*[{heading}]]"
    )


_METHOD_RE = re.compile(r"Provisioning method\s*\n\s*([^\n]+)", re.IGNORECASE)


def provisioning_method(page_text: str) -> str | None:
    """Return the "Provisioning method" value shown on the page, lower-cased, or None."""
    m = _METHOD_RE.search(page_text or "")
    return m.group(1).strip().lower() if m else None


def decide_provisioning_action(page_text: str, enable_visible: bool) -> tuple[str, str]:
    """Return (action, reason).

    * ENABLE      — a scoped Enable button is visible and the page does not say SCIM.
    * REGENERATE  — no Enable button AND the page positively shows method SCIM
                    (a genuine re-run: generate a new token via Manage provisioning).
    * ERROR       — anything else; never guess "already enabled".
    """
    method = provisioning_method(page_text)
    is_scim = method is not None and "scim" in method
    if enable_visible and not is_scim:
        return ENABLE, f"Enable button visible (provisioning method: {method or 'not shown'})"
    if not enable_visible and is_scim:
        return REGENERATE, "provisioning method is SCIM (already enabled)"
    if enable_visible and is_scim:
        return ERROR, "Enable button visible but provisioning method is SCIM: inconsistent page"
    return ERROR, (
        f"no provisioning Enable button found and provisioning method is "
        f"{method!r}, not SCIM: refusing to assume it is already enabled"
    )
