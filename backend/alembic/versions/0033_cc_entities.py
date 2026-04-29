"""Competence Category entities + seed + backfill.

Revision ID: 0033_cc_entities
Revises: 0032_app_settings
Create Date: 2026-04-21 12:00:00.000000

Adds 3 schema objects + 2 data migrations:

1. `competence_categories` — 5 seed rows (biznesowe kategorie kompetencji)
2. `user_competence_categories` — M2M user↔CC
3. FKs: `jobs.competence_category_id`, `candidates.competence_category_id`
4. `job_collaborators.source` — manual/auto_cc discriminator
5. `talent_pools.centroid_vector_id` + `centroid_updated_at` — cached member centroid
6. Backfill: map existing `candidates.competence_category` strings to FK via keyword ILIKE

Seed CCs (display_order 1..5):
  1 infrastructure_operations  — Infrastruktura i Operacje
  2 software_development       — Rozwój Oprogramowania
  3 data_ai                    — Dane i AI
  4 security_quality           — Bezpieczeństwo i Jakość
  5 management_delivery        — Zarządzanie i Dostarczanie
"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0033_cc_entities"
# NOTE: Alembic tracking in this DB sits at `notif_triggers_13` even though the
# actual schema already contains tables from sibling branches (app_settings,
# job_collaborators, candidate_invite_links, champion_profile_suggestions, ...).
# We branch from the currently-applied head to keep local + prod migrations
# applyable. A separate merge revision can later reconcile the orphan branches.
down_revision = "notif_triggers_13"
branch_labels = None
# This migration ALTERs `job_collaborators` (adds `source` column), which is
# created by 0029. On the prod DB at the time of writing this migration, the
# table existed in schema already (because the legacy 0001 ran create_all on
# the live ORM, which contained job_collaborators). After 0001 was refactored
# to pin to the 2026-03-18 schema, that crutch is gone — we must declare the
# cross-branch dependency explicitly so Alembic schedules 0029 first on fresh
# databases.
depends_on = ("0029",)


SEED_CCS = [
    {
        "slug": "infrastructure_operations",
        "name_pl": "Infrastruktura i Operacje",
        "name_en": "Infrastructure & Operations",
        "description": (
            "Zespoły odpowiedzialne za infrastrukturę, cloud, DevOps, SRE, platformę, "
            "sieć, bezpieczeństwo systemów, CI/CD oraz niezawodność. "
            "Kubernetes, Terraform, AWS/Azure/GCP, Linux, automatyzacja wdrożeń."
        ),
        "keywords": [
            "devops", "sre", "site reliability", "kubernetes", "k8s", "docker",
            "terraform", "ansible", "jenkins", "gitlab ci", "github actions",
            "aws", "azure", "gcp", "cloud", "linux", "sysadmin", "platform",
            "networking", "ci/cd", "helm", "prometheus", "grafana", "istio",
            "observability", "infrastructure",
        ],
        "display_order": 1,
    },
    {
        "slug": "software_development",
        "name_pl": "Rozwój Oprogramowania",
        "name_en": "Software Development",
        "description": (
            "Rozwój aplikacji frontend, backend, mobile, embedded. Frameworki webowe, "
            "języki programowania, architektura aplikacyjna. React, Java, Python, "
            "Node.js, iOS, Android."
        ),
        "keywords": [
            "frontend", "backend", "fullstack", "full stack", "full-stack",
            "react", "vue", "angular", "typescript", "javascript", "nextjs",
            "next.js", "nuxt", "java", "spring", "spring boot", "python",
            "django", "fastapi", "flask", "node", "nodejs", "node.js", "go",
            "golang", "rust", ".net", "dotnet", "c#", "csharp", "php", "laravel",
            "symfony", "ruby", "rails", "mobile", "ios", "swift", "android",
            "kotlin", "flutter", "react native", "embedded",
        ],
        "display_order": 2,
    },
    {
        "slug": "data_ai",
        "name_pl": "Dane i AI",
        "name_en": "Data & AI",
        "description": (
            "Inżynieria danych, data science, machine learning, analityka, BI. "
            "Spark, Airflow, Snowflake, PyTorch, TensorFlow, modele LLM, "
            "pipeline'y danych."
        ),
        "keywords": [
            "data engineer", "data scientist", "ml engineer", "machine learning",
            "deep learning", "ai", "nlp", "computer vision", "llm", "gpt",
            "tensorflow", "pytorch", "spark", "airflow", "dbt", "snowflake",
            "bigquery", "redshift", "databricks", "kafka", "analytics", "bi",
            "tableau", "power bi", "looker", "etl", "elt", "mlops",
            "feature store", "vector database",
        ],
        "display_order": 3,
    },
    {
        "slug": "security_quality",
        "name_pl": "Bezpieczeństwo i Jakość",
        "name_en": "Security & Quality",
        "description": (
            "Zapewnienie jakości, automatyzacja testów, cyberbezpieczeństwo, "
            "pentesting, compliance. Selenium, Playwright, OWASP, SIEM, audyt, "
            "red/blue team."
        ),
        "keywords": [
            "qa", "quality assurance", "tester", "test automation", "selenium",
            "cypress", "playwright", "junit", "pytest", "security", "pentester",
            "appsec", "application security", "owasp", "soc", "siem",
            "iso 27001", "sast", "dast", "red team", "blue team",
            "penetration testing", "vulnerability", "cybersecurity",
            "security engineer",
        ],
        "display_order": 4,
    },
    {
        "slug": "management_delivery",
        "name_pl": "Zarządzanie i Dostarczanie",
        "name_en": "Management & Delivery",
        "description": (
            "Zarządzanie produktem, projektami, zespołami, delivery. PM, PO, BA, "
            "Scrum Master, Tech Lead, Engineering Manager."
        ),
        "keywords": [
            "pm", "product manager", "project manager", "delivery lead",
            "delivery manager", "scrum master", "agile coach", "product owner",
            "po", "business analyst", "ba", "engineering manager", "tech lead",
            "team lead", "cto", "director", "head of",
        ],
        "display_order": 5,
    },
]


# Mapping of legacy free-text Candidate.competence_category → new CC slug.
# Each legacy keyword (ILIKE match on candidates.competence_category) maps to a
# single slug. Order matters: earlier entries win if a candidate string matches
# multiple patterns.
LEGACY_BACKFILL_MAP = [
    # software_development
    ("frontend", "software_development"),
    ("front-end", "software_development"),
    ("backend", "software_development"),
    ("back-end", "software_development"),
    ("fullstack", "software_development"),
    ("full-stack", "software_development"),
    ("full stack", "software_development"),
    ("mobile", "software_development"),
    ("ios", "software_development"),
    ("android", "software_development"),
    ("developer", "software_development"),
    ("programista", "software_development"),
    ("software", "software_development"),
    # infrastructure_operations
    ("devops", "infrastructure_operations"),
    ("sre", "infrastructure_operations"),
    ("cloud", "infrastructure_operations"),
    ("platform", "infrastructure_operations"),
    ("infrastructure", "infrastructure_operations"),
    ("infra", "infrastructure_operations"),
    ("admin", "infrastructure_operations"),
    # data_ai
    ("data", "data_ai"),
    ("ml", "data_ai"),
    ("ai", "data_ai"),
    ("analytics", "data_ai"),
    ("analyst", "data_ai"),
    ("bi ", "data_ai"),
    # security_quality
    ("qa", "security_quality"),
    ("test", "security_quality"),
    ("security", "security_quality"),
    ("pentest", "security_quality"),
    # management_delivery
    ("product", "management_delivery"),
    ("project manager", "management_delivery"),
    ("scrum", "management_delivery"),
    ("manager", "management_delivery"),
    ("lead", "management_delivery"),
]


def upgrade() -> None:
    # 1. competence_categories
    op.create_table(
        "competence_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("name_pl", sa.String(120), nullable=False),
        sa.Column("name_en", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column(
            "keywords",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("embedding_id", sa.String(100), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "display_order",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2. user_competence_categories (M2M)
    op.create_table(
        "user_competence_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "is_primary",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "user_id", "competence_category_id", name="uq_user_cc"
        ),
    )

    # 3. FK on jobs
    op.add_column(
        "jobs",
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_jobs_competence_category_id",
        "jobs",
        ["competence_category_id"],
    )

    # 4. FK on candidates (kept alongside legacy `competence_category` string)
    op.add_column(
        "candidates",
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_candidates_competence_category_id",
        "candidates",
        ["competence_category_id"],
    )

    # 5. job_collaborators.source
    jobcollabsource = sa.Enum(
        "manual", "auto_cc", name="jobcollaboratorsource"
    )
    jobcollabsource.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "job_collaborators",
        sa.Column(
            "source",
            jobcollabsource,
            nullable=False,
            server_default="manual",
        ),
    )

    # 6. talent_pools: centroid cache fields
    op.add_column(
        "talent_pools",
        sa.Column("centroid_vector_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "talent_pools",
        sa.Column(
            "centroid_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    # 7. Seed CCs
    conn = op.get_bind()
    for cc in SEED_CCS:
        conn.execute(
            sa.text(
                "INSERT INTO competence_categories "
                "(slug, name_pl, name_en, description, keywords, display_order) "
                "VALUES (:slug, :name_pl, :name_en, :description, "
                "CAST(:keywords AS JSONB), :display_order)"
            ),
            {
                "slug": cc["slug"],
                "name_pl": cc["name_pl"],
                "name_en": cc["name_en"],
                "description": cc["description"],
                "keywords": json.dumps(cc["keywords"]),
                "display_order": cc["display_order"],
            },
        )

    # 8. Backfill candidates.competence_category_id from legacy string
    for pattern, slug in LEGACY_BACKFILL_MAP:
        conn.execute(
            sa.text(
                "UPDATE candidates "
                "SET competence_category_id = cc.id "
                "FROM competence_categories cc "
                "WHERE cc.slug = :slug "
                "  AND candidates.competence_category_id IS NULL "
                "  AND candidates.competence_category ILIKE :pattern"
            ),
            {"slug": slug, "pattern": f"%{pattern}%"},
        )


def downgrade() -> None:
    op.drop_column("talent_pools", "centroid_updated_at")
    op.drop_column("talent_pools", "centroid_vector_id")
    op.drop_column("job_collaborators", "source")
    sa.Enum(name="jobcollaboratorsource").drop(op.get_bind(), checkfirst=True)
    op.drop_index(
        "ix_candidates_competence_category_id", table_name="candidates"
    )
    op.drop_column("candidates", "competence_category_id")
    op.drop_index("ix_jobs_competence_category_id", table_name="jobs")
    op.drop_column("jobs", "competence_category_id")
    op.drop_table("user_competence_categories")
    op.drop_table("competence_categories")
