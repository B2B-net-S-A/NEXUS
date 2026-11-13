"""„Ludzie w NEXUSIE” — jeden punkt, z którego ``entrypoint.sh`` bierze SQL modułu.

Każdy moduł HR ma własny ``*_schema.py`` (to samo źródło czyta jego migracja).
Entrypoint importuje tylko ten agregator i wpina listy w swoje fazy:

* ``COLUMN_DDL`` — tabele, kolumny, indeksy nowych tabel i CHECK-i ról
  (koniec ``_COLUMN_STATEMENTS``: tabele bazowe już istnieją),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (koniec ``_DATA_STATEMENTS``),
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do istniejących tabel.

Nowe wartości typów enum (``userrole``, ``notificationtype``) stoją literalnie
w ``_ENUM_STATEMENTS`` — ta lista jest zdefiniowana przed importami.
"""

from __future__ import annotations

from app.services import admin_cases_schema as admin_cases
from app.services import back_office_schema as back_office
from app.services import back_office_role_schema as back_office_role
from app.services import board_role_schema as board_role
from app.services import viewer_role_schema as viewer_role
from app.services import care_announcements_schema as care_announcements
from app.services import care_board_schema as care_board
from app.services import client_sales_invoices_schema as sales_invoices
from app.services import client_einvoices_schema as client_einvoices
from app.services import client_invoice_issue_schema as client_invoice_issue
from app.services import client_settlements_schema as client_settlements
from app.services import client_structure_schema as client_structure
from app.services import client_time_reports_schema as client_time_reports
from app.services import consultant_panel_schema as consultant_panel
from app.services import consultant_portal_schema as consultant_portal
from app.services import contract_care_schema as contract_care
from app.services import equipment_extras_schema as equipment_extras
from app.services import equipment_protocol_cancel_schema as equipment_cancel
from app.services import equipment_schema as equipment
from app.services import hr_access_schema as access
from app.services import hr_account_profile_schema as account_profile
from app.services import hr_agreements_schema as agreements
from app.services import hr_approval_basis_schema as approval_basis
from app.services import hr_approval_settlement_schema as approval_settlement
from app.services import hr_approvals_schema as approvals
from app.services import hr_bonus_guarantee_schema as bonus_guarantee
from app.services import hr_documents_schema as documents
from app.services import hr_foundation_schema as foundation
from app.services import hr_leave_proofs_schema as leave_proofs
from app.services import hr_leave_cpro_schema as leave_cpro
from app.services import hr_leave_schema as leave
from app.services import hr_lifecycle_schema as lifecycle
from app.services import hr_notification_schema as notifications
from app.services import hr_payroll_schema as payroll
from app.services import hr_settlement_schema as settlement
from app.services import hr_time_schema as time_
from app.services import trainings_schema as trainings

#: Moduły po fundamencie, w kolejności migracji 0458–0476 (0467 i 0472 to statystyki z maina) (kontrakt każdego:
#: ``TABLE_DDL, COLUMN_DDL, INDEX_DDL, CONSTRAINT_DDL, DATA_DDL``).
MODULES = (
    leave,
    time_,
    payroll,
    lifecycle,
    contract_care,
    admin_cases,
    equipment,
    equipment_extras,
    care_announcements,
    settlement,
    documents,
    agreements,
    sales_invoices,
    leave_proofs,
    client_structure,
    account_profile,
    approvals,
    approval_settlement,
    approval_basis,
    # 0509: tablica opieki i popyt dla DL (przebudowa opieki, 22.10.2026).
    care_board,
    # 0611: poprawka i anulowanie protokołu sprzętu (28.10.2026).
    equipment_cancel,
    # 0622: zastępca do Cpro we wniosku urlopowym (29.10.2026).
    leave_cpro,
    # 0637: kolejka spraw całego back office'u (02.11.2026).
    back_office,
    # 0638: portal konsultanta (02.11.2026).
    consultant_portal,
    # 0648: panel konsultanta, aktywacja i materiały (05.11.2026).
    consultant_panel,
    # 0653: gwarancja premii DL — dług i potrącenia (05.11.2026).
    bonus_guarantee,
    # 0679: rozliczenia klientów E1 (09.11.2026).
    client_settlements,
    # 0689: rozliczenia Nordei N1 — kartoteka i wersje raportu T4T (13.11.2026).
    client_time_reports,
    # 0692: e-faktury Peppol do klientów (plan Nordei N2, 13.11.2026).
    client_einvoices,
    # 0694: szkolenia i trenerzy — zamówienie, wycena, umowa, pliki (13.11.2026).
    trainings,
    # 0695: wystawianie faktur sprzedaży do KSeF — szkice, numeracja (E4, 13.11.2026).
    client_invoice_issue,
)

COLUMN_DDL: tuple[str, ...] = (
    *foundation.TABLE_DDL,
    *foundation.INDEX_DDL,
    *access.ROLE_CHECK_DDL,
    # 0490: rola „Rada nadzorcza” — po CHECK-ach „Pracownika”, przed zasiewem.
    *board_role.ROLE_CHECK_DDL,
    *back_office_role.ROLE_CHECK_DDL,
    *(stmt for module in MODULES for stmt in module.TABLE_DDL),
    *(stmt for module in MODULES for stmt in module.COLUMN_DDL),
    *(stmt for module in MODULES for stmt in module.INDEX_DDL),
)

DATA_DDL: tuple[str, ...] = (
    *foundation.DATA_DDL,
    *access.SEED_DDL,
    *board_role.SEED_DDL,
    *back_office_role.SEED_DDL,
    # 0637: raz, potem decyzja admina z panelu wygrywa.
    *viewer_role.DATA_DDL,
    *(stmt for module in MODULES for stmt in module.DATA_DDL),
)

CONSTRAINT_DDL: tuple[str, ...] = tuple(
    stmt for module in MODULES for stmt in module.CONSTRAINT_DDL
)

#: Wartości enumów, które musi znać ``_ENUM_STATEMENTS`` (test lustra).
ENUM_DDL: tuple[str, ...] = (
    access.ENUM_DDL,
    board_role.ENUM_DDL,
    back_office_role.ENUM_DDL,
    *notifications.ENUM_DDL,
)
