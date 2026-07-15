"""Cortex Trust Foundation — dedup taksonomii + guardy + trwałe runy + provenance.

Revision ID: 0167_cortex_trust_foundation
Revises: 0166_contract_framework_rate_schedule
Create Date: 2026-07-13

Naprawia P0 audytu (docs/cortex/cortex-audit-2026-07-13.md):

1. **Dedup taksonomii.** Migracja 0012 seeduje canonicale lowercase ("python"),
   ``scripts/seed_skill_aliases.py`` seeduje Title-Case ("Python"), a unique jest
   case-sensitive → duplikaty koegzystują. Skutki: split liczników w tech-map
   (``group_by(canonical_name)``) i niedeterministyczny ``skill_id`` w
   ``fact_store.load_taxonomy`` (dict last-wins). Tu scalamy duplikaty (37 par
   case-insensitive + 5 par semantycznych typu ``kafka``/``Apache Kafka``),
   repinując aliasy i fakty na survivora, i zakładamy funkcyjne unique indexy
   ``lower(canonical_name)`` / ``lower(alias)`` jako guard na przyszłość.

2. **Idempotentny unmatched.** Nowa tabela ``cortex_unmatched_observations``
   (UNIQUE term+candidate+source) — licznik ``occurrences`` liczy unikalnych
   kandydatów, nie przebiegów backfillu.

3. **Trwałe runy.** ``cortex_extraction_runs`` zastępuje in-memory job dict
   (restart-safe status + single-flight przez advisory lock w API).

4. **Provenance + integralność.** Kolumny ``extractor_version``/``run_id``/
   ``content_hash``/``source_ref`` na faktach + DB CHECK dla source/level/years/
   confidence/status.

Idempotentne (IF NOT EXISTS / DO-guard) — współgra z ``alembic upgrade heads``
oraz safety-netem w ``entrypoint.sh`` (nowe tabele/kolumny mirrorowane tam też).
Uwaga: scalanie danych taksonomii jest NIEODWRACALNE — downgrade zdejmuje tylko
nowy schemat, nie odtwarza usuniętych duplikatów.
"""

from collections import defaultdict

from alembic import op
from sqlalchemy import text

revision = "0167_cortex_trust_foundation"
down_revision = "0166_contract_framework_rate_schedule"
branch_labels = None
depends_on = None


# Pary semantyczne: ten sam koncept, różne stringi canonicala (lower() się różni,
# więc NIE łapie ich dedup case-insensitive). Loser (lower) → survivor (lower).
_EXPLICIT_MERGES = [
    ("kafka", "apache kafka"),
    ("express", "express.js"),
    ("node", "node.js"),
    ("rest", "rest api"),
    ("vue", "vue.js"),
]


def _merge_pair(conn, loser_id: int, survivor_id: int) -> None:
    """Przepnij aliasy + fakty z loser na survivor, dodaj canonical loser jako
    alias survivora i usuń loser skill. Kolizje faktów na
    ``uq_cortex_fact_cand_skill_source`` rozwiązujemy zachowując wiersz survivora
    (traffit ma jednorodny confidence, więc nie tracimy sygnału)."""
    # 1. Przepnij fakty, które NIE kolidują z istniejącym faktem survivora.
    conn.execute(
        text(
            """
            UPDATE cortex_skill_facts f
               SET skill_id = :sur
             WHERE f.skill_id = :los
               AND NOT EXISTS (
                   SELECT 1 FROM cortex_skill_facts f2
                    WHERE f2.candidate_id = f.candidate_id
                      AND f2.skill_id = :sur
                      AND f2.source = f.source)
            """
        ),
        {"sur": survivor_id, "los": loser_id},
    )
    # 2. Kolidujące resztki loser (survivor już ma taki fakt) — odrzuć.
    conn.execute(
        text("DELETE FROM cortex_skill_facts WHERE skill_id = :los"),
        {"los": loser_id},
    )
    # 3. Przepnij aliasy (alias jest globalnie UNIQUE → brak kolizji na repin).
    conn.execute(
        text("UPDATE skill_aliases SET skill_id = :sur WHERE skill_id = :los"),
        {"sur": survivor_id, "los": loser_id},
    )
    # 4. Canonical loser zostaje aliasem survivora — stare tokeny nadal rozwiążą.
    conn.execute(
        text(
            """
            INSERT INTO skill_aliases (skill_id, alias)
            SELECT :sur, lower(canonical_name) FROM skills WHERE id = :los
            ON CONFLICT (alias) DO NOTHING
            """
        ),
        {"sur": survivor_id, "los": loser_id},
    )
    # 5. Usuń loser skill (aliasy/fakty już przepięte).
    conn.execute(text("DELETE FROM skills WHERE id = :los"), {"los": loser_id})


def _dedup_taxonomy(conn) -> None:
    rows = conn.execute(text("SELECT id, canonical_name FROM skills")).all()
    if not rows:
        return
    alias_counts = dict(
        conn.execute(
            text("SELECT skill_id, count(*) FROM skill_aliases GROUP BY skill_id")
        ).all()
    )

    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for sid, name in rows:
        groups[name.lower()].append((sid, name))

    def pick_survivor(members: list[tuple[int, str]]) -> int:
        # Preferuj Title-Case (m[1] != lower → False sortuje pierwsze),
        # potem więcej aliasów, potem najniższe id — w pełni deterministyczne.
        return sorted(
            members,
            key=lambda m: (m[1] == m[1].lower(), -alias_counts.get(m[0], 0), m[0]),
        )[0][0]

    def group_survivor(lowername: str):
        members = groups.get(lowername)
        if not members:
            return None
        return members[0][0] if len(members) == 1 else pick_survivor(members)

    mapping: dict[int, int] = {}

    # Pass 1 — duplikaty case-insensitive (python/Python, aws/AWS, …).
    for members in groups.values():
        if len(members) > 1:
            survivor = pick_survivor(members)
            for sid, _name in members:
                if sid != survivor:
                    mapping[sid] = survivor

    # Pass 2 — pary semantyczne (kafka→Apache Kafka, …), po survivorach grup.
    for loser_name, sur_name in _EXPLICIT_MERGES:
        los = group_survivor(loser_name)
        sur = group_survivor(sur_name)
        if los and sur and los != sur:
            mapping[los] = sur

    # Rozwiąż łańcuchy do finalnego survivora (A→B, B→C ⇒ A→C, B→C).
    def final(sid: int) -> int:
        seen = set()
        while sid in mapping and sid not in seen:
            seen.add(sid)
            sid = mapping[sid]
        return sid

    for loser_id in sorted(mapping):
        survivor_id = final(loser_id)
        if survivor_id != loser_id:
            _merge_pair(conn, loser_id, survivor_id)

    # Dedup aliasów case-insensitive (aliasy i tak są lowercase — zwykle no-op).
    conn.execute(
        text(
            """
            DELETE FROM skill_aliases a
             USING skill_aliases b
             WHERE a.id > b.id
               AND lower(a.alias) = lower(b.alias)
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Scal duplikaty taksonomii PRZED założeniem guard-indexów.
    _dedup_taxonomy(conn)

    # 2. Guard na przyszłość — funkcyjne unique po lower().
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_canonical_lower "
        "ON skills (lower(canonical_name))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_aliases_alias_lower "
        "ON skill_aliases (lower(alias))"
    )

    # 3. Provenance kolumny na faktach + first_seen_at na unmatched.
    op.execute(
        "ALTER TABLE cortex_skill_facts "
        "ADD COLUMN IF NOT EXISTS extractor_version VARCHAR(40)"
    )
    op.execute(
        "ALTER TABLE cortex_skill_facts ADD COLUMN IF NOT EXISTS run_id BIGINT"
    )
    op.execute(
        "ALTER TABLE cortex_skill_facts "
        "ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE cortex_skill_facts "
        "ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE cortex_unmatched_terms "
        "ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ"
    )
    op.execute(
        "UPDATE cortex_unmatched_terms "
        "SET first_seen_at = last_seen_at WHERE first_seen_at IS NULL"
    )

    # 4. Nowe tabele.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cortex_extraction_runs (
            id                  BIGSERIAL PRIMARY KEY,
            run_type            VARCHAR(10) NOT NULL,
            source              VARCHAR(20) NOT NULL DEFAULT 'traffit',
            status              VARCHAR(12) NOT NULL DEFAULT 'running',
            triggered_by        VARCHAR(120) NULL,
            started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at         TIMESTAMPTZ NULL,
            heartbeat_at        TIMESTAMPTZ NULL,
            cursor_candidate_id INTEGER NULL,
            stats               JSONB NULL,
            last_error          TEXT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_runs_status_started "
        "ON cortex_extraction_runs (status, started_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_runs_started "
        "ON cortex_extraction_runs (started_at)"
    )
    # Single-flight: najwyżej jeden aktywny run na źródło (atomowo, restart-safe).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cortex_single_running "
        "ON cortex_extraction_runs (source) WHERE status = 'running'"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cortex_unmatched_observations (
            id            BIGSERIAL PRIMARY KEY,
            term          TEXT NOT NULL,
            candidate_id  INTEGER NOT NULL
                              REFERENCES candidates(id) ON DELETE CASCADE,
            source        VARCHAR(20) NOT NULL DEFAULT 'traffit',
            last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cortex_unmatched_obs UNIQUE (term, candidate_id, source)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_unmatched_obs_term "
        "ON cortex_unmatched_observations (term)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_unmatched_obs_candidate "
        "ON cortex_unmatched_observations (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cortex_unmatched_status "
        "ON cortex_unmatched_terms (status)"
    )

    # 5. DB CHECK constraints (idempotentnie — pomiń jeśli już są).
    checks = [
        (
            "cortex_skill_facts",
            "ck_cortex_fact_source",
            "source IN ('traffit', 'cv_llm', 'screening')",
        ),
        (
            "cortex_skill_facts",
            "ck_cortex_fact_level",
            "level IS NULL OR level IN ('junior', 'mid', 'senior')",
        ),
        (
            "cortex_skill_facts",
            "ck_cortex_fact_years",
            "years IS NULL OR (years >= 0 AND years <= 40)",
        ),
        (
            "cortex_skill_facts",
            "ck_cortex_fact_confidence",
            "confidence >= 0 AND confidence <= 1",
        ),
        (
            "cortex_unmatched_terms",
            "ck_cortex_unmatched_status",
            "status IN ('new', 'mapped', 'ignored')",
        ),
        (
            "cortex_extraction_runs",
            "ck_cortex_run_type",
            "run_type IN ('manual', 'daily', 'full')",
        ),
        (
            "cortex_extraction_runs",
            "ck_cortex_run_status",
            "status IN ('running', 'ok', 'errors', 'failed')",
        ),
    ]
    for table, name, expr in checks:
        op.execute(
            f"""
            DO $$ BEGIN
                ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr});
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        )


def downgrade() -> None:
    # Uwaga: scalenie duplikatów taksonomii jest nieodwracalne — zdejmujemy
    # tylko nowy schemat.
    for table, name in [
        ("cortex_skill_facts", "ck_cortex_fact_source"),
        ("cortex_skill_facts", "ck_cortex_fact_level"),
        ("cortex_skill_facts", "ck_cortex_fact_years"),
        ("cortex_skill_facts", "ck_cortex_fact_confidence"),
        ("cortex_unmatched_terms", "ck_cortex_unmatched_status"),
        ("cortex_extraction_runs", "ck_cortex_run_type"),
        ("cortex_extraction_runs", "ck_cortex_run_status"),
    ]:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")

    op.execute("DROP TABLE IF EXISTS cortex_unmatched_observations")
    op.execute("DROP TABLE IF EXISTS cortex_extraction_runs")

    op.execute("DROP INDEX IF EXISTS ix_cortex_unmatched_status")
    op.execute("ALTER TABLE cortex_unmatched_terms DROP COLUMN IF EXISTS first_seen_at")
    for col in ("extractor_version", "run_id", "content_hash", "source_ref"):
        op.execute(f"ALTER TABLE cortex_skill_facts DROP COLUMN IF EXISTS {col}")

    op.execute("DROP INDEX IF EXISTS uq_skill_aliases_alias_lower")
    op.execute("DROP INDEX IF EXISTS uq_skills_canonical_lower")
