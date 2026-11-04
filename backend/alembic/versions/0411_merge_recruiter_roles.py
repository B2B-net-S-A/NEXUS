"""Jedna rola „Rekruter” zamiast sourcera, rekrutera i TAC (02.10.2026).

Decyzja Artura 02.10.2026: role `sourcer`, `recruiter` i `tac` łączymy w jedną
— `recruiter`. Konta i role dodatkowe przechodzą na rekrutera, wiersze
wycofanych ról znikają z tabel uprawnień i celów KPI, reguły powiadomień
etapów wskazujące te role są przepisane.

SQL ma JEDNO źródło: `app/services/role_merge.py` (bez importów aplikacji);
te same instrukcje biegną w `entrypoint.sh` przy każdym starcie. Są zbieżne —
drugi przebieg zmienia 0 wierszy i nie unieważnia sesji ponownie.

Etykiety `sourcer` i `tac` zostają w typie `userrole` i w CHECK-ach tabel RBAC
(szczegóły w docstringu modułu), więc migracja to sam DML.

Downgrade przywraca role kont ze stanu zapisanego w
`role_session_migration_audit` (tylko konta, których roli nikt potem nie
zmienił) oraz skasowane wiersze uprawnień.

Revision ID: 0411_merge_recruiter_roles
Revises: 0410_named_permissions
"""

from __future__ import annotations

from alembic import op

from app.services.role_merge import (
    ROLE_MERGE_RESTORE_STATEMENTS,
    ROLE_MERGE_STATEMENTS,
)

revision = "0411_merge_recruiter_roles"
down_revision = "0410_named_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ROLE_MERGE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in ROLE_MERGE_RESTORE_STATEMENTS:
        op.execute(statement)
