# Nordea: do kolejki Cpro dopiero po akceptacji Delivery Leada — raport

Gałąź `claude/slipro-duplicate-notifications-e01336`, 13.10.2026. Reguły:
`docs/claude/rekrutacja-tablica/nordea-akceptacja-dl-przed-cpro.md`.
Analiza, makiety (stan sprzed zmiany i propozycja) i decyzje D1–D6:
https://claude.ai/artifact/Si7j1pcC3cXxUKYMNVGWa1 — Artur: „zrób zgodnie z rekomendacjami”.

## Skąd ta zmiana

Zgłoszenie: osoba od Cpro dostaje „Do wrzucenia do Cpro”, gdy rekruter kończy QC, zanim Delivery Lead
Nordei zaakceptuje kandydata. Pomiar na produkcji (tylko odczyt, za zgodą Artura):

| Co | Liczba |
|---|---|
| Wejścia do kolejki „NORDEA: Wysłać do Cpro” w Traffit (10.09–11.10), zrobione przez DL-i | 292 z 301 |
| Wejścia do kolejki „Wysłać do Cpro” w NEXUSIE (12–13.10) bez Delivery Leada | 7 z 13 |
| Ruchy głównego DL-a Nordei w NEXUSIE (QC, kolejka, „Wysłane do Cpro”) | 0 |
| Dzwonki „Do wrzucenia do Cpro” bez stawki do Cpro w chwili dzwonka | 11 z 12 |
| Dzwonki z mailem wysłanym od razu | 12 z 12 |
| Ruchy na „Wysłane do Cpro” zrobione przez DL-a, nie osobę od Cpro | 8 z 10 |
| Osoby z dwoma identycznymi dzwonkami (dwie rekrutacje Nordei) | 2 z 10 |

Przyczyna: przy przenosinach z Traffita (v4–v5) przyjęliśmy „Nordea bez zmian: po QC kolejka Cpro”, a w
Traffit do kolejki wkładał Delivery Lead — ten ruch był akceptacją. NEXUS podpowiadał go rekruterowi,
serwer nie sprawdzał, kto wkłada, Nordea była wyłączona z przeglądu DL w pięciu miejscach, a o stawkę
pytało dopiero okno przy „Wysłane do Cpro”.

## Co się zmieniło

### Serwer

- `pipeline_move_rules.requires_dl_client_rate` / `assert_client_send_allowed(..., cpro=True)`: u Nordei
  wejście do kolejki Cpro i na „Wysłane do Cpro” z pominięciem kolejki wymaga uprawnienia wysyłki CV
  (`recruitment_manage`) i stawki — `/move` i `/bulk-move`. „✓ Wrzucone” z kolejki bez zmian.
- `stage_handoff_recipients`: „QC CV” u Nordei dzwoni do DL-a; zwrot z kolejki — do akceptującego i DL-a;
  „Wróć do poprawy” nie dzwoni do osoby od Cpro; `close_cpro_queue_bells` gasi „Do wrzucenia do Cpro”,
  gdy karta wychodzi z kolejki.
- `stage_notification_emitter`: dzwonek osoby od Cpro z nazwą od klienta i numerem (bez kwoty), treść
  „zaakceptował(a)”; prośba do DL-a u Nordei mówi o akceptacji do Cpro.
- `dl_send_queue`, `api/dl_review`, `api/pipeline._viewer_owns_dl_review`, `screening_fix_requests`,
  `cv_in_transit`: Nordea w przeglądzie DL (`cpro=True`, cel = etap Cpro).
- `move_requirements`: rekruter u Nordei — „Przekaż Delivery Leadowi”, DL — „Przejrzyj i zaakceptuj do Cpro”.
- `GET /api/board-tasks/cpro/queue`: `accepted`, `accepted_by_name`, `accepted_at`, `dl_note`.

### Ekrany

- Tablica: przegląd DL u Nordei z celem „Wysłać do Cpro” (karta, przeciąganie, dok, „Przesuń dalej”,
  `?review=1`, „po kolei”, „Porównaj”); karta w kolejce czeka na osobę od Cpro.
- Przegląd DL: „Stawka do Cpro”, „Akceptuj — do Cpro za …”, uwagi dla rekrutera i osoby od Cpro.
- Pas „Do wysłania do klienta” i okienko w pasku: dopisek „→ Cpro”.
- Kolejka Cpro: „✓ Zaakceptował(a): … · data”, „Bez akceptacji DL — do kolejki przekazał(a) …”, uwaga DL-a.
- Przewodnik Jarvisa `jobs.board`, inwentarz funkcji (`dl-review.cpro-accept`, `board.cpro-queue.acceptance`).

## Sprawdzenie

- Backend lokalnie (Python 3.12, bez bazy): ruff, format, testy jednostkowe zmienionych modułów zielone;
  testy z Postgresem — CI.
- Frontend lokalnie: `tsc --noEmit`, eslint zmienionych plików, vitest na zmienionych plikach testów (m.in. Tablica 105, przegląd DL 39, warsztat wysyłki 37) — zielone.
- Ekran na harnessach lokalnie nieprzeklikany: dysk miał 5–8 GB wolnego, a `next dev` zapełniał go
  wcześniej (zasada z 12.10). Sprawdzenie po wdrożeniu — sekcja w PR.

## Poza zakresem

- Trzy karty, które 13.10 stały w kolejce bez akceptacji, zostają (D6) — w kolejce mają „Bez akceptacji DL”.
- Przypomnienie po imporcie Traffita (`cpro_queue_reminder`) nie zmienione — sync jest wyłączony od 12.10.
