"""The provider "Platform URLs" block must not print a CloudFront /grafana path.

Grafana is Amazon Managed Grafana, there is no in-cluster Grafana behind the ALB, so
`https://<domain>/grafana` does not exist (404). `task setup-env` writes the real
AMG endpoint to $GRAFANA_URL.

Run:  python -m pytest workshop/scripts/tests/test_platform_urls_grafana.py -q
"""
import os

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


@pytest.mark.parametrize("provider", ["kind-kro-ack", "kind-crossplane"])
def test_urls_block_has_no_cloudfront_grafana_path(provider):
    text = open(os.path.join(REPO, "cluster-providers", provider, "Taskfile.yaml")).read()
    assert "INGRESS_DOMAIN}}/grafana" not in text
    assert "Grafana:    Amazon Managed Grafana" in text
