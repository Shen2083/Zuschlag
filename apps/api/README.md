# Zuschlag.ai API

FastAPI service for RFQ ingestion, SAP master-data matching and quote generation.

```bash
uv sync --all-extras                       # llm: Anthropic SDK (Bedrock) · embeddings: sentence-transformers (CPU torch)
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
| `sap/idoc_xml.py` | Hardened IDoc XML reader (defusedxml, streaming, namespace-agnostic) |
| `sap/master_data.py` | MATMAS05 / DEBMAS06 Pydantic models and parsers |
| `sap/ingest.py` | Idempotent, order-safe upserts of materials and customers |
| `embeddings/` | Embedding backends: local sentence-transformers, private OpenAI-compatible endpoint, hashing (tests) |
| `sap/orders05.py`, `sap/builder.py` | ORDERS05 quotation IDoc, contract-tested against `packages/sap-schema` |
| `alembic/versions/0001_*` | Schema, RLS policies, grants, audit triggers |

## Writing tenant data

```python
async with tenant_session(tenant_id) as db:  # RLS + ORM guards active
    db.add(Rfq(source=RfqSource.EMAIL, subject="..."))  # tenant_id filled in
    await record_audit(db, actor_id=..., action="rfq.created", entity_type="rfq", entity_id=...)
```

The audit row commits in the same transaction as the change, so you get both or neither.

To provision a tenant, open `tenant_session(new_id)` and insert `Tenant(tenant_id=new_id, ...)`: RLS only accepts the row while it is the session's own tenant.

## SAP master-data ingestion

`POST /api/v1/sap/matmas` (MATMAS05) and `POST /api/v1/sap/debmas` (DEBMAS06) accept the
IDoc XML that an SAP "XML HTTP" port (SM59 type G) sends, either as the raw body
(`application/xml`, `text/xml`) or as `multipart/form-data` with one or more files.

```bash
curl -X POST localhost:8000/api/v1/sap/matmas -H "X-Tenant-ID: $TENANT" \
     -H "Content-Type: application/xml" --data-binary @tests/fixtures/sap/matmas05_shenai.xml
```

The response lists one outcome per IDoc:

| Outcome | Meaning |
| --- | --- |
| `created` / `updated` | Object written. For materials, the embedding is computed if its text changed. |
| `unchanged` | Same business content under a new DOCNUM: only the DOCNUM watermark advances |
| `stale` | Older than the stored DOCNUM (out-of-order delivery), or superseded inside the same packet |
| `duplicate` | This `(sender, DOCNUM)` was already received with the same content |

HTTP status codes:

| Status | When |
| --- | --- |
| 200 | Payload accepted. This includes pure re-deliveries, so SAP doesn't retry them. |
| 400 | Malformed or unsafe XML (DTDs, entities, XXE), or wrong IDoc type |
| 409 | A known DOCNUM arrived with different content |
| 413 | Payload too large |
| 415 | Unsupported content type |
| 422 | Field validation failed. The response names the DOCNUM and the fields. |

A payload is one transaction: nothing is stored unless every IDoc in it is valid.

**Embeddings.** Each material is embedded as `"{MATNR} {MAKTX} {MTART}"`. MAKTX is taken in the first
language of `SAP_DESCRIPTION_LANGUAGES` (default `DE,EN`). The vector is stored in
`materials.embedding` (pgvector, HNSW cosine index). The default backend runs
`intfloat/multilingual-e5-large` in-process, so catalog text never leaves the host. Bake the model
into the image with `--build-arg PRELOAD_EMBEDDING_MODEL=intfloat/multilingual-e5-large` to avoid
downloading weights at runtime. Alternatively, `EMBEDDING_PROVIDER=openai_compatible` targets a private
endpoint; it requires https and `EMBEDDING_ENDPOINT_EU_ATTESTED=true`.
