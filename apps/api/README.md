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
| `quoting/` | Zuschlagskalkulation (Herstellkosten -> Netto -> MwSt -> Brutto), payment terms, REQOTE export |
| `sap/reqote.py`, `sap/xsd/` | ORDERS05/REQOTE outbound IDoc builder and its XSD |
| `rfq/` | RFQ -> quote pipeline: extraction schema + prompt, hybrid matcher, costing, orchestration |
| `sap/orders05.py`, `sap/builder.py` | ORDERS05 quotation IDoc, contract-tested against `packages/sap-schema` |
| `alembic/versions/` | 0001 schema, RLS, audit triggers · 0002 SAP master data · 0003 prices, trigram search, quote BOM · 0004 VAT/gross, payment terms, IDoc numbering |

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

## RFQ -> quote pipeline

`POST /api/v1/quotes/generate-from-rfq` with `{"raw_text": "...", "customer_id": "100042"}`
(`customer_id` is optional: our UUID or the SAP KUNNR; `margin_pct` optionally overrides the
default Zuschlag). It returns `201` with the persisted quote and a nested BOM.

1. **Extraction** (`rfq/extraction.py`). Claude, through `ZeroRetentionLLMClient` (EU Bedrock,
   `Data-Retention: false`, compliance hash), returns an `RfqExtraction` via **structured outputs**
   (`messages.parse(output_format=...)`). The output holds the customer, delivery date and line
   items with quantity, ISO unit, specs and kind. Custom-made goods also get a proposed BOM
   (raw materials, semi-finished parts, purchased parts) and fabrication hours per operation.
   The inquiry is passed as tagged data, and the prompt tells the model to ignore instructions
   inside it.
2. **Hybrid matching** (`rfq/matching.py`). Each line and component is matched in three stages:
   1. An exact MATNR hit (cited number, or a token in the text) gives confidence about 1.0.
   2. Otherwise, pgvector cosine similarity (HNSW) and pg_trgm `word_similarity` (GIN) are
      combined, each calibrated to 0..1.
   3. The score is adjusted for material-type fit (FERT / HALB / ROH / HAWA), unit fit and
      ambiguity.

   Below `RFQ_REVIEW_THRESHOLD` (0.75), or when two materials are equally plausible, the item is
   `NEEDS_HUMAN_REVIEW`.
3. **Sourcing.** Each item is classified as one of:
   - `catalog`: a standard SAP material.
   - `custom_build`: a finished good costed from its components and labor.
   - `missing_in_catalog`: no plausible SAP material, so it has to be created or procured.
   - `internal`: own labor.
4. **Costing** (`rfq/pricing.py`):
   - **Material:** the MBEW standard or moving price ÷ PEINH, using the `SAP_VALUATION_AREA`.
   - **Labor:** hours × `LABOR_RATES_EUR`.
   - **Price:** cost + Zuschlag (default 22%) on the customer-facing lines.
   - **Missing prices:** these are reported, never guessed.
5. **Persistence.** `quotes`, `quote_items` (a hierarchy) and `quote_audit_trail` (append-only:
   `rfq.received`, `ai.extraction`, `ai.matching`, `quote.priced`, `quote.created`) are written,
   plus a global `audit_logs` entry. Everything is in one transaction, so a failed model call
   leaves nothing behind.

| Status | Meaning |
| --- | --- |
| 201 | Quote created (`draft`, or `needs_review` with `review_reasons`) |
| 404 | `customer_id` not found |
| 413 | `raw_text` is longer than `RFQ_MAX_CHARS` |
| 502 | The model refused, was truncated, or returned output that fails the schema |
| 503 | LLM not configured or not compliant (`LLM_PROVIDER`, `LLM_ZDR_ATTESTED`), or embedder down |

The calibration defaults assume `multilingual-e5-large`. Before going live, re-fit
`RFQ_DENSE_*` / `RFQ_LEXICAL_*` and the threshold on a labelled sample of your own RFQs.

Tests replay recorded structured outputs for German and English inquiries
(`tests/fixtures/rfq/`). `RUN_LIVE_LLM=1 uv run pytest tests/test_live_llm.py` runs the same
checks against the configured model.

## Calculation and SAP quotation export

**`POST /api/v1/quotes/{id}/calculate`** with
`{"zuschlag_pct": 22, "vat_rate": 19, "payment_terms": "NT30", "allow_terms_deviation": false}`:

| Step | Amount |
| --- | --- |
| Materialkosten + Fertigungslohn | Herstellkosten (factory cost) |
| + Zuschlag (0-100 %, per unit, rounded to 4 decimals, then cents per line) | Nettobetrag |
| + MwSt 19 % (standard) or 7 % (reduced), on the net total | Bruttobetrag |

Payment terms rules:

- **No terms given:** they default to the customer's agreed `ZTERM` from SAP (KNVV).
- **Agreed terms on file:** other terms are rejected (422) unless `allow_terms_deviation` is set.
- **Accepted keys:** `NT<days>` is understood. Any other key must be declared in
  `PAYMENT_TERMS_CATALOG`, so no quote goes out with terms nobody can explain.
- **Unpriced lines:** reported in `missing_price_positions`, not guessed.

A quote already synced to SAP cannot be recalculated (409). Every calculation is recorded
in `quote_audit_trail` with before and after values.

**`POST /api/v1/quotes/{id}/export-sap-idoc`** returns `application/xml`: one ORDERS05 IDoc
with message type REQOTE, a new `DOCNUM` from `sap_outbound_docnum_seq` (also in the
`X-IDoc-DOCNUM` header), validated against `sap/xsd/orders05_reqote.xsd`. The byte layout is
the interface contract `tests/fixtures/sap/quote_as_output.txt`, and tests compare the output
byte for byte: CRLF, no final newline, `SEGMENT`/`segment` attributes, empty fields omitted.
`.gitattributes` and pre-commit leave that file untouched. Export is refused (422, with every
reason listed) when:

- the tenant has no `sap_outbound_profile`,
- the quote was never calculated,
- the quote is not linked to an SAP customer, or
- a line has no confidently matched, priced SAP material. This covers custom builds that still
  need a FERT material, and `NEEDS_HUMAN_REVIEW` matches.

The tenant's `sap_outbound_profile` (JSON on `tenants`) holds MANDT, DOCREL, the
sender/receiver ports and partners, and our own vendor number and name for the `LF` partner.
