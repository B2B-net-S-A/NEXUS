"""Karta klienta (`client_playbooks`) — standardy współpracy poza profilem Championa.

Sekcja 6 „O kliencie" i 7 „Dokumenty" profilu Championa niosły wiedzę PER
KLIENT kopiowaną do każdej oferty (opis klienta, standardy, off-limit, typ
umowy, język CV, dokumenty), a 14 wzorów Word per klient dublowało ją raz
jeszcze. Żaden konsument backendu tych pól nie czytał, a KPI/SLA nie miało
w bazie domu. Ta rewizja daje im jeden: tabela 1:1 z klientem, prowadzona
przez Delivery Leada, wersjonowana (`client_playbook_events`).

Seed z `app/data/client_playbooks/seed.json` (treść dawnych 14 wzorów).
Wiersz powstaje wyłącznie przy DOKŁADNIE JEDNYM żywym kliencie pasującym
do wzorca nazwy (kalka 0255) i NIGDY nie nadpisuje istniejącego —
`ON CONFLICT (client_id) DO NOTHING`, edycja DL wygrywa z seedem.

14 wzorów per klient schodzi z Pomocy (decyzja produktowa 03.09.2026,
`is_published=false`); wiersze zostają, bo przegląd reguł CV linkuje je po
slugu.

Revision ID: 0271_client_playbooks
Revises: 0270_jobs_open_state_dates
"""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0271_client_playbooks"
down_revision = "0270_jobs_open_state_dates"
branch_labels = None
depends_on = None

# backend/alembic/versions/0271_… → parents[2] == backend/
_SEED_FILE = (
    Path(__file__).resolve().parents[2] / "app" / "data" / "client_playbooks" / "seed.json"
)

# Slugi 14 wzorów Championa per klient (migracja 0219) — wycofywane z Pomocy.
_CHAMPION_CLIENT_TEMPLATE_SLUGS: tuple[str, ...] = (
    "profil-championa-wzor-alior-docx",
    "profil-championa-wzor-bank-pocztowy-docx",
    "profil-championa-wzor-bik-docx",
    "profil-championa-wzor-bnp-paribas-docx",
    "profil-championa-wzor-credit-agricole-docx",
    "profil-championa-wzor-energa-docx",
    "profil-championa-wzor-kir-docx",
    "profil-championa-wzor-nordea-docx",
    "profil-championa-wzor-orlen-docx",
    "profil-championa-wzor-pansa-docx",
    "profil-championa-wzor-pfron-docx",
    "profil-championa-wzor-pko-bp-docx",
    "profil-championa-wzor-santander-docx",
    "profil-championa-wzor-tauron-docx",
)

# Każdy bind rzutowany jawnie: w `INSERT … SELECT` Postgres nie wywnioskuje
# typu NULL-a, a asyncpg wymaga typu z serwera. `documents` idzie jako
# string JSON + CAST — SQLAlchemy nie serializuje listy w `sa.text`.
_SEED_SQL = sa.text(
    """
    INSERT INTO client_playbooks (
        client_id, sla_business_days, sla_min_candidates, cv_limit_per_process,
        hold_hours, multi_project_cooldown_days, rate_policy, about_for_candidate,
        priority_rules, process_rules_md, onboarding_md, documents,
        version, seed_key, created_at, updated_at
    )
    SELECT c.id,
           CAST(:sla_business_days AS integer),
           CAST(:sla_min_candidates AS integer),
           CAST(:cv_limit_per_process AS integer),
           CAST(:hold_hours AS integer),
           CAST(:multi_project_cooldown_days AS integer),
           CAST(:rate_policy AS varchar),
           CAST(:about_for_candidate AS text),
           CAST(:priority_rules AS text),
           CAST(:process_rules_md AS text),
           CAST(:onboarding_md AS text),
           CAST(:documents AS jsonb),
           1, CAST(:seed_key AS varchar), now(), now()
    FROM clients c
    WHERE lower(c.name) LIKE :name_pattern
      AND c.hidden = false
      AND c.merged_into_client_id IS NULL
      AND (
          SELECT count(*) FROM clients c2
          WHERE lower(c2.name) LIKE :name_pattern
            AND c2.hidden = false
            AND c2.merged_into_client_id IS NULL
      ) = 1
    ON CONFLICT (client_id) DO NOTHING
    """
)


def _seed_entries() -> list[dict]:
    # Czytane W `upgrade()`, nie przy imporcie: `alembic heads` importuje
    # wszystkie rewizje i nie może paść na brakującym pliku danych.
    if not _SEED_FILE.exists():
        return []
    return json.loads(_SEED_FILE.read_text(encoding="utf-8"))


def upgrade() -> None:
    op.create_table(
        "client_playbooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sla_business_days", sa.Integer(), nullable=True),
        sa.Column("sla_min_candidates", sa.Integer(), nullable=True),
        sa.Column("cv_limit_per_process", sa.Integer(), nullable=True),
        sa.Column("hold_hours", sa.Integer(), nullable=True),
        sa.Column("multi_project_cooldown_days", sa.Integer(), nullable=True),
        sa.Column("rate_policy", sa.String(length=500), nullable=True),
        sa.Column("about_for_candidate", sa.Text(), nullable=True),
        sa.Column("priority_rules", sa.Text(), nullable=True),
        sa.Column("process_rules_md", sa.Text(), nullable=True),
        sa.Column("onboarding_md", sa.Text(), nullable=True),
        sa.Column("documents", postgresql.JSONB(), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("seed_key", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(sla_business_days IS NULL "
            "OR (sla_business_days >= 0 AND sla_business_days <= 365)) AND "
            "(sla_min_candidates IS NULL OR sla_min_candidates > 0) AND "
            "(cv_limit_per_process IS NULL OR cv_limit_per_process > 0) AND "
            "(hold_hours IS NULL OR hold_hours > 0) AND "
            "(multi_project_cooldown_days IS NULL "
            "OR multi_project_cooldown_days > 0)",
            name="ck_client_playbooks_numbers",
        ),
    )
    op.create_index(
        "ux_client_playbooks_client", "client_playbooks", ["client_id"], unique=True
    )
    op.create_index("ix_client_playbooks_seed_key", "client_playbooks", ["seed_key"])

    op.create_table(
        "client_playbook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("playbook_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_client_playbook_events_client_created",
        "client_playbook_events",
        ["client_id", "created_at"],
    )

    # ── Seed z repo (nigdy nie nadpisuje) ────────────────────────────────
    conn = op.get_bind()
    for entry in _seed_entries():
        conn.execute(
            _SEED_SQL,
            {
                "name_pattern": entry["name_pattern"],
                "seed_key": entry["seed_key"],
                "sla_business_days": entry.get("sla_business_days"),
                "sla_min_candidates": entry.get("sla_min_candidates"),
                "cv_limit_per_process": entry.get("cv_limit_per_process"),
                "hold_hours": entry.get("hold_hours"),
                "multi_project_cooldown_days": entry.get("multi_project_cooldown_days"),
                "rate_policy": entry.get("rate_policy"),
                "about_for_candidate": entry.get("about_for_candidate"),
                "priority_rules": entry.get("priority_rules"),
                "process_rules_md": entry.get("process_rules_md"),
                "onboarding_md": entry.get("onboarding_md"),
                "documents": json.dumps(
                    entry.get("documents") or [], ensure_ascii=False
                ),
            },
        )

    # ── Wycofanie 14 wzorów per klient z Pomocy (decyzja 03.09.2026) ─────
    # Lustro w entrypoint: krok 5.7c (marker w app_settings).
    slugs = ", ".join(f"'{slug}'" for slug in _CHAMPION_CLIENT_TEMPLATE_SLUGS)
    op.execute(
        "UPDATE help_materials SET is_published = false, updated_at = now() "
        f"WHERE slug IN ({slugs})"
    )


def downgrade() -> None:
    # Lustro: przywróć publikację (bez tego downgrade zostawiałby Pomoc pustą).
    slugs = ", ".join(f"'{slug}'" for slug in _CHAMPION_CLIENT_TEMPLATE_SLUGS)
    op.execute(
        "UPDATE help_materials SET is_published = true, updated_at = now() "
        f"WHERE slug IN ({slugs})"
    )
    op.drop_index("ix_client_playbook_events_client_created", "client_playbook_events")
    op.drop_table("client_playbook_events")
    op.drop_index("ix_client_playbooks_seed_key", "client_playbooks")
    op.drop_index("ux_client_playbooks_client", "client_playbooks")
    op.drop_table("client_playbooks")
