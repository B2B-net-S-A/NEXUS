# Pomiar poprawek CV z generatora przy zatwierdzeniu (E3, 07.11.2026)

<!-- indeks: `generated_editor_html`, `cv_approved_edit_summary`, `cv_edit_report --weekly`, mianownik od startów, `replaced`, powód podmiany, `assisted`, `cv_command_applied` -->

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
- Blok to element bez bloków w środku (`cv_approved_docx.BLOCKS` + komórki
  tabeli), nie tylko `h1–h3 / p / li`: wklejka z Worda (cytat, tabela, `h4`, goły
  `div`) i tekst punktu nad zagnieżdżoną listą (wcięcie) też się liczą. Inaczej
  takie poprawki dawały fałszywe „bez zmian” — a ta liczba jest celem pomiaru.
- Koszt liniowy: jeden przebieg drzewa i porównanie wielozbiorów tekstów
  w części. Zniknięty i nowy blok w tej samej części to razem „zmieniony”,
  nadwyżka to „dodany” / „usunięty”. Same przestawienia = `changed`
  z `reordered: true` i pustym `parts`.
- Zatwierdzenie przy akceptacji DL-a do Cpro (10.11.2026) ma w `details`
  `approved_via: "dl_accept"`, a `user_id` to DL. Poprawki liczone są względem
  startu generatora, więc to dalej poprawki ludzi z edytora (zwykle rekrutera),
  nie DL-a; zatwierdzającego bierz z `approved_via`, nie z `user_id`.
- Zapis w SAVEPOINT-cie, każdy błąd (także odczytu treści) to ostrzeżenie w logu
  `[cv_edit_summary]` — zatwierdzenie przechodzi.

## Podmiana szkicu i powód (CV-1, CV-2, 08.11.2026)

Audyt 08.11.2026: miara od zatwierdzeń widziała 52% startów, bo CV wyrzucone
i zastąpione własnym plikiem nie zostawiało śladu. **Mianownikiem jest start
generatora, a nie zatwierdzenie.**

- `_write_stage_draft` i odrzucenie szkicu wołają `log_replaced_edits` przed
  nadpisaniem: ten sam `ACTION`, `status: "replaced"`, `edits_status` (co człowiek
  zdążył zmienić), `replace_kind` (`upload`, `import`, `copy`, `discard`). Nowa
  droga podmiany = wpis w `REPLACE_KINDS` (`services/cv_edit_summary.py`).
- Bez zapisanego startu (CV sprzed E3) wpisu nie ma; raport odtwarza takie podmiany
  z wpisów szkicu (`branded_cv_uploaded_in_recruitment` itd.), więc działa wstecz.
- „Cofnij” po cichej podmianie auto-CV: wpis `branded_cv_upload_undone` po podmianie
  znosi ją w raporcie, kolejny wpis też (ostatni wynik wygrywa).
- Powód podmiany: pigułki „Klient chce swój format” / „Generator pominął
  doświadczenie” / „Mam nowsze CV od kandydata” / „Inny” w potwierdzeniu
  „Zastąpić CV do klienta?” (`StageCvUpload`) i w tostcie po cichej podmianie
  auto-CV, tylko gdy szkic miał start. Można pominąć, bez pola tekstowego.
  `POST …/cv/branded/replace-reason` dopisuje `reason` do ostatniego wpisu
  `replaced` tej osoby. Inne drogi podmiany (okno „Użyj innego CV”, odrzucenie)
  powodu nie pytają.

## Poprawki maszyną (CV-3, 08.11.2026)

- `log_approved_edits` dopisuje `assisted: {qc_fixes, assistant_commands,
  assistant_applied}`: wpisy `cv_qc_fix_applied`, `cv_command_ai`
  i `cv_command_applied` od ostatniego startu.
- Każde nałożenie planu asystenta (`applyNow`: od razu po poleceniu, „Tak”,
  „Zastosuj zaznaczone”) wysyła `POST …/cv-ai/applied` z presetem i liczbą
  operacji, bez treści CV (`cv_command_applied`).
- Raport dzieli `changed` na „kod/asystent” (było zastosowanie) i „ręczne” (żadnego).
  „Kod/asystent” to **górna granica**: serwer nie widzi, czy człowiek dopisał coś
  jeszcze. Samo zapytanie asystenta (`assistant_commands`) niczego nie zmienia,
  więc nie liczy się do tej kolumny.

## Odczyt

- Tygodniowo per klient (odsetek CV bez poprawek, „tylko pogrubienia”, zmiany,
  trzy najczęściej zmieniane części), w kontenerze backendu:
  `python -m scripts.cv_edit_report --weekly --days 56`. Ostatni wpis CV
  w tygodniu liczy się raz; tydzień to kalendarz firmy. Podmiany nie wchodzą.
- Ten sam wydruk, drugi blok: **od startów** (ręczne i auto osobno, tydzień startu
  i cały okres): bez zmian, pogrubienia, zmiany, podmienione, szkic > 7 dni, w toku,
  zatwierdzone bez wpisu (sprzed E3), plus rodzaje i powody podmian. Liczony jest
  ostatni start CV w okresie. Porównanie „co zmienił generator” bierz stąd.
- Pełny raport po sekcjach (`python -m scripts.cv_edit_report --days 28`) bierze
  zapisany start jako bazę wprost; odtwarza renderer tylko dla CV sprzed E3.
- Wprost SQL: `SELECT details->>'status', count(*) FROM activities
  WHERE action = 'cv_approved_edit_summary' GROUP BY 1`.

Testy: `backend/tests/test_cv_edit_summary.py`, `test_cv_edit_summary_db.py`,
`test_cv_edit_report.py`.
