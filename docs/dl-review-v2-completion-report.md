# Przegląd Delivery Leada v2 (D6, D9, D10) — raport

Gałąź `claude/dl-review-pr2`, 08.10.2026. Plan: `docs/candidate-path-d1-d10-plan.md`, sekcja „PR 2”.

## Czeka na Artura

- Przegląd kodu i otwarcie PR-a (PR nie jest otwarty z tej sesji).
- Po wdrożeniu: przeklikanie przeglądu DL na produkcji przy 1280 × 720 i 1440 px (lokalnie sprawdzony tylko
  harness `/preview/dl-review`, bez zalogowanej sesji).

## Co się zmieniło

### D6 — „Wróć do poprawy…” z listą pól

- `StageMove.fix_fields` (najwyżej 30 kluczy). Serwer przyjmuje listę wyłącznie przy ruchu z kolumny „QC CV”
  na „Zweryfikowany” poza Nordeą (`FIX_FIELDS_NOT_ALLOWED`), nieznany klucz = `FIX_FIELDS_INVALID` (422).
- Prośba to wiersz `screening_form_versions` z `action="fix_requested"` i `meta={stage_id, fields}`
  (`services/screening_fix_requests.py`) — bez nowej kolumny i bez migracji.
- `GET /api/screening-form` niesie `fix_request` (pola, autor, data, uwaga, stan „do poprawy / poprawione”)
  i `handback_stage_def_id`. Formularz rekrutera: baner, podświetlone pola, „Zapisz i oddaj do przeglądu DL”.
- Dzwonek zwrotu dopisuje „Do poprawy (N): …” i otwiera panel na screeningu; „Twoje CV w drodze” pokazuje pola
  (`fix_labels`).

### D9 — kontekst przeglądu w trzech kolumnach

- `GET /api/dl-review/context?candidate_id&job_id` (`api/dl_review.py`, `services/dl_review.py`), bramka
  `recruitment_manage` + odczyt rekrutacji.
- Wymagania klienta a kandydat ze źródłem dowodu (profil, CV, notatka, rozmowa), ocena rekrutera, ryzyka,
  budżet, punkty odniesienia (stawki konsultantów u klienta — mediany bez nazwisk, ostatni kontrakt osoby,
  wcześniejsze wysyłki), podpowiedź stawki do klienta.
- Redakcja: kwoty klienta tylko przy `can_read_client_finance`, stawki do klienta tylko przy
  `user_can_view_client_rate`.
- Wyniesienie pomocników stawek z `api/clients.py` i `api/candidate_rates.py` do
  `services/client_consultant_rates.py` (stare nazwy zostały jako aliasy).
- Front: `components/v2/recruitment/dl-review/` (`RequirementsColumn`, `CvColumn`, `DecisionPanel`,
  `ReturnForFixDialog`, `DlReviewQueueDialog`), marża w `lib/dl-review-margin.ts`. Trzy kolumny od ~1100 px
  szerokości panelu; na Tablicy panel `split`, na pulpicie okno `min(96vw, 1440px)`.

### D10 — porównanie kolejki

- `GET /api/dl-review/jobs/{job_id}/queue` — osoby w „QC CV” jednej rekrutacji, stała liczba zapytań, najwyżej 50,
  Nordea = pusta lista z `cpro_client: true`.
- Wejścia: „Porównaj (N)” przy grupie rekrutacji na pulpicie i w nagłówku kolumny „QC CV” na Tablicy.

### Pozostałe

- Harness `/preview/dl-review` (`?state=queue`, `?state=returned`), dwa nowe adresy w
  `e2e/responsive-preview.spec.ts`, sześć wpisów w `recruitment-feature-inventory.json`, przewodniki Jarvisa
  (`jobs.board`, `jobs.person`, nowa kotwica `jobs.board.dl-compare`) przestemplowane.
- CLAUDE.md: nowa sekcja „Przegląd Delivery Leada v2”, poprawione zdania o przeglądzie bez marży (Pipeline v4,
  0413).

## Weryfikacja

| Część | Stan | Dowód |
|---|---|---|
| Backend bez bazy | zielone | 108 testów (strażnicy: przewodniki, macierz uprawnień, sufit sekcji, czytelnicy karty, część czysta nowych plików) + 41 (route authz, job scope, logi, role); ruff check/format na zmienionych plikach |
| Backend z bazą | niepotwierdzone | 16 testów (fix request end-to-end, macierz redakcji, liczba zapytań kolejki, dzwonek, CV w drodze) czeka na CI — lokalnie brak Postgresa (bez Dockera) |
| Frontend | zielone | `vitest` 18 plików / 546 testów (przegląd DL, formularz, pulpit, Tablica, harness, pomoc, inwentarz, granice pakietów); `type-check`; `eslint` na zmienionych plikach; `check-unreachable-modules` 0 nowych |
| Harness | sprawdzony wzrokowo | 1440 × 900 i 1280 × 720: trzy kolumny, tabela porównania, formularz po zwrocie |

## Znalezione

- Etykieta „Stawka ponad budżet o 0 zł/h” przy nadwyżce poniżej złotówki — poprawione (kwota z groszami),
  z testem.
- Przy 1280 px kolumna wymagań ma ~260 px — status stoi teraz zaraz po nazwie wymagania, reszta pod
  przewijaniem tabeli.
- Zapis prośby podbija wersję formularza: rekruter z otwartym formularzem dostaje 409 i formularz wczytuje się
  ponownie z zachowaniem jego zmian (świadome — inaczej nie zobaczyłby prośby).
- `labels_for_stages` filtruje wersje po kandydatach (brak indeksu po `meta->>'stage_id'`); przy obecnej skali
  wystarczy.
- Wymagania liczą `dz_review.job_requirements` + `must_text_evidence.mention_sources`, nie
  `requirement_contract` — ta sama pisownia co QC i przegląd DZ.
- Test liczby zapytań kolejki (3 vs 10 osób) może być wrażliwy na rozgrzewkę cache — jeśli w CI zacznie migać,
  porównywać po rozgrzaniu obu przebiegów.
