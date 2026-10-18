# Zuschlag.ai API

FastAPI service for RFQ ingestion, SAP master-data matching and quote generation.

```bash
uv sync --all-extras                       # --extra llm pulls in the Anthropic SDK (Bedrock)
uv run uvicorn zuschlag_api.main:app --reload
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                              # integration tests need TEST_DATABASE_URL
uv run alembic upgrade head                # uses MIGRATIONS_DATABASE_URL (schema owner)
```

## Layout

| Path | Purpose |
| --- | --- |
| `core/config.py` | Settings; enforces EU regions, strict CORS and production guards |
| `core/auth.py` | Request principal (tenant, actor, pseudonymised IP) |
| `db/session.py` | Async engine; `tenant_session()` binds `app.current_tenant` per transaction |
| `db/guards.py` | ORM tenancy guards (defence in depth on top of RLS) |
| `models/` | Tenants, SAP materials (pgvector), RFQs, quotes, audit log |
| `audit/service.py` | `record_audit()` and hash-chain verification |
| `llm/` | `ZeroRetentionLLMClient` and provider adapters (Bedrock eu-central-1, fake) |
| `sap/` | ORDERS05 quotation IDoc models and builder, contract-tested against `packages/sap-schema` |
| `alembic/versions/0001_*` | Schema, RLS policies, grants, audit triggers |

## Writing tenant data

```python
async with tenant_session(tenant_id) as db:  # RLS + ORM guards active
    db.add(Rfq(source=RfqSource.EMAIL, subject="..."))  # tenant_id filled in
    await record_audit(db, actor_id=..., action="rfq.created", entity_type="rfq", entity_id=...)
```

The audit row commits in the same transaction as the change, so you get both or neither.

To provision a tenant, open `tenant_session(new_id)` and insert `Tenant(tenant_id=new_id, ...)`: RLS only accepts the row while it is the session's own tenant.
