# Pomiar poprawek CV z generatora przy zatwierdzeniu (E3, 07.11.2026)

<!-- indeks: `generated_editor_html`, `cv_approved_edit_summary`, `cv_edit_report --weekly` -->

Pomiar 07.11.2026 (266 CV, raport: https://claude.ai/artifact/5Qd2t5rbuM6kpv12txwruc,
prywatny) musiał odtwarzać punkt startowy edytora kodem renderera. Dla 129 z 395
CV się nie udało, bo renderer zmienił się po generacji. Artur zdecydował (E3):
start zapisujemy, a zatwierdzenie samo liczy, co zmienił człowiek — żeby było
widać efekt zmian generatora bez kolejnego odtwarzania.

## Start edytora

- `capture_editor_origin` zapisuje w `branded_render_metadata` obok skrótu
  `generated_editor_html_sha256` samą treść startu: klucz `generated_editor_html`
  (`START_HTML_KEY` w `services/cv_edit_summary.py`). Bez migracji — metadane
  i tak idą do każdej wersji (`cv_document_versions.render_metadata`) i migawki.
- Start to czysta generacja, także przy „Napisz od nowa” ze scaleniem
  (`keep_edits`): scalony szkic jest już treścią poprawianą przez człowieka.
- Kopia z innej rekrutacji (`_apply_generated_from_other_job`) dostaje sam start,
  bez skrótu generacji — kopia ma inny nagłówek i nie przejmuje jej kontroli AI.
- CV z pliku Word, z innego CV etapu i sprzed 07.11.2026 startu nie mają;
  wpisu wtedy nie ma (nie zgadujemy, od czego zaczął człowiek).

## Wpis przy zatwierdzeniu

- `finalize_stage_cv` po wpisie `branded_cv_finalized` woła `log_approved_edits`:
  `Activity(action="cv_approved_edit_summary", entity_type="candidate_stage_cv")`.
  Ponowne zatwierdzenie po dołączeniu zgody (`review_override`) wpisu nie robi —
  treść jest ta sama.
- `details`: `status` (`unchanged` / `bold_only` / `changed`), `reordered`,
  `parts` (per część: `added`, `removed`, `changed`, `bold` — liczby bloków),
  `changed_parts`, `bold_parts`, liczby bloków i znaków przed i po, `job_id`,
  `document_version_id`, `version`, `generated_document_id`, `origin`
  (`generator` albo `generated_other_job`). **Żadnego tekstu CV** — repo i logi są
  publiczne, a wpisy przeżywają usunięcie kandydata. Pilnuje
  `test_summary_carries_no_cv_text`.
- Części jak w pomiarze 07.11: `title`, `considered_for`, `why_points`, `skills`,
  `languages`, `education`, `certifications`, `role`, `employer`, `duties`,
  `technologies`, `headings` (tytuły sekcji i etykiety), `other`. Klauzula zgody
  się nie liczy (jest stała).
- Koszt liniowy: jeden przebieg drzewa i porównanie wielozbiorów tekstów
  w części. Zniknięty i nowy blok w tej samej części to razem „zmieniony”,
  nadwyżka to „dodany” / „usunięty”. Same przestawienia = `changed`
  z `reordered: true` i pustym `parts`.
- Zapis w SAVEPOINT-cie, każdy błąd (także odczytu treści) to ostrzeżenie w logu
  `[cv_edit_summary]` — zatwierdzenie przechodzi.

## Odczyt

- Tygodniowo per klient (odsetek CV bez poprawek, „tylko pogrubienia”, zmiany,
  trzy najczęściej zmieniane części), w kontenerze backendu:
  `python -m scripts.cv_edit_report --weekly --days 56`. Ostatni wpis CV
  w tygodniu liczy się raz; tydzień to kalendarz firmy.
- Pełny raport po sekcjach (`python -m scripts.cv_edit_report --days 28`) bierze
  zapisany start jako bazę wprost; odtwarza renderer tylko dla CV sprzed E3.
- Wprost SQL: `SELECT details->>'status', count(*) FROM activities
  WHERE action = 'cv_approved_edit_summary' GROUP BY 1`.

Testy: `backend/tests/test_cv_edit_summary.py`, `test_cv_edit_summary_db.py`,
`test_cv_edit_report.py`.
