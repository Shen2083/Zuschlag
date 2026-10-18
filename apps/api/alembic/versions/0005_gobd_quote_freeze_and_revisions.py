"""GoBD: approved quotes are frozen; changes only through a new revision

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 19:40:00+00:00

Approval freezes a quote's content in the database itself, so no code path
(and no ad-hoc SQL as the runtime role) can change approved figures in place:

* `quotes`: once approved or synced, only the workflow columns may change
  (status, revision, last IDoc, export time, updated_at). Leaving `approved`
  for `draft` must open the next revision (revision + 1); a synced quote is
  final.
* `quote_items`: no INSERT, UPDATE or DELETE while the quote is approved or
  synced.

The application records each new revision, with the frozen predecessor's
snapshot and hash, in the append-only `quote_audit_trail`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORKFLOW_COLUMNS = "ARRAY['status', 'revision', 'last_idoc_docnum', 'exported_at', 'updated_at']"


def upgrade() -> None:
    op.add_column("quotes", sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
    op.create_check_constraint("revision_positive", "quotes", "revision >= 1")

    op.execute(
        f"""
        CREATE FUNCTION app.quotes_enforce_freeze() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status IN ('approved', 'synced') THEN
              RAISE EXCEPTION 'quote % is % and cannot be deleted (GoBD)',
                OLD.quote_number, OLD.status USING ERRCODE = 'ZQ001';
            END IF;
            RETURN OLD;
          END IF;

          IF OLD.status NOT IN ('approved', 'synced') THEN
            IF NEW.revision <> OLD.revision THEN
              RAISE EXCEPTION 'a new revision can only be opened from an approved quote'
                USING ERRCODE = 'ZQ001';
            END IF;
            RETURN NEW;
          END IF;

          IF (to_jsonb(NEW) - {_WORKFLOW_COLUMNS}) IS DISTINCT FROM
             (to_jsonb(OLD) - {_WORKFLOW_COLUMNS}) THEN
            RAISE EXCEPTION 'quote % revision % is % and frozen (GoBD); open a new revision to change it',
              OLD.quote_number, OLD.revision, OLD.status USING ERRCODE = 'ZQ001';
          END IF;

          IF OLD.status = 'synced' THEN
            IF NEW.status <> 'synced' OR NEW.revision <> OLD.revision
               OR NEW.last_idoc_docnum IS DISTINCT FROM OLD.last_idoc_docnum
               OR NEW.exported_at IS DISTINCT FROM OLD.exported_at THEN
              RAISE EXCEPTION 'quote % was synced to SAP and is final', OLD.quote_number
                USING ERRCODE = 'ZQ001';
            END IF;
          ELSIF NEW.status = 'draft' THEN
            IF NEW.revision <> OLD.revision + 1 THEN
              RAISE EXCEPTION 'reopening approved quote % requires revision %',
                OLD.quote_number, OLD.revision + 1 USING ERRCODE = 'ZQ001';
            END IF;
          ELSIF NEW.status NOT IN ('approved', 'synced') OR NEW.revision <> OLD.revision THEN
            RAISE EXCEPTION 'invalid transition of approved quote % to %',
              OLD.quote_number, NEW.status USING ERRCODE = 'ZQ001';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER quotes_freeze BEFORE UPDATE OR DELETE ON quotes
        FOR EACH ROW EXECUTE FUNCTION app.quotes_enforce_freeze()
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.quote_items_enforce_freeze() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          frozen_status text;
        BEGIN
          SELECT q.status::text INTO frozen_status
            FROM quotes q
           WHERE q.id = COALESCE(NEW.quote_id, OLD.quote_id)
             AND q.status IN ('approved', 'synced');
          IF frozen_status IS NOT NULL THEN
            RAISE EXCEPTION 'quote items are frozen while the quote is % (GoBD)', frozen_status
              USING ERRCODE = 'ZQ001';
          END IF;
          RETURN COALESCE(NEW, OLD);
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER quote_items_freeze BEFORE INSERT OR UPDATE OR DELETE ON quote_items
        FOR EACH ROW EXECUTE FUNCTION app.quote_items_enforce_freeze()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS quote_items_freeze ON quote_items")
    op.execute("DROP FUNCTION IF EXISTS app.quote_items_enforce_freeze()")
    op.execute("DROP TRIGGER IF EXISTS quotes_freeze ON quotes")
    op.execute("DROP FUNCTION IF EXISTS app.quotes_enforce_freeze()")
    op.drop_constraint("revision_positive", "quotes", type_="check")
    op.drop_column("quotes", "revision")
