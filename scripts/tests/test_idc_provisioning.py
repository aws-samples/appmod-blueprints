"""Unit tests for ``idc.provisioning``: when to click Enable, when a re-run may take the
"already enabled" path, and when to fail instead of guessing. Stdlib only, no browser.

Page texts mirror the IAM Identity Center Settings page (body innerText).
"""

import pytest

from idc.provisioning import (
    ENABLE,
    ERROR,
    REGENERATE,
    decide_provisioning_action,
    enable_button_xpath,
    provisioning_method,
)

# Current console (2026-11): "Provisioning" section, method Manual, Enable button.
NEW_LAYOUT_MANUAL = (
    "AWS access portal URLs\nDual-stack\n...\nProvisioning\nEnable\n"
    "Automatic provisioning relies on the protocol System for Cross-domain Identity "
    "Management (SCIM) to provision users from your identity provider (IdP).\n"
    "Provisioning method\nManual\nSign-in\nManage authentication\n"
)
NEW_LAYOUT_SCIM = NEW_LAYOUT_MANUAL.replace("Provisioning method\nManual", "Provisioning method\nSCIM")
# Older console: "Automatic provisioning" heading, no method field.
OLD_LAYOUT = "Automatic provisioning\nEnable\nSCIM endpoint and token...\n"


def test_method_parsed():
    assert provisioning_method(NEW_LAYOUT_MANUAL) == "manual"
    assert provisioning_method(NEW_LAYOUT_SCIM) == "scim"
    assert provisioning_method(OLD_LAYOUT) is None
    assert provisioning_method("") is None


def test_enable_when_button_visible_and_manual():
    assert decide_provisioning_action(NEW_LAYOUT_MANUAL, True)[0] == ENABLE


def test_enable_on_old_layout_without_method_field():
    assert decide_provisioning_action(OLD_LAYOUT, True)[0] == ENABLE


def test_regenerate_only_with_positive_proof():
    assert decide_provisioning_action(NEW_LAYOUT_SCIM, False)[0] == REGENERATE


@pytest.mark.parametrize("text", [NEW_LAYOUT_MANUAL, OLD_LAYOUT, "", "Settings\nIdentity source\n"])
def test_no_button_without_scim_is_an_error_not_already_enabled(text):
    # Regression: a fresh instance (method Manual) whose Enable button the locator
    # missed must NOT be treated as "already enabled".
    action, reason = decide_provisioning_action(text, False)
    assert action == ERROR
    assert "refusing to assume" in reason


def test_inconsistent_page_is_an_error():
    assert decide_provisioning_action(NEW_LAYOUT_SCIM, True)[0] == ERROR


def test_xpath_scopes_enable_to_both_headings():
    xp = enable_button_xpath()
    assert xp.startswith("xpath=")
    assert 'normalize-space(text())="Provisioning"' in xp
    assert 'normalize-space(text())="Automatic provisioning"' in xp
    assert "self::h2" in xp
    assert xp.count('button[normalize-space()="Enable"]') == 2


def test_xpath_matches_current_console_dom():
    """Run the XPath against a DOM shaped like the current Settings page (needs lxml)."""
    etree = pytest.importorskip("lxml.etree")
    dom = etree.fromstring(
        "<body>"
        "<nav><a>Provisioning</a></nav>"
        "<div><h2>Identity-enhanced sessions</h2><button>Enable</button></div>"
        "<div><h2><span>Provisioning</span></h2><button id='want'>Enable</button>"
        "<p>Provisioning method</p><p>Manual</p></div>"
        "<div><h2>Sign-in</h2><button>Manage authentication</button></div>"
        "</body>"
    )
    hits = dom.xpath(enable_button_xpath()[len("xpath="):])
    assert [h.get("id") for h in hits] == ["want"]


def test_xpath_matches_old_console_dom():
    etree = pytest.importorskip("lxml.etree")
    dom = etree.fromstring(
        "<body><div><h2>Identity-enhanced sessions</h2><button>Enable</button></div>"
        "<div><div>Automatic provisioning</div><button id='want'>Enable</button></div></body>"
    )
    hits = dom.xpath(enable_button_xpath()[len("xpath="):])
    assert [h.get("id") for h in hits] == ["want"]
