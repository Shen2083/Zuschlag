# Zuschlag.ai

AI-powered request-to-quote for the German Mittelstand. It ingests unstructured customer RFQs (e-mail, PDF, spec sheets), matches them against SAP master data, and produces a bill of materials and an SAP-compliant quote (ORDERS05 IDoc).

## Repository layout

```
apps/
  web/          Next.js 15 (App Router, TypeScript, Tailwind v4, shadcn/ui, Lucide)
  api/          FastAPI · Pydantic v2 · SQLAlchemy 2.0 async · Alembic · PostgreSQL 16 + pgvector (uv)
  prototype/    Clickable Vite prototype, deployed to GitHub Pages
packages/
  sap-schema/   SAP IDoc JSON Schemas (source of truth), generated TS types, runtime validator
infra/
  postgres/init Role and extension bootstrap (used by docker compose and CI)
```

pnpm workspaces and Turborepo run the JavaScript packages. `apps/api` is a uv project with a thin `package.json`, so `pnpm dev`, `pnpm test` and the rest of the turbo tasks cover it too.

## Quick start

Prerequisites: Node ≥ 20.18 (22 recommended), pnpm 10, Python ≥ 3.11 with [uv](https://docs.astral.sh/uv/), and Docker.

```bash
cp .env.example .env                 # then replace every change-me-* value
pnpm install
(cd apps/api && uv sync --all-extras)
pnpm infra:up                        # Postgres 16 + pgvector, Redis, MinIO (127.0.0.1 only)
pnpm db:migrate                      # Alembic, as the schema-owner role
pnpm dev                             # web on :3000, api on :8000
uvx pre-commit install --install-hooks
```

| Command                                             | What it does                                  |
| --------------------------------------------------- | --------------------------------------------- |
| `pnpm build` / `lint` / `typecheck` / `test`        | Turbo across web, api, sap-schema             |
| `pnpm --filter @zuschlag/sap-schema generate`       | Regenerate TS types after editing a schema    |
| `pnpm --filter @zuschlag/api db:revision "message"` | New Alembic migration (autogenerate)          |
| `docker compose --profile app up --build`           | Also build and run the api and web containers |

API tests that need a database run when `TEST_DATABASE_URL` (runtime role) is set. `TEST_ADMIN_DATABASE_URL` (superuser) additionally enables the tamper-detection test. CI provides both.

## Security and compliance baseline

| Requirement                     | How it is enforced                                                                                                                                                                                                                                                                                                                                                                       | Where                                                     |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| **Tenant isolation**            | `tenant_id NOT NULL` on every table. PostgreSQL RLS is **enabled and forced** on every table, and policies compare against `app.current_tenant`, which is set per transaction (`set_config(..., true)`), so it can't leak through the connection pool. The API connects as `zuschlag_app` (not owner, `NOBYPASSRLS`).                                                                    | `alembic/versions/0001_*`, `db/session.py`                |
| **Schema-level tenancy guards** | Every foreign key between domain tables is composite `(tenant_id, id)`, so a row can't reference another tenant's row. ORM guards scope every SELECT, refuse unscoped queries and refuse writes with a foreign or changed `tenant_id`. Metadata tests fail the build if a new table breaks either rule.                                                                                  | `models/`, `db/guards.py`, `tests/test_metadata.py`       |
| **EU data residency**           | Defaults to AWS `eu-central-1` (Frankfurt); Azure `germanywestcentral` is supported. The API **refuses to start** with a non-EU cloud, S3 or LLM region. The bucket is created with `LocationConstraint=eu-central-1`.                                                                                                                                                                   | `core/config.py`, `docker-compose.yml`                    |
| **Zero-retention LLM**          | All model calls go through `ZeroRetentionLLMClient`. It refuses providers without a ZDR attestation, non-EU regions and models that require retention, and always sends `Data-Retention: false`, which callers can't override. Each call produces a verifiable `compliance_hash` over prompt and response digests; only the hashes are logged and written to `audit_logs`.               | `llm/client.py`, `llm/providers.py`                       |
| **GoBD audit log**              | `audit_logs` records `timestamp_utc`, `tenant_id`, `actor_id`, `action`, `entity_type`, `entity_id` and `ip_sha256`. The runtime role has only `SELECT, INSERT`, and triggers reject `UPDATE`, `DELETE` and `TRUNCATE` even for the owner. The server stamps the time. Rows form a per-tenant SHA-256 hash chain, checked by `app.audit_chain_breaks()` and `GET /v1/audit-logs/verify`. | migration, `audit/service.py`                             |
| **SAP IDoc ingestion**          | IDoc XML is parsed with `defusedxml` with DTDs forbidden (no XXE, entity expansion or external fetches). Payload size and file count are capped. Every IDoc is validated with Pydantic, and the whole payload is applied in one transaction. Idempotency comes from a per-tenant `(sender, DOCNUM)` receipt ledger plus order-safe `ON CONFLICT` upserts.                                | `apps/api/src/zuschlag_api/sap/`                          |
| **AI quoting**                  | LLM output is schema-validated (structured outputs), and inquiries are passed as data, not instructions. Low-confidence or ambiguous SAP matches are flagged `NEEDS_HUMAN_REVIEW`. AI-proposed BOMs always require confirmation. Every step goes to an append-only `quote_audit_trail`.                                                                                                  | `apps/api/src/zuschlag_api/rfq/`                          |
| **IP pseudonymisation**         | `ip_sha256` is an HMAC-SHA256 with a secret key. A plain SHA-256 of an IPv4 address can be reversed by brute force.                                                                                                                                                                                                                                                                      | `core/security.py`                                        |
| **CORS / HTTP hardening**       | Exact origins only (wildcards rejected, https in production), an explicit method and header list, `TrustedHostMiddleware`, security headers, and no OpenAPI docs in production. The web app uses a per-request nonce CSP plus HSTS, frame denial and a Permissions-Policy, and loads no third-party fonts or CDNs.                                                                       | `main.py`, `apps/web/src/middleware.ts`, `next.config.ts` |
| **Secrets**                     | `.env` is git-ignored. gitleaks runs in pre-commit (staged changes) and in CI (full history). `detect-private-key` also runs.                                                                                                                                                                                                                                                            | `.pre-commit-config.yaml`, `.gitleaks.toml`, CI           |

### Known gaps (deliberately not built yet)

- **Authentication** is a stub. `AUTH_MODE=dev_headers` trusts `X-Tenant-ID` and is rejected in production; `oidc` returns 501 until an EU-hosted IdP (e.g. Entra ID or Keycloak) is chosen.
- **Zero data retention is contractual.** It has to be agreed with the model provider for the account in use. The header and the `LLM_ZDR_ATTESTED` flag make the policy explicit and auditable; they don't replace that agreement. Claude Fable 5.x is blocked because it isn't offered under ZDR.
- **GoBD long-term retention:** the database guarantees immutability and tamper evidence. A 10-year WORM export (S3 Object Lock, compliance mode) is the next step.
- **MinIO** stopped publishing community images in 2025. Compose pins a source build of its final release (`coollabsio/minio`); it is only used as a local S3 mock.
