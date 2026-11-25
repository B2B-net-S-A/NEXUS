"""Słowniki dokumentów pochodnych bez żadnych importów z aplikacji.

Czyta je model, migracja 0362 i siatka DDL w ``entrypoint.sh``. Siatka importuje
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
    # Aneks z własną nazwą (0723, 16.11.2026).
    "annex_custom",
    "termination_agreement",
    "termination_agreement_mandate",
    "termination_notice",
    "notice_withdrawal",
    "preliminary_cez",
    # Umowa o udziale w procesie rekrutacyjnym (0503, 21.10.2026).
    "preliminary_participation_jdg",
    "preliminary_participation_person",
    # Umowa przedwstępna na współpracę B2B (0744, 19.11.2026).
    "preliminary_b2b",
    # Warianty z kandydatem prowadzącym działalność (0778, 25.11.2026).
    "preliminary_cez_jdg",
    "preliminary_b2b_jdg",
    # Dokument ze wzoru własnego (0785, 25.11.2026) — który wzór i wersja:
    # ``template_key`` = ``custom_v<id wersji>``.
    "custom_template",
)

B2B_DOCUMENT_STATUSES: tuple[str, ...] = ("issued", "signed", "cancelled")
