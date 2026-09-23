"""Słowniki dokumentów pochodnych bez żadnych importów z aplikacji.

Czyta je model, migracja 0358 i siatka DDL w ``entrypoint.sh``. Siatka importuje
ten moduł ZANIM ustawi adres bazy, więc nie może on (pośrednio) ładować
``app.core.database`` — silnik związałby się z domyślnym adresem, a narzędzie
``scripts/schema_inventory.py`` budowałoby schemat w niewłaściwej bazie.
"""

B2B_DOCUMENT_TYPES: tuple[str, ...] = (
    "annex_rate_change",
    "annex_start_date",
    "annex_party_data",
    "annex_subcontractor",
    "annex_mandate",
    "termination_agreement",
    "termination_agreement_mandate",
    "termination_notice",
    "notice_withdrawal",
    "preliminary_cez",
)

B2B_DOCUMENT_STATUSES: tuple[str, ...] = ("issued", "signed", "cancelled")
