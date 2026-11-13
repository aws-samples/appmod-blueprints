"""Failure-evidence policy for the console automation (stdlib only, unit-testable).

Screenshots are the main evidence when the console flow breaks. They can also hold
secrets: once the SCIM token dialog is open (step 10) the bearer token may be shown in
cleartext. So:

* the always-on error screenshot is skipped once the token dialog has been shown,
  unless --debug was asked for explicitly (then the operator opted in, as for step10.png);
* every screenshot is written owner-only (umask 0o077).
"""

from __future__ import annotations

import contextlib
import os


def should_take_error_screenshot(debug: bool, token_exposed: bool) -> bool:
    """Take the error screenshot unless it could show the SCIM token without --debug."""
    return debug or not token_exposed


@contextlib.contextmanager
def private_umask():
    """Create files owner-only (0600) inside the block, then restore the umask."""
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)
