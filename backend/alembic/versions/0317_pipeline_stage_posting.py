"""Etap „Ogłoszenia" (`posting`) — pierwsza kolumna kanbana przed „Nowi".

Revision ID: 0317_pipeline_stage_posting
Revises: 0316_order_mail_auto_recheck

Why:
- Kandydaci z ogłoszeń (pracuj.pl / JJIT, auto-match integracji) wpadali na
  „Nowi / Analiza CV" razem z kandydatami wybranymi ręcznie i zaśmiecali
  pierwszą kolumnę. Decyzja Artura 2026-09-16: osobna, PIERWSZA kolumna
  „Ogłoszenia" — poczekalnia, z której rekruter świadomie przenosi na „Nowi".
- Pełnoprawny etap w enumie (a nie kolumna z `legacy_enum_value=NULL`), żeby
  alerty „utknął", raporty i mini-lejek umiały go odróżnić od `new`.
- Wzór: 0056 (`verified`) — ALTER TYPE w `autocommit_block` + wstawienie
  stage defa do KAŻDEGO szablonu z trikiem +1000/−999 na `order`
  (UNIQUE (template_id, order) nie jest DEFERRABLE). Idempotentne.
- Domyślny etap bulk-add nadal = pierwszy nie-`posting` (proposals_bulk),
  więc ręczne dodawanie trafia do „Nowi" jak dotąd.
- Lustro w `entrypoint.sh`.
"""

from alembic import op

revision = "0317_pipeline_stage_posting"
down_revision = "0316_order_mail_auto_recheck"
branch_labels = None
depends_on = None

STAGE_NAME = "Ogłoszenia"

INSERT_SQL = f"""
    DO $$
    DECLARE
        tpl_id INTEGER;
    BEGIN
        FOR tpl_id IN SELECT id FROM pipeline_templates LOOP
            IF NOT EXISTS (
                SELECT 1 FROM pipeline_stage_defs
                WHERE template_id = tpl_id
                  AND legacy_enum_value = 'posting'
            ) THEN
                UPDATE pipeline_stage_defs
                   SET "order" = "order" + 1000
                 WHERE template_id = tpl_id;
                INSERT INTO pipeline_stage_defs (
                    template_id, name, "order", category,
                    is_terminal, terminal_type, legacy_enum_value
                ) VALUES (
                    tpl_id, '{STAGE_NAME}', 0, 'internal',
                    FALSE, NULL, 'posting'
                );
                UPDATE pipeline_stage_defs
                   SET "order" = "order" - 999
                 WHERE template_id = tpl_id
                   AND "order" >= 1000;
            END IF;
        END LOOP;
    END $$;
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE pipelinestage ADD VALUE IF NOT EXISTS 'posting'")
    op.execute(INSERT_SQL)


def downgrade() -> None:
    # Wartość enuma zostaje (PG nie usuwa wartości typu); kolumna znika, a
    # kandydaci na niej (jeśli są) wracają do `new`.
    op.execute(
        "UPDATE candidate_stages SET stage = 'new', stage_def_id = NULL "
        "WHERE stage = 'posting'"
    )
    op.execute("DELETE FROM pipeline_stage_defs WHERE legacy_enum_value = 'posting'")
