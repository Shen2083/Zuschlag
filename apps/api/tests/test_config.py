from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from zuschlag_api.core.config import CloudProvider, Settings


def make(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_to_frankfurt() -> None:
    assert Settings.model_fields["cloud_provider"].default is CloudProvider.AWS
    assert Settings.model_fields["cloud_region"].default == "eu-central-1"
    assert Settings.model_fields["s3_region"].default == "eu-central-1"
    assert Settings.model_fields["llm_aws_region"].default == "eu-central-1"


@pytest.mark.parametrize("region", ["us-east-1", "eu-central-2", "ap-southeast-1"])
def test_non_eu_aws_region_rejected(region: str) -> None:
    with pytest.raises(ValidationError, match="outside the EU"):
        make(cloud_region=region)


def test_azure_germany_west_central_allowed() -> None:
    assert make(cloud_provider="azure", cloud_region="germanywestcentral").cloud_region


def test_azure_region_must_match_provider() -> None:
    with pytest.raises(ValidationError, match="outside the EU"):
        make(cloud_provider="azure", cloud_region="eu-central-1")


def test_non_eu_llm_region_rejected() -> None:
    with pytest.raises(ValidationError, match="LLM_AWS_REGION"):
        make(llm_aws_region="us-west-2")


@pytest.mark.parametrize(
    "origin", ["*", "https://*.example.com", "https://app.example.com/path", "app.example.com"]
)
def test_bad_cors_origins_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        make(cors_allowed_origins=[origin])


def test_cors_origins_parsed_from_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.example.de, https://b.example.de/")
    assert Settings(_env_file=None).cors_allowed_origins == [
        "https://a.example.de",
        "https://b.example.de",
    ]


def test_production_rejects_dev_auth() -> None:
    with pytest.raises(ValidationError, match="dev_headers"):
        make(
            environment="production",
            embedding_provider="disabled",
            cors_allowed_origins=["https://app.zuschlag.ai"],
        )


def test_production_rejects_http_origins_and_placeholders() -> None:
    base: dict[str, Any] = {
        "environment": "production",
        "auth_mode": "oidc",
        "embedding_provider": "disabled",
    }
    with pytest.raises(ValidationError, match="https"):
        make(**base, cors_allowed_origins=["http://app.zuschlag.ai"])
    with pytest.raises(ValidationError, match="placeholder"):
        make(
            **base,
            cors_allowed_origins=["https://app.zuschlag.ai"],
            audit_ip_hmac_key="change-me-64-hex-chars-placeholder-value",
        )


def test_short_hmac_key_rejected() -> None:
    with pytest.raises(ValidationError, match="32 characters"):
        make(audit_ip_hmac_key="too-short")
