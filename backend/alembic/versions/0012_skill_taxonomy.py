"""Phase B1: skill taxonomy — canonical skills + aliases

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-17 11:20:00.000000

Introduces a small, normalized taxonomy so matching can resolve
"python3" / "Python 3.11" → canonical "python" before comparing with
job must/nice skills.

Tables
------
skills
  id               serial PK
  canonical_name   text, lowercased, unique
  category         text, nullable (e.g. "language", "framework", "cloud", "soft")
  created_at       timestamptz default now()

skill_aliases
  id               serial PK
  skill_id         FK → skills.id ON DELETE CASCADE
  alias            text, lowercased, unique
  created_at       timestamptz default now()

Seed
----
A small bootstrap of common Polish IT market aliases. Extend via
`POST /api/skills/*` once the UI exposes it.
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


# Minimal, Polish-IT-market–oriented seed. Order: (canonical, category, [aliases])
SEED: list[tuple[str, str | None, list[str]]] = [
    ("python", "language", ["py", "python3", "python 3", "python 3.11", "python 3.12"]),
    ("javascript", "language", ["js", "ecmascript", "node.js runtime"]),
    ("typescript", "language", ["ts"]),
    ("java", "language", ["java 11", "java 17", "java 21"]),
    ("kotlin", "language", []),
    ("go", "language", ["golang"]),
    ("rust", "language", []),
    ("c#", "language", ["csharp", "c sharp", ".net language"]),
    ("c++", "language", ["cpp", "c plus plus"]),
    ("react", "framework", ["react.js", "reactjs"]),
    ("next.js", "framework", ["nextjs", "next js"]),
    ("angular", "framework", ["angular.js", "angularjs", "angular 2+"]),
    ("vue", "framework", ["vue.js", "vuejs"]),
    ("node", "framework", ["node.js", "nodejs"]),
    ("express", "framework", ["express.js", "expressjs"]),
    ("fastapi", "framework", []),
    ("django", "framework", []),
    ("flask", "framework", []),
    ("spring", "framework", ["spring framework"]),
    ("spring boot", "framework", ["springboot"]),
    ("postgresql", "database", ["postgres", "psql"]),
    ("mysql", "database", []),
    ("mongodb", "database", ["mongo"]),
    ("redis", "database", []),
    ("elasticsearch", "database", ["elastic", "es"]),
    ("docker", "devops", []),
    ("kubernetes", "devops", ["k8s"]),
    ("terraform", "devops", []),
    ("ansible", "devops", []),
    ("jenkins", "devops", []),
    ("github actions", "devops", ["gh actions"]),
    ("aws", "cloud", ["amazon web services"]),
    ("azure", "cloud", ["microsoft azure"]),
    ("gcp", "cloud", ["google cloud", "google cloud platform"]),
    ("kafka", "messaging", ["apache kafka"]),
    ("rabbitmq", "messaging", []),
    ("graphql", "api", []),
    ("rest", "api", ["rest api", "restful"]),
    ("grpc", "api", []),
    ("sql", "database", []),
    ("nosql", "database", []),
    ("scrum", "methodology", []),
    ("agile", "methodology", []),
    ("kanban", "methodology", []),
]


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("canonical_name", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("canonical_name", name="uq_skills_canonical_name"),
    )

    op.create_table(
        "skill_aliases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "skill_id",
            sa.Integer,
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("alias", name="uq_skill_aliases_alias"),
    )
    op.create_index(
        "ix_skill_aliases_skill_id", "skill_aliases", ["skill_id"]
    )

    # Seed canonical + aliases
    skills_tbl = sa.table(
        "skills",
        sa.column("id", sa.Integer),
        sa.column("canonical_name", sa.Text),
        sa.column("category", sa.Text),
    )
    aliases_tbl = sa.table(
        "skill_aliases",
        sa.column("skill_id", sa.Integer),
        sa.column("alias", sa.Text),
    )

    conn = op.get_bind()
    for canonical, category, alias_list in SEED:
        result = conn.execute(
            skills_tbl.insert()
            .values(canonical_name=canonical, category=category)
            .returning(skills_tbl.c.id)
        )
        skill_id = result.scalar_one()
        if alias_list:
            conn.execute(
                aliases_tbl.insert(),
                [{"skill_id": skill_id, "alias": a.lower()} for a in alias_list],
            )


def downgrade() -> None:
    op.drop_index("ix_skill_aliases_skill_id", table_name="skill_aliases")
    op.drop_table("skill_aliases")
    op.drop_table("skills")
