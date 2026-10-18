"""Application settings.

Everything is read from the environment (or `.env`). Validation is strict on
purpose: the API refuses to start with a non-EU region, wildcard CORS, or
development-only auth in production, rather than running in a non-compliant
configuration.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from zuschlag_api.rfq.pricing import DEFAULT_LABOR_RATES_EUR


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

    # --- embeddings ------------------------------------------------------------
    embedding_provider: Literal[
        "sentence_transformers", "openai_compatible", "hashing", "disabled"
    ] = "sentence_transformers"
    # Local model name/path, or the deployment name on a private endpoint.
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_device: str | None = None  # e.g. "cpu", "cuda"; None = auto
    embedding_endpoint_url: str | None = None
    embedding_api_key: SecretStr | None = None
    # Set true only when the endpoint is hosted in the EU under a no-retention contract.
    embedding_endpoint_eu_attested: bool = False

    # --- SAP master-data ingestion -------------------------------------------------
    sap_idoc_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    sap_idoc_max_files: int = Field(default=20, ge=1, le=100)
    # Order in which E1MAKTM languages are preferred for the primary description.
    sap_description_languages: Annotated[list[str], NoDecode] = ["DE", "EN"]
    # Valuation area (BWKEY) whose E1MBEWM price is used for costing; None = first priced area.
    sap_valuation_area: str | None = None
    # Company-code currency of the valuation prices (MBEW carries no currency).
    sap_valuation_currency: str = "EUR"

    # --- SAP outbound (REQOTE quotations) ---------------------------------------
    # file: write IDoc XML into a directory read by an SAP file port (WE21 "File").
    # http: POST it to an SAP "XML HTTP" port / integration middleware.
    sap_outbound_transport: Literal["disabled", "file", "http"] = "disabled"
    sap_outbound_dir: Path | None = None
    sap_outbound_url: str | None = None
    sap_outbound_username: str | None = None
    sap_outbound_password: SecretStr | None = None
    sap_outbound_timeout_s: float = Field(default=10.0, gt=0, le=120)

    # --- RFQ -> quote pipeline ---------------------------------------------------
    rfq_max_chars: int = Field(default=50_000, ge=100)
    # Matches below this confidence are flagged NEEDS_HUMAN_REVIEW.
    rfq_review_threshold: float = Field(default=0.75, ge=0, le=1)
    # Below this, the best candidate is not even linked as a suggestion.
    rfq_suggestion_floor: float = Field(default=0.60, ge=0, le=1)
    # Score calibration (see rfq/matching.py); defaults suit multilingual-e5-large.
    rfq_dense_floor: float = 0.70
    rfq_dense_ceiling: float = 0.95
    rfq_lexical_floor: float = 0.10
    rfq_lexical_ceiling: float = 0.60
    quote_default_margin_pct: Decimal = Field(default=Decimal("22"), ge=0, lt=1000)
    quote_default_currency: str = "EUR"
    # EUR per hour by fabrication operation (JSON object in the environment).
    labor_rates_eur: dict[str, Decimal] = Field(
        default_factory=lambda: dict(DEFAULT_LABOR_RATES_EUR)
    )
    labor_default_rate_eur: Decimal = Decimal("80")
    quote_default_payment_terms: str = "NT30"
    quote_default_vat_rate: Decimal = Decimal("19")
    # Payment-term keys other than NT<days>, with their net days (JSON object).
    payment_terms_catalog: dict[str, int] = Field(default_factory=lambda: {"0001": 0})

    _split_origins = field_validator(
        "cors_allowed_origins", "trusted_hosts", "sap_description_languages", mode="before"
    )(_split_csv)

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

        if self.embedding_provider == "openai_compatible":
            url = self.embedding_endpoint_url
            if not url:
                raise ValueError("EMBEDDING_ENDPOINT_URL is required for openai_compatible")
            parts = urlsplit(url)
            local = parts.hostname in {"localhost", "127.0.0.1"}
            if parts.scheme != "https" and not (local and not self.is_production):
                raise ValueError("EMBEDDING_ENDPOINT_URL must use https")
            if not self.embedding_endpoint_eu_attested:
                raise ValueError(
                    "EMBEDDING_ENDPOINT_EU_ATTESTED must be true: catalog data may only be "
                    "sent to an EU-hosted, no-retention embedding endpoint"
                )

        if self.sap_outbound_transport == "file" and self.sap_outbound_dir is None:
            raise ValueError("SAP_OUTBOUND_DIR is required for SAP_OUTBOUND_TRANSPORT=file")
        if self.sap_outbound_transport == "http":
            if not self.sap_outbound_url:
                raise ValueError("SAP_OUTBOUND_URL is required for SAP_OUTBOUND_TRANSPORT=http")
            parts = urlsplit(self.sap_outbound_url)
            local = parts.hostname in {"localhost", "127.0.0.1"}
            if parts.scheme != "https" and not (local and not self.is_production):
                raise ValueError("SAP_OUTBOUND_URL must use https")

        if self.environment is Environment.PRODUCTION:
            if self.embedding_provider == "hashing":
                raise ValueError("EMBEDDING_PROVIDER=hashing is for tests only")
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
