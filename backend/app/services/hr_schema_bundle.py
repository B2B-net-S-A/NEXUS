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
from app.services import back_office_team_schema as back_office_team
from app.services import board_role_schema as board_role
from app.services import viewer_role_schema as viewer_role
from app.services import care_announcements_schema as care_announcements
from app.services import care_board_schema as care_board
from app.services import client_sales_invoices_schema as sales_invoices
from app.services import client_einvoices_schema as client_einvoices
from app.services import client_invoice_issue_schema as client_invoice_issue
from app.services import client_invoice_templates_schema as client_invoice_templates
from app.services import client_invoice_series_ext_schema as client_invoice_series_ext
from app.services import (
    client_invoice_collective_correction_schema as client_invoice_collective_correction,
)
from app.services import cv_parse_batch_schema as cv_parse_batch
from app.services import finance_archive_schema as finance_archive
from app.services import order_revenue_steps_schema as order_revenue_steps
from app.services import order_cost_steps_schema as order_cost_steps
from app.services import board_documents_schema as board_documents
from app.services import board_budget_schema as board_budgets
from app.services import board_statements_schema as board_statements
from app.services import board_meetings_schema as board_meetings
from app.services import board_votes_schema as board_votes
from app.services import board_reports_schema as board_reports
from app.services import client_settlements_schema as client_settlements
from app.services import client_settlement_extras_schema as settlement_extras
from app.services import client_settlement_reminders_schema as settlement_reminders
from app.services import client_settlement_feedback_schema as settlement_feedback
from app.services import client_structure_schema as client_structure
from app.services import client_time_reports_schema as client_time_reports
from app.services import client_reports_schema as client_reports
from app.services import consultant_panel_schema as consultant_panel
from app.services import consultant_portal_schema as consultant_portal
from app.services import contract_care_schema as contract_care
from app.services import contractor_payment_blocks_schema as contractor_payment_blocks
from app.services import equipment_extras_schema as equipment_extras
from app.services import equipment_protocol_cancel_schema as equipment_cancel
from app.services import equipment_schema as equipment
from app.services import finance_ledger_schema as finance_ledger
from app.services import finance_payments_schema as finance_payments
from app.services import ledger_assets_schema as ledger_assets
from app.services import ledger_automation_schema as ledger_automation
from app.services import ledger_bank_balance_schema as ledger_bank_balances
from app.services import ledger_bank_schema as ledger_bank
from app.services import ledger_export_schema as ledger_export
from app.services import ledger_fx_schema as ledger_fx
from app.services import ledger_schema as ledger
from app.services import ledger_settlement_schema as ledger_settlement
from app.services import ledger_vat_schema as ledger_vat
from app.services import finance_posting_schema as finance_posting
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
from app.services import hr_payroll_k7b_schema as payroll_k7b
from app.services import hr_payroll_lists_schema as payroll_lists
from app.services import hr_payroll_schema as payroll
from app.services import hr_settlement_schema as settlement
from app.services import hr_time_schema as time_
from app.services import trainings_schema as trainings
from app.services.law_radar import schema as law_radar
from app.services.cpro_bot import schema as cpro_bot
from app.services.contract_rate_documents import schema_sql as contract_rate_documents
from app.services.contract_partner_reads import schema_sql as contract_partner_reads
from app.services.contract_rate_history import schema_sql as contract_rate_history

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
    # 0695: księgowość w Finansach — kontrahenci i kolejka kosztów (E0, E1, 13.11.2026).
    finance_ledger,
    # 0696: wystawianie faktur sprzedaży do KSeF — szkice, numeracja (E4, 13.11.2026).
    client_invoice_issue,
    # 0699: przelewy i zapłaty faktur kosztowych (E3, 13.11.2026).
    finance_payments,
    # 0698: księgowość E2 — plan kont, reguły dekretu, dekret i paczki eksportu (13.11.2026).
    finance_posting,
    # 0700: księga NEXUSA K1 — lata, okresy, dokumenty, dziennik, trwałość zapisów (13.11.2026).
    ledger,
    # 0701: automaty księgi K3a — PK cykliczne i RMK (14.11.2026).
    ledger_automation,
    # 0702: paczki księgi do Symfonii FK K3b (14.11.2026).
    ledger_export,
    # 0703: środki trwałe i WNiP K6 — ewidencja i dokumenty środka (14.11.2026).
    ledger_assets,
    # 0704: płace liczone w NEXUSIE K7a — dane osoby, parametry, listy (14.11.2026).
    payroll_lists,
    # 0705: wyciągi bankowe w księdze K4a — jeden import wyciągu (14.11.2026).
    ledger_bank,
    # 0706: rozrachunki z rozliczaniem pozycji K4b (14.11.2026).
    ledger_settlement,
    # 0707: waluty w księdze K4c-1 — rachunki walutowe, kurs pozycji (15.11.2026).
    ledger_fx,
    # 0708: pliki JPK_V7M K5b — ewidencja VAT z deklaracją (15.11.2026).
    ledger_vat,
    # 0742: salda i numery wyciągów — ciągłość rachunku dla „po terminie” (19.11.2026).
    ledger_bank_balances,
    # 0709: szablony faktur cykliczne, refaktury benefitów, faktura z ręki (E6, 15.11.2026).
    client_invoice_templates,
    # 0712: katalog raportów klienta — definicje i historia wysyłek (15.11.2026).
    client_reports,
    # 0713: radar przepisów — biegi botów, pozycje, zmiany w prawie (15.11.2026).
    law_radar,
    # 0718: serie faktur jak w eBI24 — BEN (refaktury benefitów) i KORUE (16.11.2026).
    client_invoice_series_ext,
    # 0719: płace K7b — pensje UoP, składniki, oznaczenia L4, historia podstaw (16.11.2026).
    payroll_k7b,
    # 0720: archiwum dokumentów z eBI24 w Finansach (E5, 16.11.2026).
    finance_archive,
    # 0724: kroki stawki przychodowej zamówienia z aneksu (16.11.2026).
    order_revenue_steps,
    # 0727: dokumenty Rady nadzorczej i odpisy KRS spółki (R1, 16.11.2026).
    board_documents,
    # 0732: bot Cpro — biegi rutyny Grok Bota (17.11.2026).
    cpro_bot,
    # 0733: budżet Rady — plan miesięczny sprzedaży i kosztów (R3, 16.11.2026).
    board_budgets,
    # 0734: sprawozdania roczne dla Rady — bilans i RZiS (R4, 18.11.2026).
    board_statements,
    # 0735: posiedzenia Rady z zamrażanym pakietem (R5, 18.11.2026).
    board_meetings,
    # 0736: uchwały Rady w trybie pisemnym (R6, 18.11.2026).
    board_votes,
    # 0737: gotówka i archiwum raportów Rady (R7, 18.11.2026).
    board_reports,
    # 0739: stawki Partnera z umów i aneksów kontraktu (18.11.2026).
    contract_rate_documents,
    # 0741: koszt zamówienia od dnia zmiany stawki Partnera (19.11.2026).
    order_cost_steps,
    # 0746: jeden zespół back office'u, „Na zewnątrz” i ściąga klienta (19.11.2026).
    back_office_team,
    # 0749: korekta zbiorcza rabatu od obrotu — kolumna i CHECK korekty (22.11.2026).
    client_invoice_collective_correction,
    # 0750: kolejka odczytów CV wsadem (Message Batches API, 22.11.2026).
    cv_parse_batch,
    # 0751: dodatki do rozliczenia kontraktora — źródła, karta sprawy, dokumenty (13.11.2026).
    settlement_extras,
    # 0755: dane firm Partnerów z podpisanych umów do potwierdzenia (E5a, 22.11.2026).
    contract_partner_reads,
    # 0763: przypomnienia o brakującym raporcie godzin — dziennik wysyłek (23.11.2026).
    settlement_reminders,
    # 0765: zajęcia wierzytelności i spór przy płatnościach kontraktorów (23.11.2026).
    contractor_payment_blocks,
    # 0774: informacja zwrotna o wadach rozliczenia — wada × kontrakt × miesiąc (24.11.2026).
    settlement_feedback,
    # 0781: historia stawek kontraktu z faktur KSeF (25.11.2026).
    contract_rate_history,
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
    *settlement_reminders.ENUM_DDL,
    *settlement_feedback.ENUM_DDL,
)
