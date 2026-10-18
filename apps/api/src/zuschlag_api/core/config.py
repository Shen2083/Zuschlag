"""Application settings.

Everything is read from the environment (or `.env`). Validation is strict on
purpose: the API refuses to start with a non-EU region, wildcard CORS, or
development-only auth in production, rather than running in a non-compliant
configuration.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class CloudProvider(StrEnum):
    AWS = "aws"
    AZURE = "azure"


# Regions inside the European Union. Switzerland (eu-central-2, switzerlandnorth)
# and the UK are deliberately absent: adequate under GDPR, but not EU.
EU_REGIONS: dict[CloudProvider, frozenset[str]] = {
    CloudProvider.AWS: frozenset(
        {"eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2"}
    ),
    CloudProvider.AZURE: frozenset(
        {
            "germanywestcentral",
            "germanynorth",
            "westeurope",
            "northeurope",
            "francecentral",
            "swedencentral",
            "italynorth",
            "polandcentral",
            "spaincentral",
        }
    ),
}

DEFAULT_REGION: dict[CloudProvider, str] = {
    CloudProvider.AWS: "eu-central-1",  # Frankfurt
    CloudProvider.AZURE: "germanywestcentral",  # Frankfurt
}

_PLACEHOLDER_PREFIX = "change-me"


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    # --- data residency ----------------------------------------------------
    cloud_provider: CloudProvider = CloudProvider.AWS
    cloud_region: str = DEFAULT_REGION[CloudProvider.AWS]

    # --- persistence ---------------------------------------------------------
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://zuschlag_app:change-me-app@localhost:5432/zuschlag"
    )
    migrations_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)
    redis_url: SecretStr | None = None

    s3_endpoint_url: str | None = None
    s3_region: str = "eu-central-1"
    s3_bucket: str = "zuschlag-rfq-attachments"

    # --- HTTP security -------------------------------------------------------
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    trusted_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]
    audit_ip_hmac_key: SecretStr = SecretStr(f"{_PLACEHOLDER_PREFIX}-dev-only-audit-ip-key-0000")
    auth_mode: Literal["dev_headers", "oidc"] = "dev_headers"

    # --- LLM -----------------------------------------------------------------
    llm_provider: Literal["bedrock", "disabled"] = "disabled"
    llm_model: str = "anthropic.claude-opus-5-5"
    llm_aws_region: str = "eu-central-1"
    llm_zdr_attested: bool = False

    _split_origins = field_validator("cors_allowed_origins", "trusted_hosts", mode="before")(
        _split_csv
    )

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            if "*" in origin:
                raise ValueError("wildcard CORS origins are not allowed; list exact origins")
            parts = urlsplit(origin)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError(f"invalid CORS origin {origin!r}: expected scheme://host[:port]")
            if parts.path not in {"", "/"} or parts.query or parts.fragment:
                raise ValueError(f"CORS origin {origin!r} must not contain a path or query")
        return [o.rstrip("/") for o in origins]

    @field_validator("trusted_hosts")
    @classmethod
    def _validate_hosts(cls, hosts: list[str]) -> list[str]:
        if any(h == "*" for h in hosts):
            raise ValueError("TRUSTED_HOSTS must list explicit host names")
        return hosts

    @model_validator(mode="after")
    def _validate_residency_and_prod(self) -> Settings:
        allowed = EU_REGIONS[self.cloud_provider]
        if self.cloud_region not in allowed:
            raise ValueError(
                f"CLOUD_REGION {self.cloud_region!r} is outside the EU for "
                f"{self.cloud_provider.value}; allowed: {sorted(allowed)}"
            )
        if self.s3_region not in EU_REGIONS[CloudProvider.AWS]:
            raise ValueError(f"S3_REGION {self.s3_region!r} is outside the EU")
        if self.llm_aws_region not in EU_REGIONS[CloudProvider.AWS]:
            raise ValueError(f"LLM_AWS_REGION {self.llm_aws_region!r} is outside the EU")

        if self.environment is Environment.PRODUCTION:
            if self.auth_mode == "dev_headers":
                raise ValueError("AUTH_MODE=dev_headers is not allowed in production")
            if any(urlsplit(o).scheme != "https" for o in self.cors_allowed_origins):
                raise ValueError("production CORS origins must use https")
            for name in ("audit_ip_hmac_key", "database_url"):
                secret: SecretStr = getattr(self, name)
                if _PLACEHOLDER_PREFIX in secret.get_secret_value():
                    raise ValueError(f"{name.upper()} still contains a placeholder value")
        if len(self.audit_ip_hmac_key.get_secret_value()) < 32:
            raise ValueError("AUDIT_IP_HMAC_KEY must be at least 32 characters")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
