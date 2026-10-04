"""„Stawka od” kandydata: kolumny, decyzje rekruterów i kolejka przeliczeń.

Revision ID: 0414_candidate_rate_from
Revises: 0413_recommendation_cards

Kandydat podaje różne stawki na różne role. Filtry i AI czytały jedną liczbę
z profilu (ostatnio zapisaną). Od tej migracji czytają najniższą stawkę
z ostatnich 18 miesięcy, liczoną z kart rekomendacji, etapów, zmian profilu
i zgłoszeń (decyzje Artura 04.10.2026). Liczy pętla ``candidate_rate_from``
po starcie — migracja tylko kolejkuje kandydatów.

SQL ma jedno źródło (``app/services/candidate_rate_from_schema.py``) — ten sam
moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import candidate_rate_from_schema as schema

revision = "0414_candidate_rate_from"
down_revision = "0413_recommendation_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Decyzje rekruterów („Nie licz jako minimum”) żyją tylko w tej tabeli.
    bind = op.get_bind()
    decisions = bind.exec_driver_sql(
        "SELECT count(*) FROM candidate_rate_decisions"
    ).scalar()
    if decisions:
        raise RuntimeError(
            f"candidate_rate_decisions ma {decisions} decyzji rekruterów — "
            "downgrade skasowałby je bez śladu."
        )
    for table, trigger in (
        ("recommendation_cards", "trg_rate_from_cards"),
        ("candidate_stages", "trg_rate_from_stages"),
        ("candidates", "trg_rate_from_profile"),
        ("candidates", "trg_rate_from_profile_insert"),
        ("application_submissions", "trg_rate_from_submissions"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for fn in (
        "trg_rate_from_cards()",
        "trg_rate_from_stages()",
        "trg_rate_from_profile()",
        "trg_rate_from_profile_insert()",
        "trg_rate_from_submissions()",
        "candidate_rate_from_enqueue(integer)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.execute("DROP TABLE IF EXISTS candidate_rate_from_queue")
    op.execute("DROP TABLE IF EXISTS candidate_rate_decisions")
    op.execute("DROP INDEX IF EXISTS ix_candidates_rate_from_hourly")
    for col in (
        "rate_observation_count",
        "rate_latest_at",
        "rate_latest_hourly",
        "rate_from_computed_at",
        "rate_from_stale",
        "rate_from_job_id",
        "rate_from_source",
        "rate_from_at",
        "rate_from_hourly",
    ):
        op.execute(f"ALTER TABLE candidates DROP COLUMN IF EXISTS {col}")
    op.execute(
        "DELETE FROM app_settings WHERE key = '0414_candidate_rate_from_queued'"
    )
