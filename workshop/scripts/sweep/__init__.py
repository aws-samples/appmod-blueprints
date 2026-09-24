"""Teardown sweep package (issue #924 refactor).

Only the resilience layer is imported eagerly here — it is pure (no boto3),
so `import sweep.resilience` in unit tests never triggers AWS client creation.
Reaper modules are imported by the orchestrator/entrypoint at run time.
"""

from .resilience import (  # noqa: F401
    classify,
    error_code,
    is_access_denied,
    is_already_gone,
    is_transient,
    ensure_tenacity,
    poll_until,
    retry_aws,
    using_stdlib_fallback,
)
